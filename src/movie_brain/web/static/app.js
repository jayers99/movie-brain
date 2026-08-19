(() => {
  'use strict';
  const ROW_H = 36, OVERSCAN = 10;
  const COLS = ['title', 'year', 'director', 'language', 'imdb', 'rt', 'leaving_date', 'my_rating'];
  const state = {
    films: [], cfg: null, chips: new Set(),
    cols: { title: '', director: '', languages: new Set(), yearMin: null, yearMax: null, imdbMin: null, imdbMax: null, rtMin: null, rtMax: null },
    sort: null,            // {col, dir} or null = default
    filtered: [], openFilm: null,
  };
  const $ = (s) => document.querySelector(s);
  const tbody = $('#films tbody'), wrap = $('#table-wrap');

  // ---- canned predicates (mirror domain/filters.py; thresholds come from /api/config) ----
  const daysBetween = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000);
  const CHIP_PREDICATES = {
    leaving: (f) => f.leaving_date != null,
    unrated: (f) => f.my_rating == null,
    mine: (f) => f.my_rating != null && f.my_rating >= 1,
    not_interested: (f) => f.my_rating === 0,
    pending: (f) => f.pending || f.found === false,
    top_rt: (f) => f.rt != null && f.rt >= state.cfg.canned_thresholds.top_rt,
    top_imdb: (f) => f.imdb != null && f.imdb >= state.cfg.canned_thresholds.top_imdb,
    recent: (f) => f.first_seen != null && daysBetween(f.first_seen, state.cfg.today) <= state.cfg.canned_thresholds.recent_days,
  };

  // ---- filtering / sorting ----
  const inRange = (v, lo, hi) => v != null && (lo == null || v >= lo) && (hi == null || v <= hi);
  function rowMatches(f) {
    for (const c of state.chips) if (!CHIP_PREDICATES[c](f)) return false;
    const k = state.cols;
    if (k.title && !f.title.toLowerCase().includes(k.title)) return false;
    if (k.director && !(f.director || '').toLowerCase().includes(k.director)) return false;
    if (k.languages.size) {
      const langs = (f.language || '').split(',').map((s) => s.trim());
      if (![...k.languages].some((l) => langs.includes(l))) return false;
    }
    if ((k.yearMin != null || k.yearMax != null) && !inRange(f.year, k.yearMin, k.yearMax)) return false;
    if ((k.imdbMin != null || k.imdbMax != null) && !inRange(f.imdb, k.imdbMin, k.imdbMax)) return false;
    if ((k.rtMin != null || k.rtMax != null) && !inRange(f.rt, k.rtMin, k.rtMax)) return false;
    return true;
  }
  const byTitle = (a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: 'base' });
  function compare(a, b) {
    if (!state.sort) {  // default: imdb desc, nulls last, then title
      if (a.imdb == null !== (b.imdb == null)) return a.imdb == null ? 1 : -1;
      if (a.imdb != null && a.imdb !== b.imdb) return b.imdb - a.imdb;
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
    $('#count-showing').textContent = `Showing ${state.filtered.length} of ${state.films.length}`;
    renderRows();
    syncUrl();
  }

  // ---- summary (mirrors Repository.summary) ----
  function renderCounts() {
    const f = state.films;
    const n = (p) => f.filter(p).length;
    $('#count-films').textContent = f.length;
    $('#count-rated').textContent = n((x) => x.found === true);
    $('#count-pending').textContent = n((x) => x.pending);
    $('#count-unmatched').textContent = n((x) => x.found === false);
    $('#count-leaving').textContent = n((x) => x.leaving_date != null);
    $('#count-mine').textContent = n((x) => x.my_rating != null);
  }

  // ---- virtual-scrolled rows ----
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (v, suffix = '') => (v == null ? '—' : `${v}${suffix}`);
  function rowHtml(f) {
    const title = f.url ? `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.title)}</a>` : esc(f.title);
    return `<tr data-id="${f.id}">
      <td class="c-title">${title}</td><td class="c-year">${fmt(f.year)}</td><td class="c-director">${esc(f.director) || '—'}</td>
      <td class="c-language">${esc(f.language) || '—'}</td><td class="c-imdb num">${f.imdb == null ? '—' : f.imdb.toFixed(1)}</td>
      <td class="c-rt num">${fmt(f.rt, '%')}</td><td class="c-leaving">${esc(f.leaving_date) || ''}</td>
      <td class="c-rating num"><input class="rating" maxlength="2" data-id="${f.id}" value="${f.my_rating ?? ''}" aria-label="My rating"></td>
      <td class="c-info"><button class="info" data-id="${f.id}" aria-label="Details">ⓘ</button></td></tr>`;
  }
  function renderRows() {
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
    const k = state.cols;
    if (k.title) p.set('title', k.title);
    if (k.director) p.set('director', k.director);
    if (k.languages.size) p.set('lang', [...k.languages].join('|'));
    for (const [name, lo, hi] of [['year', k.yearMin, k.yearMax], ['imdb', k.imdbMin, k.imdbMax], ['rt', k.rtMin, k.rtMax]]) {
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
    const k = state.cols;
    k.title = (p.get('title') || '').toLowerCase();
    k.director = (p.get('director') || '').toLowerCase();
    k.languages = new Set((p.get('lang') || '').split('|').filter(Boolean));
    const range = (name) => { const v = p.get(name); if (!v) return [null, null]; const [lo, hi] = v.split('-'); return [lo === '' ? null : +lo, hi === '' || hi == null ? null : +hi]; };
    [k.yearMin, k.yearMax] = range('year'); [k.imdbMin, k.imdbMax] = range('imdb'); [k.rtMin, k.rtMax] = range('rt');
    const s = p.get('sort');
    state.sort = s && COLS.includes(s.split(':')[0]) && ['asc', 'desc'].includes(s.split(':')[1]) ? { col: s.split(':')[0], dir: s.split(':')[1] } : null;
    const film = p.get('film');
    state.openFilm = film ? +film : null;
  }
  function writeControlsFromState() {
    document.querySelectorAll('.chip[data-chip]').forEach((b) => b.classList.toggle('active', state.chips.has(b.dataset.chip)));
    const k = state.cols;
    $('#f-title').value = k.title; $('#f-director').value = k.director;
    for (const o of $('#f-lang').options) o.selected = k.languages.has(o.value);
    const set = (id, v) => { $(id).value = v == null ? '' : v; };
    set('#f-year-min', k.yearMin); set('#f-year-max', k.yearMax); set('#f-imdb-min', k.imdbMin); set('#f-imdb-max', k.imdbMax); set('#f-rt-min', k.rtMin); set('#f-rt-max', k.rtMax);
    document.querySelectorAll('th.sortable').forEach((th) => {
      if (state.sort && th.dataset.col === state.sort.col) th.dataset.dir = state.sort.dir; else delete th.dataset.dir;
    });
  }

  // ---- controls ----
  $('#chips').addEventListener('click', (e) => {
    const b = e.target.closest('.chip'); if (!b) return;
    if (b.id === 'chips-clear') state.chips.clear();
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
    k.languages = new Set([...$('#f-lang').selectedOptions].map((o) => o.value));
    k.yearMin = num('#f-year-min'); k.yearMax = num('#f-year-max');
    k.imdbMin = num('#f-imdb-min'); k.imdbMax = num('#f-imdb-max');
    k.rtMin = num('#f-rt-min'); k.rtMax = num('#f-rt-max');
    applyFilters();
  }
  document.querySelectorAll('thead tr.filters input, thead tr.filters select').forEach((el) => {
    el.addEventListener('input', readControls);
    el.addEventListener('change', readControls);
  });
  function populateLanguages() {
    const langs = new Set();
    state.films.forEach((f) => (f.language || '').split(',').map((s) => s.trim()).filter(Boolean).forEach((l) => langs.add(l)));
    $('#f-lang').innerHTML = [...langs].sort().map((l) => `<option value="${esc(l)}">${esc(l)}</option>`).join('');
  }

  // ---- rating + drawer hooks (implemented in Task 12) ----
  window.MB = { state, applyFilters, render: renderRows, renderCounts, rowHtml };

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
  boot();
})();
