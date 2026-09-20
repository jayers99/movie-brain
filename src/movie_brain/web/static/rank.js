(() => {
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const $ = (sel) => document.querySelector(sel);
  const main = $('#rank');
  const state = { session: null, order: null, details: {} };
  // Six modes on one page (order spec O3, ranking-pool spec P5, every tier since 2026-09-15):
  // the hash carries the mode so a reload stays put. Modes: 'tiers', 'order-1' … 'order-5'
  // (ORDER_TIERS mirrors domain/rank.py). '#order' (pre-phase-A bookmarks) reads as tier 1.
  const ORDER_TIERS = [1, 2, 3, 4, 5];
  const mode = () => {
    const h = location.hash;
    if (h === '#order') return 'order-1';
    const m = /^#order-(\d)$/.exec(h);
    return m && ORDER_TIERS.includes(Number(m[1])) ? `order-${m[1]}` : 'tiers';
  };
  const isOrder = () => mode().startsWith('order-');
  const orderTier = () => Number(mode().slice(6)) || 1;
  const setMode = (m) => { if (mode() !== m) location.hash = m === 'tiers' ? '' : `#${m}`; };

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
    for (const id of ['setup', 'pair', 'done', 'order-empty', 'order-done', 'order-stuck']) $('#' + id).hidden = id !== which;
    $('#progress').hidden = !state.session || !state.session.session;
    for (const el of document.querySelectorAll('.tiers-only')) el.hidden = mode() !== 'tiers';
    for (const el of document.querySelectorAll('.order-only')) el.hidden = !isOrder();
    for (const t of document.querySelectorAll('.tab')) t.setAttribute('aria-current', String(t.dataset.mode === mode()));
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

  const sideHtml = (side, d, heading, opts = { unseen: true }) => {
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
    const unseenBtn = opts.unseen ? `<button class="chip unseen" data-side="${side}" title="${side === 'candidate' ? '1' : '2'}">Have not seen</button>` : '';
    const titleHtml = opts.unseen ? `<button class="title-unseen" data-side="${side}">${esc(d.title)}</button>` : esc(d.title);
    return `<div class="heading">${esc(heading)}</div>
      <div class="buttons"><button class="chip primary better" data-side="${side}" title="${side === 'candidate' ? '←' : '→'}">Better</button>${unseenBtn}</div>
      ${poster}
      <div class="title">${titleHtml}</div>
      <div class="meta">${esc(dirYear)}</div>
      <dl class="prompt">${prompts}</dl>`;
  };

  const renderPair = async () => {
    const s = state.session;
    const [c, a] = await Promise.all([detail(s.pair.candidate.film_id), detail(s.pair.anchor.film_id)]);
    $('.side.candidate').innerHTML = sideHtml('candidate', c, 'Candidate');
    $('.side.anchor').innerHTML = sideHtml('anchor', a, `Tier ${s.pair.tier} anchor`);
    show('pair');
    main.dataset.state = 'pair';
  };

  const renderOrderPair = async () => {
    const p = state.order.pair;
    const [c, o] = await Promise.all([detail(p.candidate.film_id), detail(p.other.film_id)]);
    $('.side.candidate').innerHTML = sideHtml('candidate', c, 'Candidate', { unseen: false });
    $('.side.anchor').innerHTML = sideHtml('anchor', o, `Position ${p.position} of ${p.of}`, { unseen: false });
    show('pair');
    main.dataset.state = 'order';
  };

  const renderProgress = () => {
    const s = state.session;
    if (!s || !s.session) return;
    $('#placed').textContent = s.placed; $('#remaining').textContent = s.remaining; $('#unseen-count').textContent = s.unseen;
    for (const [t, n] of Object.entries(s.tally)) $(`#progress .tally span[data-tier="${t}"]`).textContent = n;
    if (state.order) { $('#ordered').textContent = state.order.ordered; $('#order-tier').textContent = orderTier(); $('#order-remaining').textContent = state.order.remaining; }
    $('#undo').disabled = !(isOrder() && state.order ? state.order.can_undo : s.can_undo);
  };

  const refresh = async () => {
    state.session = await api('GET', '/api/rank/session');
    state.order = null;
    const s = state.session;
    if (isOrder()) {
      if (!s.session) { show('order-empty'); main.dataset.state = 'order_nosession'; return; }
      state.order = await api('GET', `/api/rank/order?tier=${orderTier()}`);
      if (state.order.corrupt.length) note(`${state.order.corrupt.length} film(s) have an unreadable order log and were skipped`);
      renderProgress();
      if (state.order.done) { show('order-done'); main.dataset.state = 'order_done'; return; }
      // Not done and nothing to ask: every film still waiting has an unreadable order log.
      if (!state.order.pair) {
        const ids = state.order.corrupt;
        $('#order-stuck-count').textContent = `${ids.length} film${ids.length === 1 ? '' : 's'}`;
        $('#order-stuck-films').innerHTML = ids.map((id) => `<a href="/?film=${Number(id)}">film #${Number(id)}</a>`).join(' · ');
        show('order-stuck'); main.dataset.state = 'order_stuck'; return;
      }
      return renderOrderPair();
    }
    renderProgress();
    if (!s.session) return renderSetup([1, 2, 3, 4, 5], 'Confirm or swap the five anchors, then start.');
    if (s.needs_anchor.length) return renderSetup(s.needs_anchor, 'That anchor is out. Pick a replacement for the tier.');
    if (s.done) { show('done'); main.dataset.state = 'done'; return; }
    return renderPair();
  };

  // Every action re-reads the state even when the request fails: the pair on screen can be
  // stale — its candidate moved to another tier from the dashboard drawer (move-tier spec
  // M10) — and the server's 409 must be followed by a fresh pair, not the same dead one.
  const act = async (fn) => { try { await fn(); } finally { await refresh(); } };
  const verdict = async (side) => {
    if (isOrder()) {
      const o = state.order; if (!o || !o.pair) return;
      return act(() => api('POST', '/api/rank/order/verdict', { tier: orderTier(), film_id: o.pair.candidate.film_id, other_film_id: o.pair.other.film_id, verdict: side === 'candidate' ? 'better' : 'worse' }));
    }
    const s = state.session; if (!s || !s.pair) return;
    return act(() => api('POST', '/api/rank/verdict', { film_id: s.pair.candidate.film_id, anchor_tier: s.pair.tier, verdict: side === 'candidate' ? 'better' : 'worse' }));
  };
  // One request serves both: a plain Pass defers the candidate; "Have not seen" on a side
  // is that same pass with the side's flag set, sent at once (owner ruling 2026-09-13 —
  // the spec's D9 mark-then-Pass two-step is gone, so nothing is ever "marked" client-side).
  const pass = async (unseen = {}) => {
    if (isOrder()) {
      const o = state.order; if (!o || !o.pair) return;
      return act(() => api('POST', '/api/rank/order/pass', { tier: orderTier(), film_id: o.pair.candidate.film_id }));
    }
    const s = state.session; if (!s || !s.pair) return;
    return act(() => api('POST', '/api/rank/pass', { film_id: s.pair.candidate.film_id, candidate_unseen: unseen.candidate === true, anchor_unseen: unseen.anchor === true }));
  };
  const unseen = (side) => (isOrder() ? Promise.resolve() : pass({ [side]: true }));   // O6: inert in order mode
  const undo = async () => { if ($('#undo').disabled) return; return act(() => api('POST', '/api/rank/undo')); };

  $('#pair').addEventListener('click', (e) => {
    const better = e.target.closest('button.better'); if (better) return enqueue(() => verdict(better.dataset.side));
    const un = e.target.closest('button.unseen, button.title-unseen'); if (un) return enqueue(() => unseen(un.dataset.side));
  });
  $('#pass').addEventListener('click', () => enqueue(() => pass()));
  $('#undo').addEventListener('click', () => enqueue(undo));
  $('#save').addEventListener('click', () => enqueue(async () => {
    const r = await api('POST', '/api/rank/save', { name: $('#list-name').value });
    note(`saved ${r.entries} films as “${r.name}”`);
  }));

  for (const t of document.querySelectorAll('.tab')) t.addEventListener('click', () => setMode(t.dataset.mode));
  window.addEventListener('hashchange', () => enqueue(refresh));

  document.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return; // Cmd/Ctrl+Left is browser back on some platforms, not a verdict
    if (e.target.matches('input, select, textarea') || !['pair', 'order', 'done', 'order_done'].includes(main.dataset.state)) return;
    const k = e.key;
    if (k === 'ArrowLeft') { e.preventDefault(); enqueue(() => verdict('candidate')); }
    else if (k === 'ArrowRight') { e.preventDefault(); enqueue(() => verdict('anchor')); }
    else if (k === '1') enqueue(() => unseen('candidate'));
    else if (k === '2') enqueue(() => unseen('anchor'));
    else if (k === ' ') { e.preventDefault(); enqueue(() => pass()); }
    else if (k === 'u' || k === 'U') enqueue(undo);
  });

  refresh();
})();
