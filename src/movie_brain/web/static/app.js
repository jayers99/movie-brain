(() => {
  'use strict';
  const ROW_H = 36, OVERSCAN = 10;
  const TOP_SERVICES = 3;  // drawer: services shown before the ⋯ more disclosure
  const COLS = ['title', 'year', 'director', 'language', 'metacritic', 'rt', 'imdb', 'my_rating'];
  const DEFAULT_LANG = 'English';
  const state = {
    films: [], cfg: null, chips: new Set(), scope: 'reachable',
    cols: { title: '', director: '', languages: new Set(), yearMin: null, yearMax: null, mcMin: null, mcMax: null, rtMin: null, rtMax: null, imdbMin: null, imdbMax: null },
    sort: null,            // {col, dir} or null = default
    filtered: [], openFilm: null,
  };
  const $ = (s) => document.querySelector(s);
  const tbody = $('#films tbody'), wrap = $('#table-wrap');

  // ---- canned predicates (mirror domain/filters.py; thresholds come from /api/config) ----
  const daysBetween = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000);
  const printedRank = (e) => {
    const m = /^=?(\d+)$/.exec(e.rank_label ?? '');
    return m ? Number(m[1]) : e.rank;
  };
  // mirrors domain/filters.py::canon_score — no membership floor (design D12)
  const canonScore = (f) => (f.lists || []).reduce((t, e) => {
    if (!e.ordered || !e.size) return t + e.trust;
    return t + e.trust * (1 - (printedRank(e) - 1) / e.size);
  }, 0);
  const isCanon = (f) => (f.lists || []).length > 0;
  const CHIP_PREDICATES = {
    leaving: (f) => f.leaving_date != null,
    unrated: (f) => f.my_rating == null,
    mine: (f) => f.my_rating != null && f.my_rating >= 1,
    pending: (f) => f.pending || f.found === false,
    top_ratings: (f) => (f.metacritic != null && f.metacritic >= state.cfg.canned_thresholds.top_mc)
      || (f.rt != null && f.rt >= state.cfg.canned_thresholds.top_rt)
      || (f.imdb != null && f.imdb >= state.cfg.canned_thresholds.top_imdb),
    recent: (f) => f.first_seen != null && daysBetween(f.first_seen, state.cfg.today) <= state.cfg.canned_thresholds.recent_days,
    departed: (f) => f.departed,
    new_arrivals: (f) => (f.new_on || []).some((t) => daysBetween(t.appeared_on, state.cfg.today) <= state.cfg.canned_thresholds.new_arrival_days),
    watchlist: (f) => f.watchlisted,
    owned: (f) => f.owned,
    not_owned: (f) => !f.owned,
    needs_revisit: (f) => f.needs_revisit,
    suspect: (f) => f.audit != null,
    multi_list: (f) => (f.lists || []).length >= state.cfg.canned_thresholds.multi_list,
    acquire: (f) => !f.owned
      && (isCanon(f) || (f.metacritic != null && f.metacritic >= state.cfg.canned_thresholds.top_mc)),
  };

  // ---- scope ----
  // reachable = something I can act on today: a current listing on a service I pay for (svod or
  // store, Criterion included), or a film I own, rated, or watchlisted. Discovery films with no
  // listing (nothing to watch or buy) are hidden here, visible only under 'all'.
  const SCOPES = ['reachable', 'criterion', 'all'];
  const SCOPE_LABELS = { reachable: 'Reachable', criterion: 'Criterion only', all: 'All films' };
  const reachable = (f) => (f.criterion && !f.departed) || (f.services || []).some((s) => s.subscribed)
    || f.owned || f.watchlisted || f.my_rating != null;
  const inScope = (f) => state.scope === 'all' || (state.scope === 'criterion' ? f.criterion : reachable(f));

  // ---- filtering / sorting ----
  const inRange = (v, lo, hi) => v != null && (lo == null || v >= lo) && (hi == null || v <= hi);
  function rowMatches(f) {
    if (!inScope(f)) return false;
    for (const c of state.chips) if (!CHIP_PREDICATES[c](f)) return false;
    const k = state.cols;
    if (k.title && !f.title.toLowerCase().includes(k.title)) return false;
    if (k.director && !(f.director || '').toLowerCase().includes(k.director)) return false;
    if (k.languages.size) {
      const langs = (f.language || '').split(',').map((s) => s.trim());
      if (![...k.languages].some((l) => langs.includes(l))) return false;
    }
    if ((k.yearMin != null || k.yearMax != null) && !inRange(f.year, k.yearMin, k.yearMax)) return false;
    if ((k.mcMin != null || k.mcMax != null) && !inRange(f.metacritic, k.mcMin, k.mcMax)) return false;
    if ((k.rtMin != null || k.rtMax != null) && !inRange(f.rt, k.rtMin, k.rtMax)) return false;
    if ((k.imdbMin != null || k.imdbMax != null) && !inRange(f.imdb, k.imdbMin, k.imdbMax)) return false;
    return true;
  }
  const byTitle = (a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: 'base' });
  function compare(a, b) {
    if (!state.sort) {  // default hierarchy: metacritic, ties → rt, ties → imdb (each desc, missing after present), then title
      if (state.chips.has('acquire')) {  // tier 1 (on a list) above tier 2 (metacritic only), then canon score desc
        const ta = isCanon(a) ? 1 : 0, tb = isCanon(b) ? 1 : 0;
        if (ta !== tb) return tb - ta;
        const c = canonScore(b) - canonScore(a);
        if (c !== 0) return c;
      }
      if (state.chips.has('suspect')) {  // suspect chip active: audit score desc leads, then the usual hierarchy
        const c = (b.audit?.score ?? 0) - (a.audit?.score ?? 0);
        if (c !== 0) return c;
      }
      for (const key of ['metacritic', 'rt', 'imdb']) {
        if ((a[key] == null) !== (b[key] == null)) return a[key] == null ? 1 : -1;
        if (a[key] != null && a[key] !== b[key]) return b[key] - a[key];
      }
      return byTitle(a, b);
    }
    const { col, dir } = state.sort, va = a[col], vb = b[col];
    if (va == null || vb == null) return va == null && vb == null ? byTitle(a, b) : va == null ? 1 : -1;
    let c = typeof va === 'number' ? va - vb : String(va).localeCompare(String(vb), undefined, { sensitivity: 'base' });
    if (c === 0) c = byTitle(a, b);
    return dir === 'asc' ? c : -c;
  }
  function applyFilters() {
    state.filtered = state.films.filter(rowMatches).sort(compare);
    tbody.dataset.count = state.filtered.length;
    const scoped = state.films.filter(inScope).length;
    $('#count-showing').textContent = `Showing ${state.filtered.length} of ${scoped}`;
    renderRows();
    syncUrl();
  }

  // ---- summary (mirrors Repository.summary) ----
  function renderCounts() {
    const f = state.films.filter((x) => x.criterion);
    const n = (p) => f.filter(p).length;
    $('#count-films').textContent = f.length;
    $('#count-rated').textContent = n((x) => x.found === true);
    $('#count-pending').textContent = n((x) => x.pending);
    $('#count-unmatched').textContent = n((x) => x.found === false);
    $('#count-leaving').textContent = n((x) => x.leaving_date != null);
    $('#count-mine').textContent = n((x) => x.my_rating != null);
    $('#count-departed').textContent = n((x) => x.departed);
    $('#count-discovery').textContent = state.films.length - f.length;
    $('#count-owned').textContent = state.films.filter((x) => x.owned).length;
  }

  // ---- virtual-scrolled rows ----
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (v, suffix = '') => (v == null ? '—' : `${v}${suffix}`);
  function rowHtml(f) {
    const link = f.url ? `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.title)}</a>` : esc(f.title);
    const listCount = (f.lists || []).length;
    // An owned film already carries the "owned" badge, and its best source IS that purchase —
    // a second badge saying so would state the same fact twice on the same row.
    const best = f.owned ? null : f.best_source;
    const watchBadge = best && best.subscribed
      ? ` <span class="badge-watch" title="Best source: ${esc(best.name)}">${esc(best.name)}</span>` : '';
    const title = link + (f.departed ? ' <span class="badge-gone" title="No longer on the Criterion Channel">gone</span>' : '')
      + (listCount > 0 ? ` <span class="badge-lists" title="on ${listCount} curated list${listCount === 1 ? '' : 's'}">${listCount} list${listCount === 1 ? '' : 's'}</span>` : '')
      + (f.owned ? ' <span class="badge-owned" title="Owned on Apple TV">owned</span>' : '')
      + watchBadge;
    return `<tr data-id="${f.id}"${f.departed ? ' class="departed"' : ''}>
      <td class="c-title">${title}</td><td class="c-year">${fmt(f.year)}</td><td class="c-director">${esc(f.director) || '—'}</td>
      <td class="c-language">${esc(f.language) || '—'}</td><td class="c-metacritic num">${fmt(f.metacritic)}</td>
      <td class="c-rt num">${fmt(f.rt, '%')}</td><td class="c-imdb num">${f.imdb == null ? '—' : f.imdb.toFixed(1)}</td>
      <td class="c-rating num"><input class="rating" maxlength="2" data-id="${f.id}" value="${f.my_rating ?? ''}" aria-label="My rating"></td>
      <td class="c-info"><button class="info" data-id="${f.id}" aria-label="Details">ⓘ</button></td></tr>`;
  }
  function renderRows() {
    if (state.films.length === 0) {
      tbody.innerHTML = `<tr class="empty-state"><td colspan="9">No films yet — run <code>movie-brain import-legacy</code> or <code>movie-brain sync</code>.</td></tr>`;
      return;
    }
    const total = state.filtered.length;
    const start = Math.max(0, Math.floor(wrap.scrollTop / ROW_H) - OVERSCAN);
    const end = Math.min(total, Math.ceil((wrap.scrollTop + wrap.clientHeight) / ROW_H) + OVERSCAN);
    const top = start * ROW_H, bottom = (total - end) * ROW_H;
    tbody.innerHTML =
      (top ? `<tr class="spacer"><td colspan="9" style="height:${top}px"></td></tr>` : '') +
      state.filtered.slice(start, end).map(rowHtml).join('') +
      (bottom ? `<tr class="spacer"><td colspan="9" style="height:${bottom}px"></td></tr>` : '');
  }
  wrap.addEventListener('scroll', () => requestAnimationFrame(renderRows));

  // ---- URL state ----
  function syncUrl(push = false) {
    const p = new URLSearchParams();
    if (state.chips.size) p.set('chips', [...state.chips].join(','));
    if (state.scope !== 'reachable') p.set('scope', state.scope);
    const k = state.cols;
    if (k.title) p.set('title', k.title);
    if (k.director) p.set('director', k.director);
    if (k.languages.size === 0) p.set('lang', 'any');
    else if (!(k.languages.size === 1 && k.languages.has(DEFAULT_LANG))) p.set('lang', [...k.languages].join('|'));
    for (const [name, lo, hi] of [['year', k.yearMin, k.yearMax], ['mc', k.mcMin, k.mcMax], ['rt', k.rtMin, k.rtMax], ['imdb', k.imdbMin, k.imdbMax]]) {
      if (lo != null || hi != null) p.set(name, `${lo ?? ''}-${hi ?? ''}`);
    }
    if (state.sort) p.set('sort', `${state.sort.col}:${state.sort.dir}`);
    if (state.openFilm != null) p.set('film', state.openFilm);
    const qs = p.toString();
    history[push ? 'pushState' : 'replaceState'](null, '', qs ? `?${qs}` : location.pathname);
  }
  function readUrl() {
    const p = new URLSearchParams(location.search);
    state.chips = new Set((p.get('chips') || '').split(',').filter((c) => c in CHIP_PREDICATES));
    state.scope = SCOPES.includes(p.get('scope')) ? p.get('scope') : 'reachable';
    const k = state.cols;
    k.title = (p.get('title') || '').toLowerCase();
    k.director = (p.get('director') || '').toLowerCase();
    const lang = p.get('lang');
    k.languages = lang === null ? new Set([DEFAULT_LANG]) : lang === 'any' ? new Set() : new Set(lang.split('|').filter(Boolean));
    const range = (name) => { const v = p.get(name); if (!v) return [null, null]; const [lo, hi] = v.split('-'); return [lo === '' ? null : +lo, hi === '' || hi == null ? null : +hi]; };
    [k.yearMin, k.yearMax] = range('year'); [k.mcMin, k.mcMax] = range('mc'); [k.rtMin, k.rtMax] = range('rt'); [k.imdbMin, k.imdbMax] = range('imdb');
    const s = p.get('sort');
    state.sort = s && COLS.includes(s.split(':')[0]) && ['asc', 'desc'].includes(s.split(':')[1]) ? { col: s.split(':')[0], dir: s.split(':')[1] } : null;
    const film = p.get('film');
    state.openFilm = film ? +film : null;
  }
  function writeControlsFromState() {
    $('#scope-toggle').textContent = SCOPE_LABELS[state.scope];
    $('#scope-toggle').classList.toggle('active', state.scope !== 'reachable');
    document.querySelectorAll('.chip[data-chip]').forEach((b) => b.classList.toggle('active', state.chips.has(b.dataset.chip)));
    const k = state.cols;
    $('#f-title').value = k.title; $('#f-director').value = k.director;
    document.querySelectorAll('#f-lang-panel input[type=checkbox]:not(#f-lang-any)').forEach((cb) => { cb.checked = k.languages.has(cb.value); });
    const anyBox = $('#f-lang-any');
    if (anyBox) anyBox.checked = k.languages.size === 0;
    if (langPanel.hidden) langInput.value = langLabel();
    const set = (id, v) => { $(id).value = v == null ? '' : v; };
    set('#f-year-min', k.yearMin); set('#f-year-max', k.yearMax); set('#f-mc-min', k.mcMin); set('#f-mc-max', k.mcMax); set('#f-rt-min', k.rtMin); set('#f-rt-max', k.rtMax); set('#f-imdb-min', k.imdbMin); set('#f-imdb-max', k.imdbMax);
    document.querySelectorAll('th.sortable').forEach((th) => {
      if (state.sort && th.dataset.col === state.sort.col) th.dataset.dir = state.sort.dir; else delete th.dataset.dir;
    });
  }

  // ---- controls ----
  $('#chips').addEventListener('click', (e) => {
    const b = e.target.closest('.chip'); if (!b) return;
    if (b.id === 'scope-toggle') state.scope = SCOPES[(SCOPES.indexOf(state.scope) + 1) % SCOPES.length];
    else if (b.id === 'chips-clear') state.chips.clear();
    else if (state.chips.has(b.dataset.chip)) state.chips.delete(b.dataset.chip); else state.chips.add(b.dataset.chip);
    writeControlsFromState(); applyFilters();
  });
  document.querySelectorAll('th.sortable').forEach((th) => th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (!state.sort || state.sort.col !== col) state.sort = { col, dir: 'asc' };
    else if (state.sort.dir === 'asc') state.sort = { col, dir: 'desc' };
    else state.sort = null;
    writeControlsFromState(); applyFilters();
  }));
  const num = (id) => { const v = $(id).value.trim(); return v === '' ? null : Number(v); };
  function readControls() {
    const k = state.cols;
    k.title = $('#f-title').value.trim().toLowerCase();
    k.director = $('#f-director').value.trim().toLowerCase();
    // k.languages is not rebuilt here: the panel's change handler maintains it in selection order.
    if (langPanel.hidden) langInput.value = langLabel();
    k.yearMin = num('#f-year-min'); k.yearMax = num('#f-year-max');
    k.mcMin = num('#f-mc-min'); k.mcMax = num('#f-mc-max');
    k.rtMin = num('#f-rt-min'); k.rtMax = num('#f-rt-max');
    k.imdbMin = num('#f-imdb-min'); k.imdbMax = num('#f-imdb-max');
    applyFilters();
  }
  document.querySelectorAll('thead tr.filters input:not(#f-lang-input), thead tr.filters select').forEach((el) => {
    el.addEventListener('input', readControls);
    el.addEventListener('change', readControls);
  });
  function langLabel() {
    const sel = state.cols.languages;
    return sel.size === 0 ? 'Any' : [...sel].join(', ');
  }
  function populateLanguages() {
    const langs = new Set();
    state.films.forEach((f) => (f.language || '').split(',').map((s) => s.trim()).filter(Boolean).forEach((l) => langs.add(l)));
    langs.delete(DEFAULT_LANG);  // pinned first, ahead of "Any" — it's the default selection
    $('#f-lang-panel').innerHTML = `<label><input type="checkbox" value="${DEFAULT_LANG}"> ${DEFAULT_LANG}</label>`
      + '<label><input type="checkbox" id="f-lang-any"> Any language</label>'
      + [...langs].sort().map((l) => `<label><input type="checkbox" value="${esc(l)}"> ${esc(l)}</label>`).join('');
  }
  const langPanel = $('#f-lang-panel'), langInput = $('#f-lang-input');
  // The language cell is a combobox: the input shows the selection while closed, and turns
  // into a typeahead search over the options while the panel is open.
  function applyLangSearch() {
    const q = langInput.value.trim().toLowerCase();
    langPanel.querySelectorAll('label').forEach((lab) => {
      const isAny = lab.querySelector('input').id === 'f-lang-any';
      lab.hidden = isAny ? q !== '' : !lab.textContent.trim().toLowerCase().includes(q);
    });
  }
  function openLangPanel() {
    if (!langPanel.hidden) return;
    langPanel.hidden = false;
    langInput.value = '';
    applyLangSearch();
  }
  function closeLangPanel() {
    langPanel.hidden = true;
    langInput.value = langLabel();
  }
  langInput.addEventListener('focus', openLangPanel);
  langInput.addEventListener('click', (e) => { e.stopPropagation(); openLangPanel(); });
  langInput.addEventListener('input', applyLangSearch);
  langPanel.addEventListener('click', (e) => e.stopPropagation());
  langPanel.addEventListener('change', (e) => {
    const k = state.cols, anyBox = $('#f-lang-any');
    if (e.target === anyBox) {
      langPanel.querySelectorAll('input[type=checkbox]:not(#f-lang-any)').forEach((cb) => { cb.checked = false; });
      k.languages.clear();
    } else if (e.target.checked) k.languages.add(e.target.value);  // Set keeps selection order for the label
    else k.languages.delete(e.target.value);
    anyBox.checked = k.languages.size === 0;
    applyFilters();
    langInput.value = '';  // search consumed — ready to type the next language
    applyLangSearch();
    langInput.focus();
  });
  document.addEventListener('click', closeLangPanel);

  // ---- toast ----
  let toastTimer;
  function toast(msg) {
    const t = $('#toast'); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 3000);
  }

  // ---- rating entry ----
  function parseScore(text) {
    const s = text.trim();
    if (s === '') return { ok: true, score: null };
    if (!/^\d{1,2}$/.test(s)) return { ok: false };
    const n = Number(s);
    return n >= 0 && n <= 10 ? { ok: true, score: n } : { ok: false };
  }
  function updateFilmLocal(updated) {
    const i = state.films.findIndex((f) => f.id === updated.id);
    if (i >= 0) state.films[i] = updated;
    renderCounts(); applyFilters();
    document.querySelectorAll(`input.rating[data-id="${updated.id}"]`).forEach((el) => { el.value = updated.my_rating ?? ''; });
  }
  async function commitRating(input) {
    if (input.dataset.busy) return;
    const id = +input.dataset.id;
    const film = state.films.find((f) => f.id === id);
    const current = film && film.my_rating != null ? String(film.my_rating) : '';
    const parsed = parseScore(input.value);
    if (!parsed.ok) {
      input.classList.add('invalid'); input.value = current;
      setTimeout(() => input.classList.remove('invalid'), 800);
      return;
    }
    if (input.value.trim() === current) return;
    input.dataset.busy = '1';
    try {
      const r = await fetch(`/api/films/${id}/rating`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ score: parsed.score }) });
      if (!r.ok) throw new Error((await r.json()).error || r.statusText);
      updateFilmLocal(await r.json());
    } catch (err) {
      input.value = current; toast(`Could not save rating: ${err.message}`);
    } finally {
      delete input.dataset.busy;
    }
  }
  document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.matches('input.rating')) e.target.blur(); });
  document.addEventListener('focusout', (e) => { if (e.target.matches('input.rating')) commitRating(e.target); });

  // ---- drawer ----
  const drawer = $('#drawer'), backdrop = $('#drawer-backdrop'), body = $('#drawer-body');
  const VERDICTS = ['fine', 'omdb-wrong', 'tmdb-wrong', 'film-wrong', 'twin'];
  function renderAudit(d) {
    if (!d.audit && !d.verdict) return '';
    const reasons = d.audit ? d.audit.reasons.map((r) => `<li data-code="${esc(r.code)}"><b>${esc(r.code)}</b> — ${esc(r.detail)}</li>`).join('') : '';
    const verdict = d.verdict ? `${esc(d.verdict.verdict)} (${esc(d.verdict.marked_on)})${d.verdict.note ? ' — ' + esc(d.verdict.note) : ''}` : '';
    const buttons = VERDICTS.map((v) => `<button class="verdict-btn" data-id="${d.id}" data-verdict="${v}">${v}</button>`).join('');
    return `<div class="audit-block" data-id="${d.id}">
      <h3>Audit${d.audit ? ` · score ${d.audit.score}` : ''}</h3>
      <ul class="audit-reasons">${reasons}</ul>
      <div class="audit-verdict">${verdict}</div>
      <input class="verdict-note" placeholder="note (optional)">
      <div class="verdict-buttons">${buttons}</div>
    </div>`;
  }
  function detailHtml(d) {
    const p = d.payload || {};
    const poster = p.Poster && p.Poster !== 'N/A' ? `<img class="poster" src="${esc(p.Poster)}" alt="">` : '';
    const fields = [['Genre', p.Genre], ['Runtime', p.Runtime], ['Rated', p.Rated], ['Country', p.Country], ['Language', d.language], ['Awards', p.Awards], ['Cast', p.Actors], ['Writer', p.Writer]]
      .filter(([, v]) => v && v !== 'N/A').map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join('');
    const sources = (p.Ratings || []).map((r) => `<li>${esc(r.Source)}: ${esc(r.Value)}</li>`).join('');
    const svc = d.services || [];
    // Services arrive already ranked (subscribed, quality, Apple TV app, name — see
    // domain/watch.py). A film can carry dozens of them, so show the best few and put the
    // rest behind a native <details> disclosure: no filtering, because a service you rate
    // badly is still the answer when it is the only place a film exists.
    const collapse = (names) => names.length <= TOP_SERVICES ? names.join(', ')
      : `${names.slice(0, TOP_SERVICES).join(', ')} <details class="svc-more"><summary>⋯ ${names.length - TOP_SERVICES} more</summary><span class="svc-rest">, ${names.slice(TOP_SERVICES).join(', ')}</span></details>`;
    const streaming = collapse(svc.filter((s) => s.kind !== 'store')
      .map((s) => s.subscribed ? esc(s.name) : `${esc(s.name)} (not subscribed)`));
    const buyable = collapse(svc.filter((s) => s.kind === 'store').map((s) => esc(s.name)));
    const newOn = (d.new_on || []).map((t) => `${esc(t.name)} since ${esc(t.appeared_on)}`).join(', ');
    const lists = (d.lists || []).map((l) => {
      const label = l.published ? `${esc(l.curator || l.name)} ${esc(l.published)}` : esc(l.curator || l.name);
      // rank_label is the cell AS PRINTED, so a tie arrives as "=54"; the drawer shows the
      // number alone (#54) — whether the placing was tied is not what this line is for.
      const rank = String(l.rank_label ?? l.rank).replace(/^=/, '');
      return l.ordered ? `${label} #${esc(rank)}` : label;
    }).join(', ');
    const bestLine = d.best_source
      ? `<p class="meta best-source">Best source: <b>${esc(d.best_source.name)}</b>${d.best_source.subscribed ? '' : ' (not subscribed)'}</p>`
      : '';
    return `<h2>${esc(d.title)} <button class="watch-toggle" data-id="${d.id}" title="Toggle watchlist" aria-label="Toggle watchlist">${d.watchlisted ? '★' : '☆'}</button><button class="revisit-toggle" data-id="${d.id}" title="Toggle needs-revisit" aria-label="Toggle needs-revisit">${d.needs_revisit ? '⚑' : '⚐'}</button></h2>
      ${d.needs_revisit ? `<input class="revisit-note" data-id="${d.id}" placeholder="what looks wrong?" value="${esc(d.revisit_note || '')}">` : ''}
      ${renderAudit(d)}
      <div class="meta">${fmt(d.year)} · ${esc(d.director) || '—'}${d.departed ? ' · <b>Gone from Criterion</b>' : ''}</div>
      ${p.Plot && p.Plot !== 'N/A' ? `<p>${poster}${esc(p.Plot)}</p>` : poster}
      <dl>${fields}</dl>
      ${sources ? `<ul class="sources">${sources}</ul>` : d.pending ? '<p class="meta">OMDb lookup pending.</p>' : d.found === false ? '<p class="meta">No OMDb match.</p>' : ''}
      <p>${d.url ? `<a class="criterion" href="${esc(d.url)}" target="_blank" rel="noopener">Open on Criterion ↗</a>` : ''}
        ${d.metacritic_url ? ` <a class="criterion" href="${esc(d.metacritic_url)}" target="_blank" rel="noopener">Open on Metacritic ↗</a>` : ''}
        ${d.owned ? ` <a class="criterion owned-link" href="https://tv.apple.com/search?term=${encodeURIComponent(d.title)}" target="_blank" rel="noopener">Owned on Apple TV ↗</a>` : ''}
        ${buyable ? ` <a class="criterion cheapcharts-link" href="https://www.cheapcharts.com/us/search;q=${encodeURIComponent(d.title)};t=all" target="_blank" rel="noopener">Find on CheapCharts ↗</a>` : ''}
        &nbsp; My rating: <input class="rating" maxlength="2" data-id="${d.id}" value="${d.my_rating ?? ''}" aria-label="My rating"></p>
      ${newOn ? `<p class="meta new-on">New on: ${newOn}</p>` : ''}
      ${bestLine}
      ${streaming ? `<p class="meta">Also streaming on: ${streaming}</p>` : ''}
      ${buyable ? `<p class="meta">Buy on: ${buyable}</p>` : ''}
      ${lists ? `<p class="meta">On lists: ${lists}</p>` : ''}
      <details><summary>Raw OMDb payload</summary><pre class="raw">${esc(d.payload ? JSON.stringify(d.payload, null, 2) : 'null')}</pre></details>
      ${d.leaving_date ? `<p class="meta leaving"><b>Leaving ${esc(d.leaving_date)}</b></p>` : ''}`;
  }
  let drawerSeq = 0;
  let drawerOpenPushed = false; // true once the currently-open drawer got its own pushState entry
  function hideDrawer() {
    drawer.hidden = true; backdrop.hidden = true; body.innerHTML = '';
    state.openFilm = null;
  }
  async function openDrawer(id, push = true) {
    const seq = ++drawerSeq;
    const r = await fetch(`/api/films/${id}`);
    if (seq !== drawerSeq) return; // a newer open (or a close) superseded this one
    if (!r.ok) { toast('Film not found'); return; }
    const d = await r.json();
    if (seq !== drawerSeq) return;
    body.innerHTML = detailHtml(d);
    drawer.hidden = false; backdrop.hidden = false;
    state.openFilm = id;
    if (push) { syncUrl(true); drawerOpenPushed = true; } else { drawerOpenPushed = false; }
  }
  // fromPopstate=true: the URL already changed (browser back/forward already happened) — just
  // reflect it in the DOM, never touch history again (that's what caused the re-push bug).
  // fromPopstate=false (user closed it directly): if the open pushed its own history entry, walk
  // it back with history.back() so the entry is consumed instead of piling up a duplicate one;
  // popstate then finishes the close via the fromPopstate=true branch above.
  function closeDrawer(fromPopstate = false) {
    if (fromPopstate) {
      drawerSeq++;
      hideDrawer();
      drawerOpenPushed = false;
      return;
    }
    if (drawer.hidden) return; // nothing open — don't navigate back for no reason
    drawerSeq++; // supersede any in-flight open so it can't reopen after this close
    if (drawerOpenPushed) {
      drawerOpenPushed = false;
      history.back();
    } else {
      hideDrawer();
      syncUrl(true);
    }
  }
  tbody.addEventListener('click', (e) => {
    if (e.target.closest('a, input')) return;
    const tr = e.target.closest('tr[data-id]'); if (tr) openDrawer(+tr.dataset.id);
  });
  $('#drawer-close').addEventListener('click', () => closeDrawer());
  backdrop.addEventListener('click', () => closeDrawer());
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.watch-toggle'); if (!b) return;
    const r = await fetch(`/api/films/${b.dataset.id}/watchlist`, { method: 'POST' });
    if (!r.ok) { toast('Could not update watchlist'); return; }
    const { watchlisted } = await r.json();
    b.textContent = watchlisted ? '★' : '☆';
    const film = state.films.find((f) => f.id === +b.dataset.id);
    if (film) { film.watchlisted = watchlisted; applyFilters(); }
  });
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.revisit-toggle'); if (!b) return;
    const id = Number(b.dataset.id);
    const r = await fetch(`/api/films/${id}/revisit`, { method: 'POST' });
    if (!r.ok) { toast('Could not update revisit flag'); return; }
    const { needs_revisit } = await r.json();
    b.textContent = needs_revisit ? '⚑' : '⚐';
    const film = state.films.find((f) => f.id === id);
    if (film) { film.needs_revisit = needs_revisit; if (!needs_revisit) film.revisit_note = null; applyFilters(); }
    // Patch the drawer DOM in place — reopening (openDrawer) would clear drawerOpenPushed
    // and desync closeDrawer()'s history-back bookkeeping (see the fromPopstate comment above).
    let note = body.querySelector('.revisit-note');
    if (needs_revisit && !note) {
      note = document.createElement('input');
      note.className = 'revisit-note';
      note.dataset.id = String(id);
      note.placeholder = 'what looks wrong?';
      note.value = (film && film.revisit_note) || '';
      b.closest('h2').insertAdjacentElement('afterend', note);
    } else if (!needs_revisit && note) {
      note.remove();
    }
  });
  async function commitRevisitNote(input) {
    if (input.dataset.busy) return;
    const id = Number(input.dataset.id);
    const film = state.films.find((f) => f.id === id);
    const current = (film && film.revisit_note) || '';
    if (input.value === current) return;
    input.dataset.busy = '1';
    try {
      const r = await fetch(`/api/films/${id}/revisit`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note: input.value }) });
      if (!r.ok) throw new Error((await r.json()).error || r.statusText);
      if (film) film.revisit_note = input.value;
    } catch (err) {
      input.value = current; toast(`Could not save note: ${err.message}`);
    } finally {
      delete input.dataset.busy;
    }
  }
  document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.matches('input.revisit-note')) e.target.blur(); });
  document.addEventListener('focusout', (e) => { if (e.target.matches('input.revisit-note')) commitRevisitNote(e.target); });
  document.addEventListener('click', async (e) => {
    const b = e.target.closest('.verdict-btn'); if (!b) return;
    const id = Number(b.dataset.id);
    const block = b.closest('.audit-block');
    const note = block.querySelector('.verdict-note').value.trim();
    const r = await fetch(`/api/films/${id}/verdict`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ verdict: b.dataset.verdict, note: note || null }) });
    if (!r.ok) { toast('Could not record verdict'); return; }
    const res = await r.json();
    const film = state.films.find((f) => f.id === id);
    if (film) { film.verdict = { verdict: res.verdict, reasons: res.reasons, note: res.note, marked_on: res.marked_on }; film.audit = res.audit; applyFilters(); }
    block.querySelector('.audit-verdict').textContent = `${res.verdict} (${res.marked_on})${res.note ? ' — ' + res.note : ''}`;
    if (!res.audit) block.querySelector('.audit-reasons').innerHTML = '';
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!langPanel.hidden) { closeLangPanel(); return; }
    closeDrawer();
  });
  window.addEventListener('popstate', () => {
    readUrl(); writeControlsFromState(); applyFilters();
    if (state.openFilm != null) openDrawer(state.openFilm, false); else closeDrawer(true);
  });

  window.MB = { state, applyFilters, render: renderRows, renderCounts, rowHtml, onBoot: () => { if (state.openFilm != null) openDrawer(state.openFilm, false); } };

  // ---- boot ----
  async function boot() {
    const [cfg, films] = await Promise.all([fetch('/api/config').then((r) => r.json()), fetch('/api/films').then((r) => r.json())]);
    state.cfg = cfg; state.films = films;
    populateLanguages();
    readUrl();
    writeControlsFromState();
    renderCounts();
    applyFilters();
    if (window.MB.onBoot) window.MB.onBoot();
  }
  boot().catch((e) => toast(`Failed to load: ${e.message}`));
})();
