(() => {
  'use strict';
  const ROW_H = 36, OVERSCAN = 10;
  const TOP_SERVICES = 3;  // drawer: services shown before the ⋯ more disclosure
  const APPLE_STORE = 'Apple TV Store (iTunes)';  // the registry's one store, named for a film holding a store id but no TMDB store listing
  const TOP_CAST = 6;      // drawer: cast names shown inline before the ⋯ more disclosure (drawer spec D2)
  const COLS = ['title', 'year', 'director', 'language', 'metacritic', 'rt', 'imdb', 'my_rating'];
  const DEFAULT_LANG = 'English';
  const state = {
    films: [], cfg: null, chips: new Set(),
    q: '', search: null,   // power search: state.search is null or {ids: Set, rank: Map|null}
    list: null, listCatalog: [],   // list picker: filter to one curated list and order by its rank
    cols: { title: '', director: '', languages: new Set(), yearMin: null, yearMax: null, mcMin: null, mcMax: null, rtMin: null, rtMax: null, imdbMin: null, imdbMax: null },
    sort: null,            // {col, dir} or null = default
    filtered: [], openFilm: null,
    mark: null,            // find-my-row: the last film opened — a bookmark in memory, never in the URL
  };
  const $ = (s) => document.querySelector(s);
  const tbody = $('#films tbody'), wrap = $('#table-wrap'), thead = $('#films thead');

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
  // The selected list's printed rank for one film, or null when the list is UNORDERED — an
  // unordered list's `rank` is a line position, not a placing, so sorting on it would invent
  // a ranking the source never made. Null falls through to the default hierarchy.
  const listRank = (f) => {
    const e = (f.lists || []).find((l) => l.slug === state.list);
    return e && e.ordered ? printedRank(e) : null;
  };
  // reachable = somewhere to watch it today: a current Criterion listing, ANY current listing on
  // a streaming service (subscribed or not) or the Apple store, the film is owned (it IS
  // watchable, and ownership on Apple is proof of a store presence TMDB's US data missed), or it
  // holds an iTunes id (a CheapCharts product page exists only for a title Apple sells — TMDB's
  // feed lags new digital releases). Rated and watchlisted do not count. Mirrors
  // domain/filters.py::reachable; the header count and the chip share it.
  const reachable = (f) => (f.criterion && !f.departed) || (f.services || []).length > 0 || f.owned || !!f.cheapcharts_url;
  // Mirrors domain/filters.py::_PREDICATES — keep the two in lockstep. Keys are what `chips=`
  // encodes in the URL; a cycle chip's keys are mutually exclusive in the UI only.
  const CHIP_PREDICATES = {
    reachable,
    unreachable: (f) => !reachable(f),
    unrated: (f) => f.my_rating == null,
    mine: (f) => f.my_rating != null && f.my_rating >= 1,
    criterion: (f) => f.criterion && !f.departed,
    leaving: (f) => f.leaving_date != null,
    criterion_new: (f) => (f.new_on || []).some((t) => t.source === 'criterion'
      && daysBetween(t.appeared_on, state.cfg.today) <= state.cfg.canned_thresholds.new_arrival_days),
    not_criterion: (f) => !(f.criterion && !f.departed),
    watchlist: (f) => f.watchlisted,
    owned: (f) => f.owned,
    not_owned: (f) => !f.owned,
    multi_list: (f) => (f.lists || []).length >= state.cfg.canned_thresholds.multi_list,
    // Loved then, not judged since (old-ratings spec O7): a pending request a rating today serves.
    rewatch: (f) => f.old_rating != null && f.old_rating.stars === 5 && f.my_rating == null,
    // A film worth buying (mirrors domain/filters.py::shop): not owned, not rated, on no streaming
    // service I have, holding a store id — and not yet wishlisted, so a film leaves the list the
    // moment it is wishlisted. Raw fields only: the Apple store row is itself `subscribed`, so the
    // svod check is load-bearing.
    shop: (f) => !f.owned && f.my_rating == null && f.cheapcharts_url != null && !f.wishlisted
      && !((f.criterion && !f.departed) || (f.services || []).some((s) => s.kind === 'svod' && s.subscribed)),
  };

  // ---- filtering / sorting ----
  const inRange = (v, lo, hi) => v != null && (lo == null || v >= lo) && (hi == null || v <= hi);
  function rowMatches(f) {
    if (state.search && !state.search.ids.has(f.id)) return false;
    if (state.list && !(f.lists || []).some((l) => l.slug === state.list)) return false;
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
      if (state.search && state.search.rank) {  // freeform text ranks; a column sort still overrides
        const ra = state.search.rank.get(a.id), rb = state.search.rank.get(b.id);
        if (ra !== rb) return ra - rb;
      }
      if (state.list) {  // a picked list is reproduced in ITS order, ahead of every other rule
        const ra = listRank(a), rb = listRank(b);
        if (ra != null && rb != null && ra !== rb) return ra - rb;
      }
      if (state.chips.has('multi_list')) {  // "On a list" active: canon score desc leads, so Citizen Kane outranks a one-list entry
        const c = canonScore(b) - canonScore(a);
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
  // Where the open film sits in the shown list — re-found BY ID on every filter pass (a film's
  // object is replaced when it is patched) and KEPT when the film drops out, so ↑ ↓ can carry on
  // from the gap it left: wishlist a film under Shop, or rate one under Unrated, and the next ↓
  // opens the film that took its place. null = the open film was never in the list.
  let openIndex = null;
  function trackOpenIndex() {
    const i = state.openFilm == null ? -1 : state.filtered.findIndex((f) => f.id === state.openFilm);
    if (i >= 0) openIndex = i;
    else if (openIndex != null) openIndex = Math.min(openIndex, state.filtered.length);
  }
  function applyFilters() {
    state.filtered = state.films.filter(rowMatches).sort(compare);
    trackOpenIndex();
    tbody.dataset.count = state.filtered.length;
    $('#count-showing').textContent = `Showing ${state.filtered.length} of ${state.films.length}`;
    renderRows();
    syncUrl();
  }

  // ---- header counts ----
  // Four catalogue-wide numbers the owner acts on: the whole catalogue, what is reachable today
  // (the same predicate the Reachable chip uses, so the number and the chip can never disagree), what
  // is owned, and what is rated. The old nine were Criterion-scoped and mostly OMDb plumbing
  // (found / pending / unmatched); that maintenance view lives in `movie-brain status` now.
  function renderCounts() {
    const n = (p) => state.films.filter(p).length;
    $('#count-films').textContent = state.films.length;
    $('#count-reachable').textContent = n(reachable);
    $('#count-owned').textContent = n((x) => x.owned);
    $('#count-mine').textContent = n((x) => x.my_rating != null);
  }

  // ---- virtual-scrolled rows ----
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const escapeRegExp = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const fmt = (v, suffix = '') => (v == null ? '—' : `${v}${suffix}`);
  // My 2004-08 rating as a watching signal (old-ratings spec §4.4): only the two ends earn a badge —
  // 5★ says rewatch, 1★ says avoid. 2-4★ show in the drawer alone.
  const OLD_SPAN = '2004–08';
  function oldBadge(f) {
    const s = f.old_rating && f.old_rating.stars;
    if (s !== 5 && s !== 1) return '';
    const cls = s === 5 ? 'badge-old-loved' : 'badge-old-avoid';
    return ` <span class="${cls}" title="I rated this ${s}★ in ${OLD_SPAN}">${s}★ then</span>`;
  }
  // Find my row (brief 2026-09-20): the open film's row is lifted above the drawer's dim so it
  // stays white (`lit`, with the dark `edge` bar), and once the drawer closes the last film opened
  // keeps a grey `marked` row. Both are drawn here from state, so the virtual scroll cannot lose
  // them. A row is lifted only while it sits wholly below the sticky header (`i` is its index in
  // state.filtered): lifted any higher it would paint over the header instead of sliding under it.
  function rowClass(f, i) {
    const cls = f.departed ? ['departed'] : [];
    if (drawer.hidden) { if (f.id === state.mark) cls.push('marked'); }
    else if (f.id === state.openFilm && i * ROW_H >= wrap.scrollTop) cls.push('lit', 'edge');
    return cls.length ? ` class="${cls.join(' ')}"` : '';
  }
  function rowHtml(f, i) {
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
      + oldBadge(f) + watchBadge
      // On my CheapCharts wishlist — always the last mark on the row, and never a price.
      + (f.wishlisted ? ' <span class="icon-wish" title="On your CheapCharts wishlist">♥</span>' : '');
    return `<tr data-id="${f.id}"${rowClass(f, i)}>
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
      state.filtered.slice(start, end).map((f, k) => rowHtml(f, start + k)).join('') +
      (bottom ? `<tr class="spacer"><td colspan="9" style="height:${bottom}px"></td></tr>` : '');
  }
  wrap.addEventListener('scroll', () => requestAnimationFrame(renderRows));

  // ---- URL state ----
  function syncUrl(push = false) {
    const p = new URLSearchParams();
    if (state.chips.size) p.set('chips', [...state.chips].join(','));
    const k = state.cols;
    if (k.title) p.set('title', k.title);
    if (k.director) p.set('director', k.director);
    if (k.languages.size) p.set('lang', [...k.languages].join('|'));  // the default (any language) is implicit
    for (const [name, lo, hi] of [['year', k.yearMin, k.yearMax], ['mc', k.mcMin, k.mcMax], ['rt', k.rtMin, k.rtMax], ['imdb', k.imdbMin, k.imdbMax]]) {
      if (lo != null || hi != null) p.set(name, `${lo ?? ''}-${hi ?? ''}`);
    }
    if (state.list) p.set('list', state.list);
    if (state.q) p.set('q', state.q);
    if (state.sort) p.set('sort', `${state.sort.col}:${state.sort.dir}`);
    if (state.openFilm != null) p.set('film', state.openFilm);
    const qs = p.toString();
    history[push ? 'pushState' : 'replaceState'](null, '', qs ? `?${qs}` : location.pathname);
  }
  function readUrl() {
    const p = new URLSearchParams(location.search);
    state.chips = new Set((p.get('chips') || '').split(',').filter((c) => c in CHIP_PREDICATES));
    // Saved links from before the scope toggle was folded into the chips: `scope=criterion`
    // becomes the Criterion chip; `scope=all` and the old default are simply the new default.
    if (p.get('scope') === 'criterion') state.chips.add('criterion');
    const slug = p.get('list');
    state.list = state.listCatalog.some((l) => l.slug === slug) ? slug : null;
    const k = state.cols;
    k.title = (p.get('title') || '').toLowerCase();
    k.director = (p.get('director') || '').toLowerCase();
    const lang = p.get('lang');
    // Any language is the default (2026-09-07); `lang=any` is the pre-default spelling old links carry.
    k.languages = lang === null || lang === 'any' ? new Set() : new Set(lang.split('|').filter(Boolean));
    const range = (name) => { const v = p.get(name); if (!v) return [null, null]; const [lo, hi] = v.split('-'); return [lo === '' ? null : +lo, hi === '' || hi == null ? null : +hi]; };
    [k.yearMin, k.yearMax] = range('year'); [k.mcMin, k.mcMax] = range('mc'); [k.rtMin, k.rtMax] = range('rt'); [k.imdbMin, k.imdbMax] = range('imdb');
    const s = p.get('sort');
    state.sort = s && COLS.includes(s.split(':')[0]) && ['asc', 'desc'].includes(s.split(':')[1]) ? { col: s.split(':')[0], dir: s.split(':')[1] } : null;
    const film = p.get('film');
    state.openFilm = film ? +film : null;
    state.q = p.get('q') || '';
  }
  function writeControlsFromState() {
    $('#search').value = state.q;
    $('#list-picker').value = state.list || '';
    document.querySelectorAll('.chip[data-chip]').forEach((b) => b.classList.toggle('active', state.chips.has(b.dataset.chip)));
    document.querySelectorAll('.chip[data-cycle]').forEach((b) => {
      const keys = b.dataset.cycle.split(','), labels = b.dataset.labels.split('|');
      const i = keys.findIndex((k) => state.chips.has(k));  // -1 = off; labels[0] is the off label
      b.textContent = labels[i + 1];
      b.classList.toggle('active', i >= 0);
    });
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
    if (b.id === 'chips-clear') {  // Clear means EVERYTHING: chips, list, search, column filters, sort
      state.chips.clear(); state.list = null; state.sort = null;
      state.q = ''; state.search = null; noteEl.hidden = true; noteEl.innerHTML = ''; searchEl.dataset.settled = '';
      Object.assign(state.cols, { title: '', director: '', languages: new Set(), yearMin: null, yearMax: null,
        mcMin: null, mcMax: null, rtMin: null, rtMax: null, imdbMin: null, imdbMax: null });
    }
    else if (b.dataset.cycle) {  // off → first key → … → last key → off; the keys are mutually exclusive
      const keys = b.dataset.cycle.split(',');
      const i = keys.findIndex((k) => state.chips.has(k));
      keys.forEach((k) => state.chips.delete(k));
      if (i + 1 < keys.length) state.chips.add(keys[i + 1]);
    }
    else if (!b.dataset.chip) return;  // a .chip with no data-chip would add `undefined` to the set
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
    langs.delete(DEFAULT_LANG);  // "Any" (the default) first, then the owner's own language pinned, then the rest A–Z
    $('#f-lang-panel').innerHTML = '<label><input type="checkbox" id="f-lang-any"> Any language</label>'
      + `<label><input type="checkbox" value="${DEFAULT_LANG}"> ${DEFAULT_LANG}</label>`
      + [...langs].sort().map((l) => `<label><input type="checkbox" value="${esc(l)}"> ${esc(l)}</label>`).join('');
  }
  // The picker's options come from the films payload — every film carries its list entries with
  // slug/name/curator/published/ordered/trust/size — so no endpoint is needed. A list with no
  // linked film is absent, which is right: there would be nothing to filter to.
  function populateLists() {
    const by = new Map();
    state.films.forEach((f) => (f.lists || []).forEach((l) => { if (!by.has(l.slug)) by.set(l.slug, l); }));
    // The owner's own lists first (the ranker saves with curator "me"; 2026-09-14 ruling — "My
    // Ranked" is the list opened most and trust is a canon weight, not a shelf position), then
    // trust desc then name — the order `movie-brain lists trust` prints and the drawer uses.
    const mine = (l) => (l.curator === 'me' ? 1 : 0);
    state.listCatalog = [...by.values()].sort((a, b) => mine(b) - mine(a) || b.trust - a.trust || a.name.localeCompare(b.name));
    // The label is the list's NAME, which the owner writes in the file header to read well here
    // ("BFI: 100 Film Noir") and which is unique by construction — the earlier "curator published"
    // form ("Cahiers du Cinéma 2008") collided on the two 1992 Sight & Sound polls and had to
    // fall back to the name anyway.
    const label = (l) => `${l.name} (${l.size})`;
    $('#list-picker').innerHTML = '<option value="">— all films —</option>'
      + state.listCatalog.map((l) => `<option value="${esc(l.slug)}">${esc(label(l))}</option>`).join('');
  }
  $('#list-picker').addEventListener('change', (e) => {
    state.list = e.target.value || null;
    // Picking a list touches no other control (2026-09-07): the old picker forced the scope to
    // "all" so a list came out whole, but now every filter is off by default, and a Reachable
    // chip the owner set on purpose must stay set — "which of the Cahiers 100 can I watch" is a
    // question, not an accident.
    writeControlsFromState(); applyFilters();
  });

  // ---- power search (spec §9) ----
  // The server resolves the query to an id set; this pipeline only intersects with it, so chips,
  // scope, list picker and column filters all keep working mid-search. `dataset.settled` on the
  // input records the last query whose response has been applied — tests wait on it.
  const searchEl = $('#search'), noteEl = $('#search-note');
  let searchTimer = null, searchSeq = 0;
  function applySearchResponse(body) {
    state.search = { ids: new Set(body.ids), rank: body.ranked ? new Map(body.ids.map((id, i) => [id, i])) : null };
    const parts = [];
    for (const c of body.corrections) parts.push(`Showing results for <b>${esc(c.used)}</b> (you typed “${esc(c.typed)}”) <button class="undo" data-typed="${esc(c.typed)}" data-field="${esc(c.field)}">undo</button>`);
    for (const s of body.suggestions) parts.push(`No ${esc(s.field)} “${esc(s.typed)}” — did you mean ${s.options.map((o) => `<button class="suggest" data-typed="${esc(s.typed)}" data-use="${esc(o)}" data-field="${esc(s.field)}">${esc(o)}</button>`).join('')}?`);
    for (const h of body.hints) parts.push(esc(h));
    noteEl.innerHTML = parts.join('<br>');
    noteEl.hidden = parts.length === 0;
  }
  async function runSearch() {
    const value = searchEl.value;
    const q = state.q.trim();
    const seq = ++searchSeq;
    if (!q) {
      state.search = null; noteEl.hidden = true; noteEl.innerHTML = '';
      searchEl.dataset.settled = value;
      applyFilters();
      return;
    }
    try {
      const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      if (seq !== searchSeq) return;  // a newer query is in flight
      applySearchResponse(body);
    } catch (e) {
      if (seq !== searchSeq) return;
      state.search = null; noteEl.hidden = false; noteEl.textContent = `Search failed: ${e.message}`;
    }
    searchEl.dataset.settled = value;
    applyFilters();
  }
  searchEl.addEventListener('input', () => {
    state.q = searchEl.value;
    delete searchEl.dataset.settled;
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(runSearch, 300);
  });
  // Quoting a value makes it exact (spec §7.3): undo re-runs with the typed text quoted, and a
  // suggestion replaces the typed text with the chosen name, quoted.
  noteEl.addEventListener('click', (e) => {
    if (searchTimer) clearTimeout(searchTimer);   // a click within 300ms of typing must not also fire the debounced fetch
    const b = e.target.closest('button'); if (!b) return;
    const typed = b.dataset.typed, use = b.classList.contains('undo') ? typed : b.dataset.use, field = b.dataset.field;
    // Anchor on the field the server reported: a bare `.replace(typed, …)` would quote the
    // FIRST textual occurrence of `typed` in the query, which is wrong when the same text
    // appears earlier under a different field (e.g. `title: bogrt actor: bogrt`).
    const anchored = new RegExp(`(${field}\\s*:\\s*)${escapeRegExp(typed)}`, 'i');
    // A replacer FUNCTION, not a template string: a string replacement treats `$1`, `$&`, etc.
    // inside it as backreferences, so a corrected name containing e.g. "$1" would corrupt itself
    // (I3) — a function's return value is inserted verbatim, no re-interpretation.
    state.q = anchored.test(state.q)
      ? state.q.replace(anchored, (_m, p1) => `${p1}"${use}"`)
      : state.q.replace(typed, () => `"${use}"`);   // the user typed an alias (cast:, role:, dp:…); fall back to the first occurrence
    searchEl.value = state.q;
    delete searchEl.dataset.settled;
    runSearch();
  });

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
  // "Rank this" is the drawer's one signal that the ranker still owes the film a pass (move-tier
  // spec M4): lit for a pool mark OR while an ordered tier has yet to insert a moved film, and
  // disabled in the second case so a click cannot un-press what should stay lit.
  // Four states, one button (M12, owner ruling 2026-09-14: the mark means "this ranking is
  // wrong, ask me again", and it comes off once served): unplaced + unmarked = pool ticket;
  // unplaced + marked = lit, click un-marks; placed + awaiting order = lit + disabled; placed +
  // ordered = unlit, click RE-RANKS (the Tiers tab asks it again from scratch).
  function rankToggleState(marked, awaiting, tier) {
    const placed = tier != null;
    const pressed = (marked && !placed) || awaiting;
    const title = awaiting ? `Waiting for Order tier ${tier}` : placed ? 'Re-rank this film (the ranker asks you again)' : "Rank this film (puts it in the ranker's pool)";
    return { pressed, disabled: !!awaiting, placed, title };
  }
  function rankToggleAttrs(marked, awaiting, tier) {
    const st = rankToggleState(marked, awaiting, tier);
    return ` aria-pressed="${st.pressed ? 'true' : 'false'}" data-placed="${st.placed ? '1' : ''}"${st.disabled ? ' disabled' : ''} title="${st.title}"`;
  }
  function paintRankToggle(btn, marked, awaiting, tier) {
    const st = rankToggleState(marked, awaiting, tier);
    btn.setAttribute('aria-pressed', st.pressed ? 'true' : 'false');
    btn.dataset.placed = st.placed ? '1' : '';
    btn.disabled = st.disabled;
    btn.title = st.title;
  }
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
    const prev = film && film.my_rating != null ? film.my_rating : null;
    const current = prev != null ? String(prev) : '';
    const parsed = parseScore(input.value);
    if (!parsed.ok) {
      input.classList.add('invalid'); input.value = current;
      setTimeout(() => input.classList.remove('invalid'), 800);
      return;
    }
    if (input.value.trim() === current) return;
    input.dataset.busy = '1';
    let saved = null;
    try {
      const r = await fetch(`/api/films/${id}/rating`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ score: parsed.score }) });
      if (!r.ok) throw new Error((await r.json()).error || r.statusText);
      saved = await r.json();
      updateFilmLocal(saved);
    } catch (err) {
      input.value = current; toast(`Could not save rating: ${err.message}`);
    } finally {
      delete input.dataset.busy;
    }
    // Outside the try/catch/finally: a throw from the move path must never run the catch above
    // (which would toast a failed save) after the save itself already succeeded.
    if (saved && film) moveOnIfLeft({ film: id, slow: false,
      label: parsed.score == null ? `Cleared ${film.title}'s rating` : `Rated ${film.title} ${parsed.score}`,
      undo: async () => {
        const r2 = await fetch(`/api/films/${id}/rating`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ score: prev }) }).catch(() => null);
        if (!r2 || !r2.ok) { toast('Could not save rating'); return false; }
        updateFilmLocal(await r2.json()); return true;
      } });
  }
  document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.matches('input.rating')) e.target.blur(); });
  document.addEventListener('focusout', (e) => { if (e.target.matches('input.rating')) commitRating(e.target); });

  // ---- drawer ----
  const drawer = $('#drawer'), backdrop = $('#drawer-backdrop'), body = $('#drawer-body');
  const VERDICTS = ['fine', 'omdb-wrong', 'tmdb-wrong', 'film-wrong', 'twin'];
  // Maintenance detail: rendered at the bottom of the drawer, directly above the raw payload
  // (owner ruling 2026-09-07) — never above the summary the drawer exists to show.
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
  // A person link (drawer spec D4): the click handler below reads data-query and searches it,
  // closing the drawer. `exact` names come from TMDB credits and are quoted — exact, never
  // corrected — because they come from the same person table the search resolves against;
  // OMDb-fallback names are bare so the fuzzy stage can bridge a spelling drift. `shown` is the
  // link text, `queried` the name in the query (they differ for the director: the table's
  // Criterion string is shown, the TMDB Director credit is searched).
  const personLink = (field, shown, exact, queried = shown) => {
    const query = exact ? `${field}: "${queried.replace(/"/g, '')}"` : `${field}: ${queried}`;
    return `<a class="person" href="#" data-query="${esc(query)}">${esc(shown)}</a>`;
  };
  function castHtml(d, p) {
    const cast = (d.credits && d.credits.cast) || [];
    if (cast.length) {
      const inline = cast.slice(0, TOP_CAST).map((c) => personLink('actor', c.name, true)).join(', ');
      if (cast.length <= TOP_CAST) return inline;
      // Six bare names inline; the disclosure lists EVERYONE with their role, one per line, and
      // CSS hides the inline six while it is open (spec §3 "Cast row").
      const full = cast.map((c) => `<li>${personLink('actor', c.name, true)}${c.character ? ` as ${esc(c.character)}` : ''}</li>`).join('');
      return `<div class="cast"><span class="cast-inline">${inline}</span> <details class="svc-more cast-more"><summary><span class="when-closed">⋯ ${cast.length - TOP_CAST} more</span><span class="when-open">⋯ fewer</span></summary><ul class="cast-full">${full}</ul></details></div>`;
    }
    if (p.Actors && p.Actors !== 'N/A') return p.Actors.split(', ').map((n) => personLink('actor', n, false)).join(', ');
    return '';
  }
  function writerHtml(d, p) {
    const writers = (d.credits && d.credits.writers) || [];
    // label is "Name" or "Name (novel)" (domain/credits.py::writer_label): link the name, keep the tag as text.
    if (writers.length) return writers.map((w) => personLink('writer', w.name, true) + esc(w.label.slice(w.name.length))).join(', ');
    if (p.Writer && p.Writer !== 'N/A') {
      return p.Writer.split(', ').map((part) => {
        const name = part.replace(/\s*\(.*\)\s*$/, '');   // OMDb's "(screenplay)" / "(novel)" suffixes stay as text
        return personLink('writer', name, false) + esc(part.slice(name.length));
      }).join(', ');
    }
    return '';
  }
  // "Wishlist it" (brief 2026-09-19-price-watch). One slot in the links row, after the CheapCharts
  // link: the done mark, or the button — shown only for a film the Apple store sells (it holds a
  // store id, hence a direct CheapCharts page) that I do not own. Anything else: nothing, no message.
  // The click is reversible (brief 1.2, the owner's ruling at delivery): the "♥ Wishlisted" mark
  // IS the button, one click taking the film back off again.
  const WISH_BUTTON = '♡ Wishlist it';
  const WISH_DONE = '<button class="wish-button wish-done" title="Remove from your CheapCharts wishlist">♥ Wishlisted</button>';
  function wishSlotHtml(d) {  // the slot's resting content for this film's state
    if (d.wishlisted) return WISH_DONE;
    if (!d.cheapcharts_url || d.owned) return '';
    return `<button class="wish-button">${WISH_BUTTON}</button>`;
  }
  function wishHtml(d) {
    const inner = wishSlotHtml(d);
    return inner ? ` <span class="wish" data-id="${d.id}">${inner}</span>` : '';
  }
  // The trailer link (brief 2026-09-20-trailer-link): FIRST in the links row, so it sits in the same
  // spot on every film whatever other links the film has. No ↗ — it does not leave the page (and a
  // BUTTON dressed as a link, so there is no href to land in the URL or to ⌘-click into a new tab). A film
  // with no stored trailer gets a grey YouTube SEARCH link in its place, which opens a new tab: a
  // search result is never played inside movie-brain (that is where reviews and reactions come from).
  const trailerSearchUrl = (d) => `https://www.youtube.com/results?search_query=${encodeURIComponent(`${d.title} ${d.year ?? ''} trailer`.replace(/\s+/g, ' '))}`;
  const trailerSearchHtml = (d) => `<a class="criterion trailer-search" href="${esc(trailerSearchUrl(d))}" target="_blank" rel="noopener">Find a trailer on YouTube ↗</a>`;
  function trailerLinkHtml(d) {
    return (d.trailers || []).length ? '<button class="trailer-link">▶ Trailer</button>' : trailerSearchHtml(d);
  }
  function detailHtml(d) {
    const p = d.payload || {};
    const poster = p.Poster && p.Poster !== 'N/A' ? `<img class="poster" src="${esc(p.Poster)}" alt="">` : '';
    // Summary: TMDB's overview first, OMDb's short plot only when there is none (spec D1).
    const summary = d.overview || (p.Plot && p.Plot !== 'N/A' ? p.Plot : '');
    const fields = [['Genre', esc(p.Genre)], ['Runtime', esc(p.Runtime)], ['Rated', esc(p.Rated)], ['Country', esc(p.Country)],
      ['Language', esc(d.language)], ['Awards', esc(p.Awards)], ['Cast', castHtml(d, p)], ['Writer', writerHtml(d, p)]]
      .filter(([, v]) => v && v !== 'N/A').map(([k, v]) => `<dt>${k}</dt><dd class="dd-${k.toLowerCase()}">${v}</dd>`).join('');
    const svc = d.services || [];
    // Services arrive already ranked (subscribed, quality, Apple TV app, name — see
    // domain/watch.py). A film can carry dozens of them, so show the best few and put the
    // rest behind a native <details> disclosure: no filtering, because a service you rate
    // badly is still the answer when it is the only place a film exists.
    const collapse = (names) => names.length <= TOP_SERVICES ? names.join(', ')
      : `${names.slice(0, TOP_SERVICES).join(', ')} <details class="svc-more"><summary>⋯ ${names.length - TOP_SERVICES} more</summary><span class="svc-rest">, ${names.slice(TOP_SERVICES).join(', ')}</span></details>`;
    const streaming = collapse(svc.filter((s) => s.kind !== 'store')
      .map((s) => s.subscribed ? esc(s.name) : `${esc(s.name)} (not subscribed)`));
    // Every store entry links to the Apple TV app when the film holds an itunes id (the
    // registry has exactly one store, apple-tv-store) — plain text otherwise.
    // A store id alone also earns the line: CheapCharts keys a product only for a title Apple sells,
    // and TMDB's provider feed misses some entirely (Memories of Murder, 2026-09-20: a store id, no
    // US provider at all — 133 unowned films were in that state, so the drawer offered Wishlist it
    // but no way into the Apple TV app). Same reasoning as `reachable`. An owned film needs no
    // such line: its watch line already opens the app.
    const stores = svc.filter((s) => s.kind === 'store').map((s) => s.name);
    if (!stores.length && d.apple_tv_url && !d.owned) stores.push(APPLE_STORE);
    const buyable = collapse(stores
      .map((name) => d.apple_tv_url ? `<a class="store-link" href="${esc(d.apple_tv_url)}">${esc(name)}</a>` : esc(name)));
    const newOn = (d.new_on || []).map((t) => `${esc(t.name)} since ${esc(t.appeared_on)}`).join(', ');
    const lists = (d.lists || []).map((l) => {
      const label = esc(l.name);  // the same name the picker shows, so the two agree
      // rank_label is the cell AS PRINTED, so a tie arrives as "=54"; the drawer shows the
      // number alone (#54) — whether the placing was tied is not what this line is for.
      const rank = String(l.rank_label ?? l.rank).replace(/^=/, '');
      return l.ordered ? `${label} #${esc(rank)}` : label;
    }).join(', ');
    // Ratings block (spec D5): the same three numbers the table columns show, never OMDb's
    // Ratings array; then the lists line with the canon score the On-a-list sort uses.
    const critics = [
      d.imdb != null ? `IMDb <b>${d.imdb.toFixed(1)}</b>` : '',
      d.metacritic != null ? `Metacritic <b>${esc(d.metacritic)}</b>` : '',
      d.rt != null ? `Rotten Tomatoes <b>${esc(d.rt)}%</b>` : '',
    ].filter(Boolean).join(' · ');
    const criticsLine = critics ? `<div class="row critics">${critics}</div>`
      : d.pending ? '<div class="row note">OMDb lookup pending.</div>'
      : d.found === false ? '<div class="row note">No OMDb match.</div>' : '';
    const old = d.old_rating;
    const oldLine = old ? `<div class="row old-rating">Me, ${OLD_SPAN}: <span class="old-stars" aria-label="${old.stars} of 5 stars">${'★'.repeat(old.stars)}${'☆'.repeat(5 - old.stars)}</span>${old.rented_on ? ` · rented ${esc(old.rented_on)}` : ''}</div>` : '';
    const listsLine = lists ? `<div class="row on-lists">On lists: ${lists} <span class="canon-score">· canon score ${canonScore(d).toFixed(1)}</span></div>` : '';
    // The one watch link (spec D6/D7). Possession short-circuits the ranking in domain/watch.py.
    // An owned film opens straight in the Apple TV desktop app via d.apple_tv_url (the app's own
    // com.apple.tv:// scheme on the film's itunes id — domain/watch.py::apple_tv_url); without an
    // id it falls back to the store's own url (best_source's template) and then a tv.apple.com
    // search. A custom scheme gets no target/rel — a new tab for it would just sit there blank.
    const bs = d.best_source;
    let watchLine = '';
    if (d.owned) {
      const appLink = !!d.apple_tv_url;
      const href = d.apple_tv_url || (bs && bs.url) || `https://tv.apple.com/search?term=${encodeURIComponent(d.title)}`;
      const attrs = appLink ? '' : ' target="_blank" rel="noopener"';
      watchLine = `<p class="meta best-source"><a class="owned-link" data-opens="${appLink ? 'app' : 'web'}" href="${esc(href)}"${attrs}>Owned on Apple TV ↗</a></p>`;
    } else if (bs) {
      const label = `Watch on <b>${esc(bs.name)}</b>${bs.subscribed ? '' : ' (not subscribed)'} ↗`;
      watchLine = `<p class="meta best-source">${bs.url ? `<a class="watch-link" href="${esc(bs.url)}" target="_blank" rel="noopener">${label}</a>` : label}</p>`;
    }
    const credited = d.credits && d.credits.director;
    const director = d.director ? personLink('director', d.director, !!credited, credited || d.director) : '—';
    // Move-tier spec M4/M7: the tier row exists only for a film the open session has placed
    // (`rank_tier` is detail-only); a click hands the film to the Order tab, never to a slot.
    const tierRow = d.rank_tier == null ? '' : `<div class="tier-row"><span class="tier-label">Tier</span>${[1, 2, 3, 4, 5].map((t) => `<button class="tier-pick" data-id="${d.id}" data-tier="${t}"${t === d.rank_tier ? ' aria-current="true"' : ''} title="Move to tier ${t}">${t}</button>`).join('')}</div>`;
    return `<h2>${esc(d.title)} <button class="copy-title" data-title="${esc(d.title)}" title="Copy the title" aria-label="Copy the title">⧉</button><button class="watch-toggle" data-id="${d.id}" title="Toggle watchlist" aria-label="Toggle watchlist">${d.watchlisted ? '★' : '☆'}</button><button class="revisit-toggle" data-id="${d.id}" title="Toggle needs-revisit" aria-label="Toggle needs-revisit">${d.needs_revisit ? '⚑' : '⚐'}</button></h2>
      <div class="unseen-row"><button class="unseen-toggle" data-id="${d.id}" aria-pressed="${d.unseen ? 'true' : 'false'}" title="Toggle unseen (the ranker skips it)">Unseen</button><button class="rank-toggle" data-id="${d.id}"${rankToggleAttrs(d.rank_marked, d.awaiting_order, d.rank_tier)}>Rank this</button></div>
      ${tierRow}
      ${d.needs_revisit ? `<input class="revisit-note" data-id="${d.id}" placeholder="what looks wrong?" value="${esc(d.revisit_note || '')}">` : ''}
      <div class="meta">${fmt(d.year)} · ${director}${d.departed ? ' · <b>Gone from Criterion</b>' : ''}</div>
      ${summary ? `<p>${poster}${esc(summary)}</p>` : poster}
      <dl>${fields}</dl>
      <div class="ratings">
        <div class="row">My rating: <input class="rating" maxlength="2" data-id="${d.id}" value="${d.my_rating ?? ''}" aria-label="My rating"></div>
        ${oldLine}${criticsLine}${listsLine}
      </div>
      ${watchLine}
      ${newOn ? `<p class="meta new-on">New on: ${newOn}</p>` : ''}
      ${streaming ? `<p class="meta">Also streaming on: ${streaming}</p>` : ''}
      ${buyable ? `<p class="meta">Buy on: ${buyable}</p>` : ''}
      <p class="links">${trailerLinkHtml(d)}${d.url ? ` <a class="criterion criterion-link" href="${esc(d.url)}" target="_blank" rel="noopener">Open on Criterion ↗</a>` : ''}
        ${d.tmdb_url ? ` <a class="criterion tmdb-link" href="${esc(d.tmdb_url)}" target="_blank" rel="noopener">TMDB ↗</a>` : ''}
        ${d.cheapcharts_url
          ? ` <a class="criterion cheapcharts-link" href="${esc(d.cheapcharts_url)}" target="_blank" rel="noopener">CheapCharts ↗</a>`
          : buyable ? ` <a class="criterion cheapcharts-link" href="https://www.cheapcharts.com/us/search;q=${encodeURIComponent(d.title)};t=all" target="_blank" rel="noopener">Find on CheapCharts ↗</a>` : ''}${wishHtml(d)}</p>
      ${renderAudit(d)}
      <details><summary>Raw OMDb payload</summary><pre class="raw">${esc(d.payload ? JSON.stringify(d.payload, null, 2) : 'null')}</pre></details>
      ${d.leaving_date ? `<p class="meta leaving"><b>Leaving ${esc(d.leaving_date)}</b></p>` : ''}`;
  }
  let drawerSeq = 0;
  let drawerOpenPushed = false; // true once the currently-open drawer got its own pushState entry
  let drawnFilm = null;         // the film whose details are on screen — where a failed step falls back to
  let drawnDetail = null;       // …and its detail payload: what the trailer window plays from
  // The one close choke point (direct close, popstate close, person links): the redraw is what
  // turns the white row into the mark.
  function hideDrawer() {
    closeTrailer();  // Back while a trailer is up must not leave it orphaned over the list
    drawer.hidden = true; backdrop.hidden = true; body.innerHTML = '';
    state.openFilm = null; drawnFilm = null; drawnDetail = null; openIndex = null; movedOn = null;
    renderRows();
  }
  // ---- The trailer window (brief 2026-09-20-trailer-link) ----
  // Plays the film's STORED trailers (`enrich trailers` looked them up; nothing is fetched here) in
  // play order: the videos TMDB types as a trailer, on YouTube, then Apple's own store preview.
  // Over the whole browser window, playing at once, never in the URL or history. Whatever fails —
  // YouTube's onError (removed, embedding refused), its script not loading, a player that never
  // becomes READY (seen in rehearsal: YouTube sat on a broken video and reported nothing; an advert
  // plays AFTER ready, so it cannot trip this), Apple's file erroring — falls through to the next
  // source, and past the last one the window says so. YouTube's script is injected on the FIRST
  // trailer, never at page load: the dashboard must not need YouTube to boot.
  const trailerEl = $('#trailer'), trailerScreen = $('#trailer-screen');
  const trailerCfg = { readyMs: 8000 };
  let trailer = null;      // { d, list, i, seq, failed } while the window is up
  let ytPlayer = null, ytTimer = null, ytApi = null;
  function loadYouTube() {
    ytApi = ytApi || new Promise((resolve, reject) => {
      if (window.YT && window.YT.Player) return resolve();
      window.onYouTubeIframeAPIReady = resolve;  // fires once per page: set BEFORE the script goes in
      const el = document.createElement('script');
      el.src = 'https://www.youtube.com/iframe_api';
      el.onerror = () => { ytApi = null; el.remove(); reject(new Error('youtube unreachable')); };  // the next trailer retries
      document.head.appendChild(el);
    });
    return ytApi;
  }
  function dropPlayer() {
    clearTimeout(ytTimer); ytTimer = null;
    if (ytPlayer) { try { ytPlayer.destroy(); } catch { /* already gone */ } ytPlayer = null; }
    const v = trailerScreen.querySelector('video');
    if (v) { v.pause(); v.removeAttribute('src'); v.load(); }  // or the download carries on behind a closed window
    trailerScreen.innerHTML = '';
  }
  function closeTrailer() {
    if (!trailer) return;
    trailer = null; dropPlayer(); trailerEl.hidden = true;
  }
  function playTrailer(i) {
    const run = trailer; if (!run) return;
    dropPlayer();
    run.i = i;
    const seq = ++run.seq, { d, list } = run, src = list[i];
    // Every callback below may arrive late — after a close, a switch, a fall-through — and must then
    // do nothing: `live` is the token. A failure marks its source and moves to the first source that
    // has not failed, so Apple failing after a hand-made switch goes BACK to a working YouTube.
    // Deferred, because YouTube calls onError from inside the player a fall-through destroys.
    const live = () => trailer === run && run.seq === seq;
    const fail = (every) => setTimeout(() => {
      if (!live()) return;
      list.forEach((t, k) => { if (k === i || (every && t.source === 'youtube')) run.failed.add(k); });
      const k = list.findIndex((_, j) => !run.failed.has(j));
      playTrailer(k >= 0 ? k : list.length);
    }, 0);
    $('#trailer-frame').className = src && src.source === 'apple' ? 'apple' : '';
    $('#trailer-title').textContent = `${d.title}${d.year ? ` (${d.year})` : ''}`;
    $('#trailer-what').textContent = !src ? '' : src.source === 'apple' ? `— ${src.name}` : `— ${src.name} · YouTube`;
    const yt = list.findIndex((t, k) => t.source === 'youtube' && !run.failed.has(k));
    const apple = list.findIndex((t, k) => t.source === 'apple' && !run.failed.has(k));
    $('#trailer-sources').innerHTML = src && yt >= 0 && apple >= 0
      ? `<button data-i="${src.source === 'youtube' ? i : yt}"${src.source === 'youtube' ? ' class="on"' : ''}>YouTube</button><button data-i="${apple}"${src.source === 'apple' ? ' class="on"' : ''}>Apple</button>` : '';
    if (!src) {
      trailerScreen.innerHTML = `<div class="trailer-sorry"><div>This trailer won't play here.</div>${trailerSearchHtml(d)}</div>`;
      return;
    }
    if (src.source === 'apple') {
      if (!/^https:\/\//.test(src.ref)) return void fail();
      const v = document.createElement('video');
      v.controls = true; v.autoplay = true; v.playsInline = true;
      v.addEventListener('error', () => fail());
      v.src = src.ref;
      trailerScreen.appendChild(v);
      return;
    }
    // The clock starts with the SOURCE, not the player: `iframe_api` is only a loader for a second
    // script, and if that one never arrives neither `onerror` nor ready ever fires. No API by then
    // means YouTube is unreachable — skip every YouTube source, not 8 s of black for each.
    let built = false;
    ytTimer = setTimeout(() => fail(!built), trailerCfg.readyMs);
    loadYouTube().then(() => {
      if (!live()) return;
      built = true;
      const slot = document.createElement('div');
      trailerScreen.appendChild(slot);
      ytPlayer = new window.YT.Player(slot, { videoId: src.ref, host: 'https://www.youtube-nocookie.com', width: '100%', height: '100%',
        playerVars: { autoplay: 1, rel: 0, playsinline: 1 },
        events: { onReady: (e) => { if (!live()) return; clearTimeout(ytTimer); ytTimer = null; e.target.playVideo(); }, onError: () => fail() } });
    }, () => fail(true));
  }
  // Only for the film whose details are ON SCREEN: right after ↓ the white row has moved but the
  // new film's details (and trailers) have not arrived — T must not play the previous film's.
  function openTrailer() {
    const d = drawnDetail, list = d && d.trailers || [];
    if (drawer.hidden || trailer || !list.length || state.openFilm !== drawnFilm) return;
    trailer = { d, list, i: 0, seq: 0, failed: new Set() }; trailerEl.hidden = false;
    playTrailer(0);
  }
  body.addEventListener('click', (e) => { if (e.target.closest('.trailer-link')) openTrailer(); });
  $('#trailer-close').addEventListener('click', closeTrailer);
  trailerEl.addEventListener('click', (e) => { if (e.target === trailerEl || e.target.classList.contains('trailer-hint')) closeTrailer(); });
  $('#trailer-sources').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b && trailer) playTrailer(Number(b.dataset.i)); });
  // CAPTURE phase, ahead of every other key handler on the page: while a trailer is up Esc closes
  // IT and not the drawer, and ↑ ↓ do not step the drawer underneath. Otherwise T plays the open
  // film's trailer — plain T only, and never while typing.
  document.addEventListener('keydown', (e) => {
    if (trailer) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); closeTrailer(); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); e.stopImmediatePropagation(); }
      return;
    }
    if ((e.key !== 't' && e.key !== 'T') || drawer.hidden || e.metaKey || e.altKey || e.ctrlKey) return;
    if (e.target.matches('input, textarea, select')) return;
    e.preventDefault(); openTrailer();
  }, true);

  // Person links (drawer spec D4). Close WITHOUT walking history back: closeDrawer() would call
  // history.back(), and the popstate handler then re-reads state from the previous URL, wiping
  // the query set here (spec §4's ordering hazard). Pushing a fresh entry instead leaves the
  // open-drawer entry behind it, so Back reopens the film — the undo the spec asks for. Touches
  // no chip, column filter, language or list (the list-picker ruling).
  body.addEventListener('click', (e) => {
    const a = e.target.closest('a.person'); if (!a) return;
    e.preventDefault();
    if (searchTimer) clearTimeout(searchTimer);
    drawerSeq++;              // supersede any in-flight open
    hideDrawer();
    drawerOpenPushed = false;
    state.q = a.dataset.query;
    searchEl.value = state.q;
    delete searchEl.dataset.settled;
    syncUrl(true);
    runSearch();
  });
  // mode: 'push' (a click — the open gets its own history entry), 'keep' (boot / popstate — the
  // URL already names the film, history is never touched) or 'step' (↑ ↓ — the open film is
  // REPLACED in the current entry and drawerOpenPushed is left alone, so one Back or ✕ still
  // closes the drawer however many films were stepped through; 'keep' would clear the flag and
  // the next close would push a stale film= entry behind itself).
  async function openDrawer(id, mode = 'push') {
    const seq = ++drawerSeq;
    const r = await fetch(`/api/films/${id}`);
    if (seq !== drawerSeq) return; // a newer open (or a close) superseded this one
    if (!r.ok) {
      toast('Film not found');
      // A step moved the white row ahead of its fetch: put it back on the film still on screen.
      if (mode === 'step') { state.openFilm = drawnFilm; state.mark = drawnFilm; renderRows(); }
      return;
    }
    const d = await r.json();
    if (seq !== drawerSeq) return;
    closeTrailer();  // a redraw (popstate, a step that was in flight) never happens under an open trailer
    body.innerHTML = detailHtml(d); drawnDetail = d;
    // Move on: the line rides with the film it was drawn for; any other film's draw ends it.
    if (movedOn && movedOn.at === id) body.querySelector('h2').insertAdjacentHTML('afterend', movedOnHtml(movedOn));
    else movedOn = null;
    drawer.hidden = false; backdrop.hidden = false; drawer.scrollTop = 0;
    state.openFilm = id; state.mark = id; drawnFilm = id;
    const at = state.filtered.findIndex((f) => f.id === id);
    openIndex = at >= 0 ? at : null;
    renderRows();
    if (mode === 'push') { syncUrl(true); drawerOpenPushed = true; }
    else if (mode === 'keep') drawerOpenPushed = false;
    else { try { syncUrl(); } catch { /* Safari throws past 100 replaceState calls in 30 s (a held key) */ } }
  }
  // Nudge the list only as far as needed to show the whole of row i below the sticky header.
  // Arithmetic, never scrollIntoView: a row outside the rendered window is not in the DOM.
  function revealRow(i) {
    const top = i * ROW_H, view = wrap.clientHeight - thead.offsetHeight;
    if (top < wrap.scrollTop) wrap.scrollTop = top;
    else if (top + ROW_H > wrap.scrollTop + view) wrap.scrollTop = top + ROW_H - view;
  }
  // Move the open drawer to row i of the shown list without closing it (↑ ↓, or a click on a
  // dimmed row). The white row moves at once; drawerSeq lets only the last film's details be drawn.
  function moveDrawerTo(i) {
    const next = state.filtered[i];
    if (!next || next.id === state.openFilm) return;
    state.openFilm = next.id; state.mark = next.id; openIndex = i;
    revealRow(i);
    renderRows();
    openDrawer(next.id, 'step');
  }
  // ↑ ↓: the previous / next film of the list exactly as it is shown. Does nothing at either end.
  // When the open film has LEFT the list (see openIndex), ↓ opens the film now in its place and ↑
  // the one before it; a film that was never in the list leaves the arrows quiet.
  function stepDrawer(dir) {
    const i = state.filtered.findIndex((f) => f.id === state.openFilm);
    if (i >= 0) moveDrawerTo(i + dir);
    else if (openIndex != null) moveDrawerTo(dir > 0 ? openIndex : openIndex - 1);
  }
  // ---- Move on (brief docs/superpowers/briefs/2026-09-24-move-on/brief.md) ----
  // After a drawer EDIT has landed (a rating, the ★, the ♡ — the three edits a filter reads), if
  // the open film is no longer in the shown list, take the step ↓ would have taken: to the film
  // now at its index, or the one before at the end. Called on the edit paths ONLY — never from
  // applyFilters — so a chip, the search, the list picker, a column filter or Back still leave
  // the gap (find-my-row story 6). A film that was never in the list (openIndex null) stays put;
  // an empty list moves nothing. `edit` is what the moved-to drawer's undo line remembers.
  let movedOn = null;  // { at, film, label, slow, undo } — the last edit that moved the drawer on
  function moveOnIfLeft(edit) {
    if (edit.film !== state.openFilm) return false;
    if (drawer.hidden || openIndex == null) return false;
    if (state.filtered.some((f) => f.id === state.openFilm)) return false;
    if (!state.filtered.length) return false;
    const i = Math.min(openIndex, state.filtered.length - 1);
    movedOn = { ...edit, at: state.filtered[i].id };
    moveDrawerTo(i);
    return true;
  }
  // The line under the moved-to drawer's title: "Wishlisted Pan's Labyrinth · Undo". Only the
  // LAST edit has one; it lasts until that drawer is redrawn (openDrawer clears it for any other
  // film, hideDrawer always). A failed wishlist Undo keeps the words and offers Try again in
  // Undo's place; a failed rating or star Undo toasts (inside edit.undo) and keeps its Undo.
  function movedOnHtml(m, failed = false) {
    if (m.busy) return `<div class="moved-on">${esc(m.label)} · <button class="undo" disabled>${m.slow ? 'Reaching CheapCharts…' : 'Undo'}</button></div>`;
    return `<div class="moved-on">${esc(m.label)} ·${failed ? ' <span class="wish-failed">Couldn\'t reach CheapCharts.</span>' : ''} <button class="undo">${failed ? 'Try again' : 'Undo'}</button></div>`;
  }
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.moved-on button.undo'); if (!b || b.disabled || !movedOn) return;
    const m = movedOn;
    m.busy = true; b.disabled = true; if (m.slow) b.textContent = 'Reaching CheapCharts…';
    const ok = await m.undo();  // the exact reverse call; on success the film is back in state.films and the list
    const line = body.querySelector('.moved-on');
    if (!ok) { m.busy = false; if (line && movedOn === m) line.outerHTML = movedOnHtml(m, m.slow); return; }
    // Landing rule: the row is back already; the drawer goes back to the film only if nothing was
    // stepped, clicked or closed since Undo was pressed (any other draw cleared movedOn). Clear
    // movedOn on a match regardless of where the drawer landed, so an undone edit never comes back
    // as a fresh, enabled Undo on a later redraw of the line's film.
    const landing = movedOn === m && !drawer.hidden && state.openFilm === m.at;
    if (movedOn === m) movedOn = null;
    if (!landing) return;
    const i = state.filtered.findIndex((f) => f.id === m.film);
    if (i >= 0) moveDrawerTo(i); else if (line) line.remove();
  });
  // The index of the film row showing through the dim at a point, or -1. Only the TOPMOST thing
  // under the backdrop counts: a row scrolled beneath the sticky header is not showing, and the
  // white row is pointer-events:none, so both read as "no row" and a click there closes.
  function dimmedRowAt(x, y) {
    const under = document.elementsFromPoint(x, y).find((el) => el !== backdrop);
    const tr = under && under.closest('#films tbody tr[data-id]');
    return tr ? state.filtered.findIndex((f) => f.id === +tr.dataset.id) : -1;
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
    if (!drawer.hidden) return; // a keyboard Enter on a still-focused ⓘ would push a second history entry
    const tr = e.target.closest('tr[data-id]'); if (!tr) return;
    revealRow(state.filtered.findIndex((f) => f.id === +tr.dataset.id)); // a half-hidden row is shown whole first
    openDrawer(+tr.dataset.id);
  });
  $('#drawer-close').addEventListener('click', () => closeDrawer());
  // One click on another film's row switches the drawer to it (owner request 2026-09-20: it used
  // to close, and the film took a second click). Anywhere in the row counts — a title link or a
  // rating box under the dim is just the row. Any other click on the dim closes, as before.
  backdrop.addEventListener('click', (e) => {
    const i = dimmedRowAt(e.clientX, e.clientY);
    if (i >= 0) moveDrawerTo(i); else closeDrawer();
  });
  backdrop.addEventListener('mousemove', (e) => {
    backdrop.style.cursor = dimmedRowAt(e.clientX, e.clientY) >= 0 ? 'pointer' : '';
  });
  // Copy the title (owner request 2026-09-22): the title alone, no year, so it pastes straight
  // into a search box elsewhere. The button itself reports success — ✓ for a moment — because
  // the toast is the dashboard's error voice.
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.copy-title'); if (!b) return;
    try {
      await navigator.clipboard.writeText(b.dataset.title);
      b.textContent = '✓';
      setTimeout(() => { b.textContent = '⧉'; }, 1200);
    } catch (err) {
      toast('Could not copy the title');
    }
  });
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.watch-toggle'); if (!b) return;
    const r = await fetch(`/api/films/${b.dataset.id}/watchlist`, { method: 'POST' });
    if (!r.ok) { toast('Could not update watchlist'); return; }
    const { watchlisted } = await r.json();
    b.textContent = watchlisted ? '★' : '☆';
    const film = state.films.find((f) => f.id === +b.dataset.id);
    if (film) {
      film.watchlisted = watchlisted; applyFilters();
      moveOnIfLeft({ film: film.id, slow: false,
        label: watchlisted ? `Starred ${film.title}` : `Took ${film.title} off your watchlist`,
        undo: async () => {
          const r2 = await fetch(`/api/films/${film.id}/watchlist`, { method: 'POST' }).catch(() => null);
          if (!r2 || !r2.ok) { toast('Could not update watchlist'); return false; }
          const j = await r2.json(), f = state.films.find((x) => x.id === film.id);
          if (f) { f.watchlisted = j.watchlisted; applyFilters(); }
          return true;
        } });
    }
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
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.unseen-toggle'); if (!b) return;
    const next = b.getAttribute('aria-pressed') !== 'true';
    const r = await fetch(`/api/films/${b.dataset.id}/unseen`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ unseen: next }) });
    if (!r.ok) { toast('Could not update unseen'); return; }
    const { unseen } = await r.json();
    b.setAttribute('aria-pressed', String(unseen));
    const film = state.films.find((f) => f.id === Number(b.dataset.id));
    if (film) film.unseen = unseen;
  });
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.wish-button'); if (!b || b.disabled) return;
    const slot = b.closest('.wish'); const id = Number(slot.dataset.id);
    const film = state.films.find((f) => f.id === id);
    // The mark is the un-wishlist button (brief 1.2: the click is reversible). "Try again" sits in
    // the same slot and repeats whichever action failed, remembered on the slot.
    if (!b.closest('.wish-failed')) slot.dataset.action = b.classList.contains('wish-done') ? 'remove' : 'add';
    const removing = slot.dataset.action === 'remove';
    // Adding paces four or five calls to CheapCharts (5-10 s); removing is two. A "Try again"
    // click starts inside .wish-failed; swap the WHOLE slot to a fresh busy button first, so the
    // stale failure text never shows beside it, and so it cannot be clicked twice.
    slot.innerHTML = '<button class="wish-button" disabled>Reaching CheapCharts…</button>';
    const r = await fetch(`/api/films/${id}/wishlist`, { method: removing ? 'DELETE' : 'POST' }).catch(() => null);
    if (!r || !r.ok) {
      // One line whatever went wrong — offline, a refused password, no price history — a failed
      // add marks nothing, and a failed removal changes nothing: the heart it already had stays.
      slot.innerHTML = '<span class="wish-failed">Couldn\'t reach CheapCharts. <button class="wish-button">Try again</button></span>';
      return;
    }
    // Patch in place, as the toggles do: re-opening the drawer would desync closeDrawer()'s history bookkeeping.
    const wishlisted = !removing;
    if (film) { film.wishlisted = wishlisted; applyFilters(); }
    // An owned film gets no add button: its slot simply empties.
    slot.innerHTML = wishSlotHtml({ ...(film || {}), id, wishlisted });
    // The slot above was patched while it is still on screen; if the film left the list the
    // drawer now moves on, and the moved-to drawer's line is how the click is taken back.
    if (film) moveOnIfLeft({ film: id, slow: true,
      label: wishlisted ? `Wishlisted ${film.title}` : `Took ${film.title} off your wishlist`,
      undo: async () => {
        const r2 = await fetch(`/api/films/${id}/wishlist`, { method: wishlisted ? 'DELETE' : 'POST' }).catch(() => null);
        if (!r2 || !r2.ok) return false;
        const f = state.films.find((x) => x.id === id);
        if (f) { f.wishlisted = !wishlisted; applyFilters(); }
        return true;
      } });
  });
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.tier-pick'); if (!b || b.getAttribute('aria-current') === 'true') return;
    const r = await fetch('/api/rank/move', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ film_id: Number(b.dataset.id), tier: Number(b.dataset.tier) }) });
    const json = await r.json().catch(() => ({}));
    if (!r.ok) { toast(json.error || 'Could not move the film'); return; }
    // Patch in place, as the toggles do: re-opening the drawer would desync closeDrawer()'s history bookkeeping.
    for (const p of body.querySelectorAll('.tier-pick')) { if (Number(p.dataset.tier) === json.tier) p.setAttribute('aria-current', 'true'); else p.removeAttribute('aria-current'); }
    const film = state.films.find((f) => f.id === json.film_id);
    const rank = body.querySelector('.rank-toggle');
    if (rank) paintRankToggle(rank, !!(film && film.rank_marked), json.awaiting_order, json.tier);
  });
  body.addEventListener('click', async (e) => {
    const b = e.target.closest('.rank-toggle'); if (!b) return;
    const film = state.films.find((f) => f.id === Number(b.dataset.id));
    if (b.dataset.placed === '1') {   // placed and ordered: the click is a re-rank, not a mark
      const r = await fetch('/api/rank/rerank', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ film_id: Number(b.dataset.id) }) });
      const json = await r.json().catch(() => ({}));
      if (!r.ok) { toast(json.error || 'Could not re-rank the film'); return; }
      const row = body.querySelector('.tier-row'); if (row) row.remove();   // unplaced now: no tier to move
      paintRankToggle(b, true, false, null);
      if (film) film.rank_marked = true;
      return;
    }
    const next = b.getAttribute('aria-pressed') !== 'true';
    const r = await fetch(`/api/films/${b.dataset.id}/rank-mark`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ marked: next }) });
    if (!r.ok) { toast('Could not update rank mark'); return; }
    const { marked } = await r.json();
    paintRankToggle(b, marked, false, null);
    if (film) film.rank_marked = marked;
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
  // While the drawer is open the plain arrow keys belong to stepping (so they no longer scroll the
  // drawer's own content; the wheel, Space and Page Down still do). Typing and modified arrows are
  // left alone.
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    if (drawer.hidden || e.metaKey || e.altKey || e.ctrlKey || e.shiftKey) return;
    if (e.target.matches('input, textarea, select')) return;
    e.preventDefault();
    stepDrawer(e.key === 'ArrowDown' ? 1 : -1);
  });
  window.addEventListener('popstate', () => {
    readUrl(); writeControlsFromState();
    // A pushed q= entry (a person link) can be walked back: state.search must follow the URL,
    // or the table stays filtered by a query that is no longer in the box or the address bar.
    if (state.q !== (searchEl.dataset.settled ?? '')) { delete searchEl.dataset.settled; runSearch(); }
    else applyFilters();
    if (state.openFilm != null) openDrawer(state.openFilm, 'keep'); else closeDrawer(true);
  });

  window.MB = { state, applyFilters, render: renderRows, renderCounts, rowHtml, trailer: trailerCfg, onBoot: () => { if (state.openFilm != null) openDrawer(state.openFilm, 'keep'); } };

  // ---- boot ----
  async function boot() {
    const [cfg, films] = await Promise.all([fetch('/api/config').then((r) => r.json()), fetch('/api/films').then((r) => r.json())]);
    state.cfg = cfg; state.films = films;
    populateLanguages();
    populateLists();
    readUrl();
    writeControlsFromState();
    renderCounts();
    applyFilters();
    if (state.q) runSearch(); else searchEl.dataset.settled = '';
    if (window.MB.onBoot) window.MB.onBoot();
  }
  boot().catch((e) => toast(`Failed to load: ${e.message}`));
})();
