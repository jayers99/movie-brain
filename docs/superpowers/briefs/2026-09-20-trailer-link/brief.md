# Task brief — a trailer link in the drawer (backlog 4, trailer half)

**Version 1.0 — frozen 2026-09-20.** You walked the mock-up [mockup-1.html](mockup-1.html) and chose **C-2**: the trailer link FIRST in the links row, and a grey "Find a trailer on YouTube ↗" search link on a film with no trailer ("c-2 mockup looks great. proceed"). You raised nothing against Apple's previews, so they stay as the stand-in. A cold read-back by a fresh agent reconstructed the intent correctly; its 18 findings are folded in below. From here the brief changes only by amendment. (To replay the mock-up serve it over http — YouTube refuses to play inside a `file://` page: `python3 -m http.server 5599` in this directory.) *Where the mock-up and this brief disagree, the brief wins.* Fourth trial of the process in `docs/superpowers/research/2026-09-19-human-in-loop-diet-v2.md`; stories first.

## Your page

### The question you asked first: which source?

**TMDB's video list, filtered to the type TMDB calls Trailer, played from YouTube; Apple's own store preview as the stand-in.** Measured 2026-09-20 on 400 films drawn at random from the live catalogue (`scripts/discovery/trailer_spike.py`, seed 20260920):

| | TMDB → YouTube | Apple preview | either |
|---|---|---|---|
| Films holding a store id (199) — every Shop film is one | 177 · 89% | 183 · 92% | **198 · 99%** |
| Films with no store id (201) | 67 · 33% | — | 67 · 33% |
| All 400 | 244 · 61% | 183 | **265 · 66%** |

- Every YouTube pick was checked against YouTube's oEmbed: 243 of 244 exist and allow embedding; the one dead first pick (Sleeping Beauty) had a live second trailer.
- 30 picks read by title: 30 trailers, no reviews, no reactions (one box-set trailer: Paisan → the BFI's "War Trilogy").
- **Why CheapCharts looks bogus:** its `trailers.youtube` list is TMDB's first five videos of ANY type — for Memories of Murder a trailer, a teaser, a clip, a second trailer and a Lincoln Center introduction. The `type` label is the whole fix.
- Trailers filed under another language rescue only 12 of 156 misses, and some are dubs (an Italian-dubbed trailer for Rosencrantz and Guildenstern Are Dead) — so: English, no-language, or the film's own language, never a third.
- Apple previews are direct `.m4v` files (no player, no adverts, nothing to refuse) but 640 px wide. Durations seen: 57 s, 104 s, 154 s — trailer-length, not proof. OMDb has none. A YouTube search is never played, only ever linked.

### The stories

All on real films, read from a copy of the live database on 2026-09-20; every trailer named below was played in a headless rehearsal and its title copied from the rehearsal's output.

| # | Story |
|---|---|
| 1 | **One click, and the trailer is playing.** I open Army of Shadows and click ▶ Trailer. Everything dims, the trailer comes up centred over the whole browser window and starts by itself, with sound: STUDIOCANAL's Official 4K Restoration Trailer. Esc, ✕ or a click outside closes it — and the drawer is still open on Army of Shadows. |
| 2 | **The real trailer — not a clip, not a review.** Memories of Murder: TMDB files seven videos, among them "Mark Kermode reviews Memories of Murder", a clip and the director's introduction. movie-brain plays NEON's "MEMORIES OF MURDER Trailer". |
| 3 | **Browsing by trailer, hands on the keyboard.** Drawer open on Army of Shadows: T plays its trailer, Esc, ↓ to Pan's Labyrinth, T plays the Official 4K Trailer, Esc, ↓ to The Big Sleep. ↑ ↓ do nothing while a trailer is up. |
| 4 | **No YouTube trailer, so Apple's preview stands in.** To Die For (1995) has no trailer on TMDB. The link is there all the same and plays Apple's store preview in a smaller window. Same for Moonrise (1948). |
| 5 | **The link is where I expect it, film after film.** M has Open on Criterion among its links; The Big Sleep is owned, so no ♡ Wishlist it; Army of Shadows has CheapCharts and ♡ Wishlist it. ▶ Trailer is the first thing in the links row on all three. (Set aside: A, after CheapCharts, and B, last — both move sideways from film to film.) |
| 6 | **The awkward one: no trailer anywhere.** The Hitch-Hiker (1953), on two noir lists: no trailer on TMDB, not sold by Apple. In the trailer link's place the row says "Find a trailer on YouTube ↗" in grey, which opens a YouTube search for `The Hitch-Hiker 1953 trailer` in a new tab — never played inside movie-brain. (Set aside: 1, no link at all.) |
| 7 | **YouTube says no.** A trailer is deleted or refuses to play outside youtube.com: the next trailer on the list is tried, then Apple's preview; only when all fail does the window say "This trailer won't play here." with the YouTube search link. |

**Outcome.** From any open drawer, one click or one key puts the right trailer on screen, playing, without leaving movie-brain.

**What wins when things trade off.** The right video beats having a video: nothing is ever played that TMDB does not type as a trailer (or teaser) or that Apple does not publish as the film's preview.

**What deliberately does not ship.** No "other trailers" menu. No trailer badge or chip on the list. No ↑ ↓ trailer-surfing while the window is up. No per-film override for a wrong pick. No trailer lookup inside sync.

| Behaviour | Status |
|---|---|
| The pick (Trailer before Teaser, official first, then sharpest), YouTube inside the page, autoplay with sound after a click in Chrome | demonstrated — headless Chrome, default autoplay policy, all seven stories |
| Apple's preview as stand-in, the YouTube · Apple switch | demonstrated; whether the previews are trailers is **unresolved — yours to judge on stories 4 and 5** |
| Fall-through when YouTube refuses | simulated (two keys broken on purpose); with the final code it went through in about a second on two of three rehearsals — **one rehearsal sat on the broken video for 20 s+ without YouTube reporting an error**, so the build needs its own give-up timer (the mock-up has one for the simulated breakage only), designed so that an advert in front of a trailer is not mistaken for a failure |
| Link position C, no-trailer treatment 2 | simulated in the mock-up; **your choice** |
| Safari | unresolved — not tested |

## Builder's pages

**Decision provenance**

| Decision | Whose |
|---|---|
| A link in the drawer only; a window centred over the whole browser window; plays at once | your choice, 2026-09-20 |
| C: the link is first in the links row. 2: no trailer → the grey YouTube search link, new tab | your choice on the mock-up, 2026-09-20 |
| Source = TMDB typed videos → YouTube, Apple preview second, never a search result played | agent recommendation from the measurement; shown on the mock-up page, not objected to |
| Label "▶ Trailer", no ↗; T plays it while the drawer is open (no modifier, not while typing); Esc closes the trailer and leaves the drawer; a second Esc closes the drawer; ↑ ↓ do nothing while the trailer is up; the drawer's hint reads `↑ ↓ previous / next film · T trailer` | agent default, shown in the mock-up and named on its page |
| The caption under the player: `Title (year) — trailer name · YouTube` or `— Apple's store preview`; a `YouTube · Apple` switch when the film holds both; the Apple window is narrower (960 px cap against 1280) | agent default, shown in the mock-up |
| Pick order: Trailer before Teaser; English or no-language before the film's original language, no third language ever; `official` first; then larger `size`; at most three YouTube videos kept | agent default |
| Trailers are looked up AHEAD of time and stored; the link exists only when a stored trailer does | agent default, named on the mock-up page |

**Design (agent defaults, not visible)**

- **Migration 028** — `film_trailer (film_id INTEGER PRIMARY KEY REFERENCES films(id), tmdb_id INTEGER, itunes_id TEXT, trailers TEXT NOT NULL, fetched_on TEXT NOT NULL)`. `trailers` is a JSON array, in play order, of `{"source": "youtube", "ref": <key>, "name": …}` then at most one `{"source": "apple", "ref": <previewUrl>, "name": "Apple's store preview"}`; `[]` means "looked up, nothing found". `tmdb_id` / `itunes_id` are the ids the lookup was made UNDER. One row per film, so it joins `_ONE_ROW_TABLES` and `merge_film` moves it survivor-wins (kept note: the loser's `film_id`). BEGIN/COMMIT, inserts its `schema_version` row.
- **Worklist** `Repository.films_needing_trailers(limit, refresh=False)` — live movies (`_NOT_DISPOSED`, `_IS_MOVIE`) holding a `tmdb` or an `itunes` external id (`MIN(value)` each, the drawer's own pick) whose row is missing or was made under a different tmdb or itunes id (so a re-key, or a store id gained later, re-asks by itself); `refresh=True` selects every such film. `write_trailers(film_id, tmdb_id, itunes_id, trailers, today)` replaces the row; `film_trailers(film_id) -> list[dict]`.
- **Domain** `domain/trailers.py` — `Trailer(source, ref, name)`, `pick_youtube(videos, original_language) -> list[Trailer]` (pure; the rule above; site must be `YouTube`), `APPLE_NAME`.
- **Adapters** — `TmdbClient.movie_videos(tmdb_id, languages="en,null") -> (original_language, list[dict])`: `/movie/{id}?append_to_response=videos&include_video_language=…`, so the body's `original_language` and the videos arrive together (verified live 2026-09-20). English is asked first; a FOREIGN film whose English list holds no `Trailer`-type video (a teaser does not count) is asked once more for its own language and the pick is made over both answers — so one call for most films, two for some, and any language works without a fixed list (the 0.95 draft's "one call with a fixed list" is set aside). New `infrastructure/itunes.py::ItunesLookup.previews(ids) -> dict[id, url]`: `https://itunes.apple.com/lookup?id=<≤150 ids>&country=us`, paced 3 s between calls, no account, no key; a URL is believed only when it is `https` on an `.apple.com` host (it becomes a `<video src>`). A product Apple no longer answers for simply has no preview.
- **Use case** `application/trailers.py::enrich_trailers(repo, tmdb, itunes, today, *, apply, limit, refresh, …)` on `enrich_credits`'s shape: dry run by default, batches of 150 films (one iTunes call per batch, then one paced TMDB call per film holding a tmdb id), the consecutive-failure abort, a report `scanned / with_youtube / apple_only / none / failed`. A failed iTunes batch aborts the run (nothing half-stamped). CLI: `movie-brain enrich trailers [--apply] [--limit N] [--refresh]`; never in sync. `summary()` / `status` gains `trailers` (films holding at least one).
- **Web** — `/api/films/<id>` gains detail-only `trailers` (the stored array, `[]` when no row); `/api/films` does not grow. No new route.
- **Page** — `index.html` gains `#trailer` (hidden; `position:fixed; inset:0`, above the drawer and the toast) and the hint text; `app.js` builds the link first in `p.links`, and the player: YouTube's IFrame API script is injected on the FIRST trailer open, never at page load (the dashboard must not depend on YouTube to boot; the tests route that URL to a stub), host `youtube-nocookie.com`, `autoplay=1`; Apple is a plain `<video controls autoplay playsinline>`. Fall-through: YouTube `onError`, the script failing to load, a player not READY within 8 s (the silent failure seen in rehearsal was a player that never became ready; an advert plays after ready, so it cannot trip this), or the video element's `error` → the next source; past the last one the window says `This trailer won't play here.` with the search link. `hideDrawer` also closes the trailer (Back while a trailer is up must not leave it orphaned). The trailer is never in the URL or history.
- **Tests** — unit: the pick rule (incl. a Memories of Murder-shaped list built from the real answer's shape with invented keys — story 2), the iTunes adapter, the TMDB call, repository worklist / write / merge, the use case with fakes; API: the detail key; Playwright, own module server `tests/web/test_trailer_link.py`, the seven stories under their own names with the IFrame API routed to a stub and Apple's URL routed to a request that never answers (plays) or is aborted (fails). No test reaches YouTube, Apple or TMDB.

**Added at the freeze, from the cold read-back (agent defaults unless marked):**

| Decision | Note |
|---|---|
| Esc / ↑ ↓ while a trailer is up are taken in the CAPTURE phase with `stopImmediatePropagation`, ahead of the page's other key handlers — the drawer's Esc handler closes through `history.back()`, which lands later, so the test WAITS before asserting the drawer stayed (proven by removing the line) | not visible |
| T and the link act only for the film whose details are ON SCREEN (`state.openFilm === drawnFilm`): right after ↓ the white row has moved but the new film's trailers have not arrived. Any redraw of the drawer closes an open trailer | proven by removing the guard |
| The link is a BUTTON dressed as a link — no `href` to land in the URL or to ⌘-click into a new tab | looks the same |
| Callbacks are guarded by a per-play token; a failure marks its source and moves to the first source that has NOT failed — so Apple failing after a hand-made switch goes back to a working YouTube instead of "won't play here"; the switch only offers sources that have not failed | **owner-visible, small** |
| The 8 s clock starts with the source, not the player; no YouTube API by then (or its script failing) skips EVERY YouTube trailer of the film — one wait, not three | — |
| A player that becomes READY and then shows YouTube's own "unavailable" pane WITHOUT reporting an error does not fall through; the YouTube · Apple switch is the way out | **accepted risk; name at delivery** |
| A TMDB id that no longer exists (404) is "no videos", stamped, and keeps Apple's preview; any other TMDB failure leaves the film for the next run | — |
| `--refresh` asks the longest-unasked first, so `--refresh --limit N` makes progress and an interrupted refresh carries on | — |
| A film holding two store products asks Apple about BOTH and takes the first preview found (about 180 stored ids are dead products); the row is stamped under `MIN(value)` | — |
| Null year: dropped from the caption and the search query | — |
| The grey search link shows for a film never looked up as well as for one looked up and empty — so until the first live `enrich trailers --apply` EVERY film shows it, and a film sync adds later shows it until the verb is run again | **owner-visible; name at delivery** |
| `#drawer h2` right padding 180 → 250 px for the longer hint; `test_find_my_row.py`'s pinned hint text updated | tested |
| Delivery order: migration 028 must be applied before any verb runs from this checkout, so the evidence run and your trial happen on a migrated COPY of the database; the live `migrate --apply` and `enrich trailers --apply` wait for your yes | **process** |

**Execution authority.** The builder may decide anything not visible. Not without a separate yes: `migrate --apply` and `enrich trailers --apply` on the live database, merge, push.

**What you will see at delivery.** The stories passing as tests under their own names; the lookup run for real on a migrated copy of your catalogue, with its counts; the dashboard running on that copy for you to try on your own films. Then — on your yes — the migration and the lookup on the live database, and only after your say-so the merge.
