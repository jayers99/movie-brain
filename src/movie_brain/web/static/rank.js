(() => {
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const $ = (sel) => document.querySelector(sel);
  const main = $('#rank');
  const state = { session: null, marked: { candidate: false, anchor: false }, details: {} };

  // Every user action (click or key) that touches the session must run strictly after the
  // previous one's request-and-re-render has finished, or a fast second action reads
  // `state.session` before the first's refresh() has landed and posts a stale film_id — the
  // server then answers 409 "no longer current" against its own now-newer pair. A plain click
  // handler has no such ordering guarantee on its own, so every dispatch below goes through
  // this one-at-a-time queue instead of running immediately.
  let queue = Promise.resolve();
  const enqueue = (fn) => { queue = queue.then(fn, fn).catch((e) => console.error(e)); return queue; };

  const api = async (method, url, body) => {
    const r = await fetch(url, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    const json = await r.json().catch(() => ({}));
    if (!r.ok) { note(json.error || `${method} ${url} failed`); throw new Error(json.error || r.status); }
    return json;
  };
  const note = (text) => { const n = $('#note'); n.textContent = text; setTimeout(() => { if (n.textContent === text) n.textContent = ''; }, 4000); };

  const show = (which) => {
    for (const id of ['setup', 'pair', 'done']) $('#' + id).hidden = id !== which;
    $('#progress').hidden = !state.session || !state.session.session;
  };

  // --- setup / needs-anchor -------------------------------------------------
  const renderSetup = async (tiers, lead) => {
    const prop = await api('GET', '/api/rank/proposal');
    $('#setup-lead').textContent = lead;
    $('#anchor-cards').innerHTML = tiers.map((t) => {
      const p = prop.proposal[t];
      const choices = prop.choices[t] || [];
      const opts = choices.map((c) => `<option value="${c.film_id}" ${p && c.film_id === p.film_id ? 'selected' : ''}>${esc(c.title)}${c.year ? ` (${c.year})` : ''}${c.score != null ? ` · ${c.score}` : ''}</option>`).join('');
      return `<div class="anchor-card" data-tier="${t}"><div class="tier">Tier ${t} anchor</div><div class="anchor-title">${p ? esc(p.title) : '— choose —'}</div><select class="anchor-swap" data-tier="${t}"><option value="">choose…</option>${opts}</select></div>`;
    }).join('');
    show('setup');
    main.dataset.state = tiers.length === 5 ? 'setup' : 'needs_anchor';
  };

  $('#anchor-cards').addEventListener('change', (e) => {
    const sel = e.target.closest('select.anchor-swap'); if (!sel) return;
    const card = sel.closest('.anchor-card');
    card.querySelector('.anchor-title').textContent = sel.selectedOptions[0]?.textContent.replace(/ · \d+$/, '') || '— choose —';
  });

  $('#start').addEventListener('click', () => enqueue(async () => {
    const cards = [...document.querySelectorAll('.anchor-card')];
    const chosen = Object.fromEntries(cards.map((c) => [c.dataset.tier, Number(c.querySelector('select').value) || null]));
    if (Object.values(chosen).some((v) => !v)) { note('Choose an anchor for every tier shown'); return; }
    if (!state.session || !state.session.session) {
      await api('POST', '/api/rank/session', { anchors: chosen });
    } else {
      for (const [tier, film_id] of Object.entries(chosen)) await api('PUT', '/api/rank/anchor', { tier: Number(tier), film_id });
    }
    await refresh();
  }));

  // --- the pair -------------------------------------------------------------
  const detail = async (id) => {
    if (!state.details[id]) state.details[id] = await fetch(`/api/films/${id}`).then((r) => r.json());
    return state.details[id];
  };

  const sideHtml = (side, d, heading, marked) => {
    const p = d.payload || {};
    const poster = p.Poster && p.Poster !== 'N/A' ? `<img class="poster" src="${esc(p.Poster)}" alt="">` : '<div class="poster placeholder"></div>';
    const cast = d.credits && d.credits.cast && d.credits.cast.length ? d.credits.cast.slice(0, 4).map((c) => c.name).join(', ') : (p.Actors && p.Actors !== 'N/A' ? p.Actors : '');
    const blurb = d.overview || (p.Plot && p.Plot !== 'N/A' ? p.Plot : '');
    const prompts = [
      blurb ? `<div>${esc(blurb)}</div>` : '',
      cast ? `<div><dt>Cast</dt><dd>${esc(cast)}</dd></div>` : '',
      p.Runtime && p.Runtime !== 'N/A' ? `<div><dt>Runtime</dt><dd>${esc(p.Runtime)}</dd></div>` : '',
      d.imdb != null || d.metacritic != null ? `<div><dt>IMDb</dt><dd>${d.imdb ?? '–'}</dd> · <dt>Metacritic</dt><dd>${d.metacritic ?? '–'}</dd></div>` : '',
      d.my_rating != null ? `<div><dt>My rating</dt><dd>${d.my_rating}</dd></div>` : '',
    ].join('');
    const dirYear = [d.year, d.director].filter(Boolean).join(' · ');
    return `<div class="heading">${esc(heading)}</div>
      <div class="buttons"><button class="chip primary better" data-side="${side}" title="${side === 'candidate' ? '←' : '→'}">Better</button><button class="chip unseen" data-side="${side}" aria-pressed="${marked}" title="${side === 'candidate' ? '1' : '2'}">Have not seen</button></div>
      ${poster}
      <div class="title"><button class="title-unseen" data-side="${side}">${esc(d.title)}</button></div>
      <div class="meta">${esc(dirYear)}</div>
      <dl class="prompt">${prompts}</dl>`;
  };

  const renderPair = async () => {
    const s = state.session;
    const [c, a] = await Promise.all([detail(s.pair.candidate.film_id), detail(s.pair.anchor.film_id)]);
    $('.side.candidate').innerHTML = sideHtml('candidate', c, 'Candidate', state.marked.candidate);
    $('.side.anchor').innerHTML = sideHtml('anchor', a, `Tier ${s.pair.tier} anchor`, state.marked.anchor);
    show('pair');
    main.dataset.state = 'pair';
  };

  const renderProgress = () => {
    const s = state.session;
    if (!s || !s.session) return;
    $('#placed').textContent = s.placed; $('#remaining').textContent = s.remaining; $('#unseen-count').textContent = s.unseen;
    for (const [t, n] of Object.entries(s.tally)) $(`#progress .tally span[data-tier="${t}"]`).textContent = n;
    $('#undo').disabled = !s.can_undo;
  };

  const refresh = async () => {
    state.session = await api('GET', '/api/rank/session');
    state.marked = { candidate: false, anchor: false };
    renderProgress();
    const s = state.session;
    if (!s.session) return renderSetup([1, 2, 3, 4, 5], 'Confirm or swap the five anchors, then start.');
    if (s.needs_anchor.length) return renderSetup(s.needs_anchor, 'That anchor is out. Pick a replacement for the tier.');
    if (s.done) { show('done'); main.dataset.state = 'done'; return; }
    return renderPair();
  };

  const verdict = async (side) => {
    const s = state.session; if (!s || !s.pair) return;
    await api('POST', '/api/rank/verdict', { film_id: s.pair.candidate.film_id, anchor_tier: s.pair.tier, verdict: side === 'candidate' ? 'better' : 'worse' });
    await refresh();
  };
  const toggleMark = (side) => {
    state.marked[side] = !state.marked[side];
    const b = document.querySelector(`.side.${side} button.unseen`); if (b) b.setAttribute('aria-pressed', String(state.marked[side]));
  };
  const pass = async () => {
    const s = state.session; if (!s || !s.pair) return;
    await api('POST', '/api/rank/pass', { film_id: s.pair.candidate.film_id, candidate_unseen: state.marked.candidate, anchor_unseen: state.marked.anchor });
    await refresh();
  };
  const undo = async () => { if ($('#undo').disabled) return; await api('POST', '/api/rank/undo'); await refresh(); };

  $('#pair').addEventListener('click', (e) => {
    const better = e.target.closest('button.better'); if (better) return enqueue(() => verdict(better.dataset.side));
    const un = e.target.closest('button.unseen, button.title-unseen'); if (un) return enqueue(() => toggleMark(un.dataset.side));
  });
  $('#pass').addEventListener('click', () => enqueue(pass));
  $('#undo').addEventListener('click', () => enqueue(undo));
  $('#save').addEventListener('click', () => enqueue(async () => {
    const r = await api('POST', '/api/rank/save', { name: $('#list-name').value });
    note(`saved ${r.entries} films as “${r.name}”`);
  }));

  document.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return; // Cmd/Ctrl+Left is browser back on some platforms, not a verdict
    if (e.target.matches('input, select, textarea') || main.dataset.state !== 'pair') return;
    const k = e.key;
    if (k === 'ArrowLeft') { e.preventDefault(); enqueue(() => verdict('candidate')); }
    else if (k === 'ArrowRight') { e.preventDefault(); enqueue(() => verdict('anchor')); }
    else if (k === '1') enqueue(() => toggleMark('candidate'));
    else if (k === '2') enqueue(() => toggleMark('anchor'));
    else if (k === ' ') { e.preventDefault(); enqueue(pass); }
    else if (k === 'u' || k === 'U') enqueue(undo);
  });

  refresh();
})();
