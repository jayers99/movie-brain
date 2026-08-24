# Feature seed: Multiple Movie Services

**Status: discovery.** Nothing here is committed work — this collects the vision, known facts,
and every unanswered question / spike ticket needed to take movie-brain from a Criterion-only
app to n streaming services. Absorbs backlog items 1 and 2 from [backlog.md](backlog.md).

## Vision

- Support **n movie services** — Apple TV+, iTunes, Max, Peacock, Prime Video, Criterion, plus
  candidates **BFI Player (British Film Institute — used it before, good catalog)** and
  **MUBI** — and whatever comes next; not just the Criterion Channel.
- One movie database; a **services table**; a **join of movie ↔ service availability** so the
  app can say which services a film is on and link to each.
- Target catalog size is roughly what Metacritic's browse returns for my services today:
  **~9,700 films**.
- Ownership matters: iTunes **purchases** are films I own — the app should be able to filter
  streaming lists down to films I *don't* already own.
- Possible bonus: keep **My Ratings in sync with my Metacritic account** (they have a
  My Ratings section), so ratings live in both places.
- **Watchlist availability alerts (added 2026-08-24 — important):** I keep a watchlist of
  ~50 films (a subset of the full database). When a watchlist film **becomes available** on
  a streaming service, alert me — rare films surface for two weeks or a month and vanish;
  the whole point is catching those brief windows. Requires: a watchlist entity, availability
  *transition* detection in the sync (newly-appeared, not just currently-on), and an alert
  channel (macOS notification from the nightly sync + a "newly available" surface in the
  dashboard; spec decides the mix).

## Pivot (2026-08-23): score-first, all services

Supersedes the network-filtered crawl as the leading approach:

1. **One-shot ingest of all highly-rated Metacritic movies** above a score threshold —
   probably **metascore ≥ 80** — with the threshold as the knob controlling database size.
   No network filter: this is the universe of good movies, not just my services.
2. Each Metacritic title page has an **"available to watch" block listing the services**
   carrying it. Ingest *all* of those services per movie — including ones I don't subscribe to.
3. App logic then splits availability into **my services vs. others**, and can rank
   unsubscribed services by **how many movies-I-want-to-see they carry** — turning the app
   into a tool for deciding **which streaming service to subscribe to next**.

New questions this raises (also folded into the spike lists below):

- [x] ~~Does the browse URL take a minimum-metascore filter?~~ **Probed 2026-08-23: no** —
      filters are year / streaming service / release type / genre only. But the browse
      **sorts by Metascore descending** (unfiltered total: 17,313 movies), so a threshold
      needs no filter param: **walk the sorted pages and stop when scores drop below 80.**
- [x] ~~Is the title-page availability block JustWatch-powered?~~ **Probed 2026-08-23: yes** —
      the "Where to Watch" block is server-rendered *with explicit JustWatch attribution*
      (links to justwatch.com, region-aware, possibly truncated behind "All Watch Options").
      So Metacritic's availability data **is** JustWatch data — the same source TMDB watch
      providers serves as a real API. Leading design: **browse walk for titles + scores;
      TMDB watch providers (by IMDb/TMDB id) for full availability** — no per-title
      Metacritic scraping needed.
- [x] ~~How many titles clear metascore 80?~~ **Measured 2026-08-24 by sampling the sorted
      walk** (24 titles/page, 722 pages total): page 2 → 97–98, page 42 → 85, page 75 → 81
      (ranks ~1,780–1,800), page 92 → 79 (ranks 2,185–2,208), page 125 → 76. The 80/79
      boundary falls around page ~83, so **≈2,000 titles score ≥ 80** (and ≥ 76 ≈ 3,000 — the
      threshold knob is well-behaved).
- [x] ~~Verify TMDB watch-provider coverage.~~ **Verified 2026-08-24** on the provider
      registry + 10 sample films. All my services are distinct US providers with stable ids:
      Criterion Channel 258 · Apple TV (=Apple TV+) 350 · Apple TV Store (=iTunes rent/buy) 2
      · HBO Max 1899 · Peacock Premium 386 / Plus 387 · Prime Video 9 · MUBI 11. Per-film data
      is current and splits cleanly into `flatrate` (streaming) vs `rent`/`buy` — iTunes
      purchasability comes free via Apple TV Store in the buy arrays. Sample sanity: Tokyo
      Story/Seven Samurai → Criterion + HBO Max; Oppenheimer → Peacock; CODA → Apple TV+;
      Decision to Leave → MUBI; Manchester by the Sea → Prime. **Two design consequences:**
      (1) one logical service = **several TMDB provider ids** (HBO Max also appears as
      "HBO Max Amazon Channel" 1825, MUBI as "MUBI Amazon Channel" 201, …) → the services
      table needs a provider-id grouping; (2) **BFI in the US is "BFI Player Classics"** — a real
      US-only SVOD ($5.99/mo, Roku 2019, Apple TV channel + app 2020, bfiplayerclassics.com;
      the service I've subscribed to via Apple TV) — but TMDB indexes it only through its
      Amazon storefront, "BFI Player Amazon Channel" (287); the GB "BFI Player" (224) is a
      separate service. So: provider labels ≠ service names, one storefront id proxies the
      whole catalog, and region handling is a real column, not a constant. Minor caveat: sources can drift
      (The Conformist shows Criterion on Metacritic's page but only Kino on TMDB today) —
      availability is a snapshot, refreshed by sync, not a fact.
- [x] **Provider-seeding decisions (2026-08-23, settled in the Phase 1 spec):**
      (1) **Amazon channel ids are excluded** (HBO Max 1825, MUBI 201, BFI Player 287) —
      Amazon-billed storefronts are not how he subscribes; accepted consequence: TMDB
      availability for BFI Player Classics is knowingly invisible (287 was its only US id).
      (2) **svod availability = TMDB `flatrate` only**; `rent`/`buy` arrays are read only
      for store-kind services (Apple TV Store, provider 2 = the iTunes movie store, kept as
      the future owned-films hook). Purchasable-from-Amazon is never availability.
- [ ] Data model: `movie_service` needs a **`subscribed` flag** (and the ownership question
      from the working sketch still stands).
- [ ] Define "**movies I want to see**" for the ranking — above-threshold and unrated-by-me?
      Excluding owned? Excluding not-interested (rating 0)?
- [ ] Ranking/UI: a "services worth subscribing to" view — count of wanted films per
      unsubscribed service, with the film lists behind it.

## Scrape contract — one-and-done (drafted 2026-08-24)

Goal: **never scrape Metacritic again.** Design the single friendly crawl so everything worth
having is captured and archived on the first pass.

**Scope (revised 2026-08-24): cap the walk at ~300 pages ≈ 7,200 titles.** Even a polite
scraper may get shut off before long — Metacritic has no reason to welcome a full-catalog
walk — so don't be greedy: 300 pages (~15 minutes at one request per 3 s) lands 5–8 thousand
titles, comfortably past the ~2,000 that clear metascore 80 (score floor at page 300 is
unmeasured; extrapolating from page 125 ≈ 76, likely upper-60s). Make the page cap a
**parameter with checkpoint/resume**, so a mid-walk block loses nothing and a later run can
extend the archive if they never object. The score threshold stays a query-time filter within
whatever the archive holds.

**Archive raw, parse later.** Store each fetched page (raw HTML or extracted JSONL) with its
fetch timestamp and page number. If parsing needs a fix next month, we re-parse the archive —
no re-fetch.

**Fields per title card** (verified present in the card markup 2026-08-24):

- title, release date (year), **metascore**
- **slug/URL** (e.g. `/movie/seven-samurai-1954/`) — the identity key for any future
  Metacritic need (ratings sync, detail lookups) and for title+year disambiguation
- content rating (R / TV-14 …), short description, "must-see" badge, poster image URL
- rank at crawl time (position in the sorted walk)

**Not on the cards** — do not plan to get these from the crawl: user score, runtime, genres.
TMDB/OMDb supply those downstream.

**Crawl behavior:** honest User-Agent, ~1 request / 2–3 s, resumable via page-number
checkpoint, bounded retries, stop-and-keep-progress on repeated failures (same tripwire
philosophy as the Criterion sync).

**Post-crawl verification:** ~24 titles per fetched page up to the cap; scores monotonically
non-increasing through the walk; no duplicate slugs; spot-check a few known titles.

**The real work is after the crawl:** map each title to `film_key(title, year)` and to
TMDB/IMDb ids (via TMDB search / OMDb) so availability and ratings join cleanly — the
match-rate question already tracked in the spikes below.

## Implementation phases (replanned 2026-08-24 — strangle pattern)

Each phase is sized for **one superpowers spec→implement run** (brainstorm → spec → execute).
Strategy: **strangle, don't big-bang** — redesign the database first, prove the model on the
data we already have (Criterion's ~3,000), then grow the Metacritic side through a
**configurable top-N dial** instead of a one-shot 10K ingestion. Rationale: if the model is
wrong we find out at N=100, not after querying 10,000 records we'd have to re-query.

**Identity decision (2026-08-24):** movies get **our own generated GUID** as the primary
identity — guaranteed unique, guaranteed ours. Each service's native id (Metacritic slug,
TMDB id, IMDb id, Criterion URL, …) hangs off it one-to-many in an external-ids table.
`film_key(title, year)` is demoted from *the* identity to a matching aid.

**Two Metacritic query modes** (same adapter, different drivers):

- **Mode A — enrich what we have:** find the Metacritic record for each film already in the
  database (score, slug, their id). The strangle-pattern first step, run against Criterion's
  3,000.
- **Mode B — top-N discovery:** "give me the top N Metacritic-scored movies", with N a
  **config parameter — initially 100**, then dialed to 1,000, eventually ~10,000, each bump
  just a bigger walk on the next sync.

A third acquisition pattern, distinct from both: **full-service import** — a paid,
small-catalog service gets its *entire* catalog imported ("we're paying for it, import all
of it"), the way Criterion works today. Films arrive individually, not by rating rank.

| # | Phase | Depends on | Disruption risk |
|---|-------|-----------|-----------------|
| 1 | Schema redesign: GUID identity + services model — **done** | — | live schema — the careful one |
| 2 | Metacritic adapter, Mode A (enrich Criterion) — **done** | 1 | low (additive columns/joins) |
| 3 | TMDB availability adapter — **done** | 1 | medium (sync flow) |
| 4 | Watchlist + availability alerts — **done** | 3 | low |
| 5 | Metacritic Mode B: top-N dial (start N=100) — **done** | 2 | low at N=100 — grows with the dial |
| 6 | Full-service import pattern | 5 | low (Criterion is the precedent) |
| 7 | Subscription advisor | 5 | low (read-only view) |
| 8 | DB maintenance suite | late by design | none until used |

1. **Done (2026-08-23).** **Schema redesign — the strangle root** (zero visible change). GUID movie id;
   external-ids table (movie ↔ per-service ids, one-to-many); `movie_service` registry
   (name, slug, kind, `subscribed`, region) + provider-id grouping; availability join;
   **remove `purge_departed`** (immutability decision); migrate the existing Criterion data
   into the new shape. Done when: migration applied, all tests green, dashboard identical.
2. **Done (2026-08-23).** **Metacritic adapter — Mode A.** Enrich every film currently in the DB (=Criterion) with
   its Metacritic record; the movie↔Metacritic join goes live; metascores become
   first-class instead of OMDb-payload backfill. Landed as an incremental dial: `metacritic crawl --pages N` (10 first, extend by re-running with a bigger cap), offline `match`, scraped-first score with OMDb fallback, anomalies in `match_review`.
3. **Done (2026-08-23).** **TMDB availability adapter.** Promoted the spike matcher (98% rules) into
   `infrastructure/tmdb.py`; `tmdb` cache table on the `omdb` pattern; watch-providers for
   my services; sync step with its own tripwires (one-shot match, weekly refresh gated by
   meta `tmdb_providers_refreshed_at`); drawer shows "Also streaming on: …".
   Done when: cross-service availability visible for Criterion films.
4. **Done (2026-08-23).** **Watchlist + availability alerts** (the brief-window catcher). Watchlist entity + drawer
   toggle; sync-time **transition detection** (availability *appearing*, not just existing);
   alert channel (macOS notification from the nightly sync + a "newly available" dashboard
   surface — spec decides the mix). Landed as: append-only `availability_transitions`
   recorded at listing-write time against the pre-batch currency frontier, a nightly ~50-film
   watchlist provider pass ahead of the weekly full refresh, one summary macOS notification
   per sync, and dashboard "New arrivals"/"Watchlist" chips + drawer star toggle and "New on"
   line.
5. **Done (2026-08-23).** **Metacritic Mode B — the top-N dial.** Crawler per the scrape contract (checkpoint/
   resume, raw archive, staging) with **N as config, set to 100**; staging → films via the
   matcher (unmatched → log for the later review queue); dashboard gains the minimum
   source-awareness to stay usable as N grows (default view = my services / Criterion
   parity). Then exercise the system and simply raise N next sync. Done when: top-100 lives
   in the app, model validated, N=1,000 is a config change not a project. Landed as: N
   resident in meta (`mc_top_n`, `metacritic dial [N]`), nightly offline promotion
   (match-first dedup guard, key/slug conflicts → `match_review`) between the Criterion walk
   and the OMDb loop, a criterion/all dashboard scope toggle over a source-agnostic
   `_VIEW_SQL`, quiet first-ever TMDB provider checks (no false "new arrival"), and the OMDb
   loop widened to cover discovery films.
6. **Full-service import pattern.** Generalize "import a service's whole catalog" beyond
   Criterion (future: MUBI, BFI Player Classics — small paid catalogs worth having whole).
   Done when: adding such a service is configuration + an adapter, not a redesign.
7. **Subscription advisor.** Define "movies I want to see" (watchlist as the sharpest core),
   rank unsubscribed services by wanted-films carried. Done when: the app answers "what
   should I subscribe to next?"
8. **DB maintenance suite — late by design (his call).** The identity-disposition table
   (tombstones + merge aliases), dedup/merge verbs, and the match-review queue UI. Until
   this phase, the standing rules still hold: collectors never delete, unmatched ids are
   logged, and any manual removal waits for tombstone support so nothing resurrects.

**Parallel tracks, not on this critical path** (each its own future spec run): practice-loop
notes + rubric (independent of services; any time), MCP server (independent driving adapter),
power search (wants Phase 3's structured metadata; port from yt-brain), iTunes ownership
(blocked on the export spike), ratings sync (TMDB/Metacritic; latest of all).

## Facts collected so far

- Browse URL for my services (9,703 movies as of 2026-08-23):
  <https://www.metacritic.com/browse/movie/?network=apple-tv-plus&network=criterion-channel&network=itunes&network=max&network=peacock&network=prime-video>
- The `network` query param repeats per service; slugs seen: `apple-tv-plus`,
  `criterion-channel`, `itunes`, `max`, `peacock`, `prime-video`.
- A first probe of that page (2026-08-23) found it **server-rendered** (movies embedded in the
  HTML, not a JS shell), publicly accessible with **no visible bot wall or login**, numbered
  **pagination of ~405 pages** (~24 titles/page), each entry carrying title, year, and
  metascore. No JSON API endpoints visible in the markup. Needs re-verification from a real
  scraper's perspective (headers, rate limits, consistency).
- I have a Metacritic account, and Metacritic already has per-title user ratings ("My Ratings").
- **TMDB credentials live at** `~/.config/movie-brain/tmdb-read-token.txt` (v4 bearer, use this)
  and `tmdb-api-key.txt` (v3) — both verified working 2026-08-24. TMDB accounts can also store
  **my own movie ratings**, a second ratings-sync target alongside Metacritic My Ratings.
- Current schema is closer to this than it looks: `listings` already keys on
  `(film_id, source)` with per-source `url`, `first_seen`/`last_seen`, `leaving_date` — the
  availability join in embryo. `criterion` is just the only `source` value so far, and
  CLAUDE.md already anticipated "Apple Movies" as a future source.

## API landscape (researched 2026-08-23)

Guiding preference: **API-centric wherever possible; HTML scraping only as a fallback** — keep
the complication at the provider boundary low.

| Provider | Official API? | Verdict for us |
| --- | --- | --- |
| **Metacritic** | Paid + approval-gated only, via [Fabric Origin](https://developer.iva-api.com/apis/metacritic) ("Origin Nexus" — IVA's licensing platform); no free official API. **No public pricing** — contact-sales/demo only (checked 2026-08-24); Metacritic data excluded from their free trial; API is per-title review lookups on their own movie IDs, no bulk-catalog endpoint | **Decision (2026-08-24): not pursuing the paid API** — too much friction for a personal app; 17,313 titles ≈ **~722 browse pages** (24/page), one polite one-shot crawl. Browse pages are server-rendered and scrapeable (our probe); [Apify scraper](https://apify.com/automation-lab/metacritic-scraper/api) and OSS scrapers exist; OMDb already gives us the Metascore per title |
| **iTunes (purchasable + prices)** | Yes — free official [iTunes Search API](https://performance-partners.apple.com/search-api) (`itunes.apple.com/search` and [`/lookup`](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/LookupExamples.html)), JSON with prices | Best-in-class option; covers purchasable + price. **Purchase history (owned) is NOT exposed** — owned-films spike stays open |
| **Apple TV+ / Max / Peacock / Prime catalogs** | None public, per service | Use an **aggregator** (below) instead of four scrapers |
| **MUBI / BFI Player** | No official APIs (MUBI has only [community packages](https://github.com/jdennes/mubi)); both are tracked by [JustWatch](https://www.justwatch.com/uk/provider/mubi) ([BFI Player too](https://www.justwatch.com/uk/provider/bfi-player)) and thus TMDB watch providers | Same aggregator path as the big four. Spike: are they networks on Metacritic's browse filter, and does region matter (both skew UK)? |
| **Aggregators** | [TMDB](https://developer.themoviedb.org/docs/faq) — free non-commercial, per-region watch providers powered by JustWatch, attribution required; [Watchmode](https://api.watchmode.com/) — paid, deep links, 200+ services; [Streaming Availability API](https://www.movieofthenight.com/about/api) — RapidAPI, IMDb/TMDB id mapping; JustWatch itself has no official public API | **TMDB watch-providers looks like the sweet spot** for a personal app: free, one API for all four services, ids map to IMDb |
| **IMDb** | Free daily [TSV datasets](https://developer.imdb.com/documentation/); official GraphQL API is paid via AWS Data Exchange | We already get IMDb ratings via OMDb; datasets are a bulk fallback |
| **Rotten Tomatoes** | Paid + approval via [Fabric Origin](https://knowledgebase.fabricdata.com/origin/apis-all/rotten-tomatoes-api-docs) only | Keep sourcing RT from OMDb |
| **CheapCharts** | No public API found — [app](http://app.cheapcharts.com/) has [price alerts](https://www.cheapcharts.com/blog/did-you-know-4/) but no developer docs | Spike: contact support / inspect the app's traffic; may end up a deep-link-only integration |

Emerging picture: **three integration tiers** — (1) real APIs: iTunes Search, TMDB watch
providers, OMDb (already built); (2) polite scraping: Metacritic browse; (3) unknown/contact:
CheapCharts, Metacritic My Ratings sync.

## Service layer direction

The app is already hexagonal, so this feature is more of the same, harder: **one port per
domain concept** (catalog source, price source, ratings sync — spoken in domain language:
films, availability, offers), with **one adapter per provider** in `infrastructure/`
(`criterion.py` is the template). Whether a provider is a JSON API or a scraper stays an
adapter detail the application layer never sees.

## Discovery questions / spike tickets

### Metacritic integration (the big research project)

- [ ] **Spike: find the best integration method.** Official API? Partner API? MCP server? Or
      scraping the browse pages? Inventory what exists and pick one.
- [ ] What do the browse pages actually expose per title — title, year, metascore, network
      badges? Does an entry list *which* of my networks carries it, or must that be derived
      per-network (one crawl per service vs. one combined crawl)?
- [ ] Scrape mechanics: rate limits, robots.txt, ToS position on scraping, stability of the
      HTML, and whether ~405 pages can be walked politely on a daily/weekly schedule.
- [ ] Does the browse filter cover *all* titles on a service or only ones with a metascore?
      (If metascore-less films are excluded, Metacritic alone undercounts catalogs.)
- [ ] Authenticated surface: what does logging in unlock? Is My Ratings readable/writable via
      any endpoint?
- [ ] **Spike: ratings sync design.** One-way (push my 0–10 scores to Metacritic), one-way
      (pull), or two-way with conflict rules? Do their user scores use the same 0–10 scale?
- [x] ~~Title matching: can Metacritic entries be matched reliably?~~ **Measured 2026-08-24**
      (96-title sample across score bands 100→77, naive TMDB search + year ±1):
      **73% top-1, 8% top-3, 19% miss.** The misses are almost all one fixable class —
      **Metacritic uses the US release/re-release year, TMDB the original year** (Tokyo Story
      1972-vs-1953, Playtime 1973-vs-1967, Army of Shadows 2006-vs-1969) — plus title
      annotations to strip ("Dekalog (1988)", "The Leopard (re-release)"), 1–2-year US-lag
      drift (Arrietty 2012-vs-2010), and punctuation (Forbidden Lie$). With parenthetical
      stripping + wider year tolerance + exact-title preference, expect **~95%+**; the
      residue is a small human-review queue. Spike script:
      `scripts/discovery/match_spike2.py` (kept in-repo; fold into the adapter when built).
- [x] ~~Re-run the matching spike with normalization fixes.~~ **Confirmed 2026-08-24: 98%**
      (94/96; 93 exact-title, 1 near-year fallback). Winning rules: strip
      `(re-release)`/`(NNNN)` annotations · punctuation/case-insensitive title compare
      (`Lie$`→`lies`) · accept exact-title results whose **original year ≤ MC year + 2**
      (MC stamps US re-release years). The two residuals both have known fixes: *Dekalog* is
      a TV series on TMDB (needs a TV/multi-search fallback) and *Intolerance* carries a
      subtitle on TMDB (needs prefix-tolerant compare). Verdict: **matching is solved** —
      normalization function + tiny review queue; the winning matcher and the watch-providers
      probe are preserved at `scripts/discovery/` (fold into the real adapters when built).
- [ ] Do Metacritic pages link out to the streaming services (deep links we could store as the
      per-service `url`), or do we need each service's own catalog/API for links?

### Data model

**Working sketch (2026-08-23):** a `movie_service` table with a many-to-many join to movies
(the current `listings(film_id, source)` is this join in embryo, with `source` as a string
instead of a foreign key). Ownership proposal: iTunes gets **two rows** — "iTunes (available
for purchase)" and "iTunes (owned)" — so owned films are marked by membership in the owned
pseudo-service, and every query/filter works the same way as any other service.

Alternative to weigh in the same spike: keep one row per real service and put the semantics on
the **join edge** instead — `availability(film_id, service_id, kind)` with kind ∈ streaming /
purchasable / owned. Trade-off: the two-row version needs zero new columns and "owned" is just
another chip; the kind-on-edge version keeps a service's identity in one row (one URL/branding/
adapter), lets ownership extend to other stores later (e.g. Prime purchases) without twin rows,
and keeps "which services stream this?" queries from having to exclude owned-rows.

- [x] ~~**Spike: pick the ownership model** — pseudo-service rows vs. kind-on-the-join (or a
      separate `owned` table). Decide with the iTunes-export spike in hand.~~
      **Decision (2026-08-23): dedicated `owned` table (watchlist pattern), AppleScript export
      as acquisition (870 cloud purchases visible); privacy-portal export remains the
      completeness backstop.**
- [ ] Formalize `movie_service`: what does a service row carry (name, slug, kind, base URL)?
      Does `listings.source` become a foreign key to it?
- [x] ~~Retention rules per service?~~ **Decision (2026-08-24): the film database is
      immutable.** A movie is a movie, forever — `purge_departed` is removed entirely; films
      are append-only (dedup aside). What churns is **availability**: per-service
      `first_seen`/`last_seen` keeps moving, and "departed"/"gone" becomes a pure display
      state, never a deletion. This also dissolves the old ingestion landmine (one-shot
      Metacritic films can never be purge-eaten).

**Data-hygiene principles (2026-08-24)** — how immutability coexists with cleanup:

- **Collectors never delete.** Sync/crawl/ingest processes are append-and-update only, full
  stop. Deletion authority lives nowhere in the automated pipeline.
- **Dedup, cleaning, and repair are a separate maintenance surface** — deliberate,
  human-driven verbs (CLI commands and/or a review UI), never a side effect of syncing.
  (merge_yearless already foreshadows this: dedup pressure is real and grows at 10K films.)
- **Removals leave tombstones.** A deliberately-removed identity (film_key and/or source ids)
  is recorded in an identity-disposition table that **every ingester checks** — so a removed
  entry can't magically resurrect on the next walk.
- **Merges leave aliases.** When dedup folds two rows, the losing identity records an alias
  pointing at the survivor; incoming data for the old identity re-routes instead of
  recreating a duplicate. Tombstones and aliases are the same table family: "what happened
  to this identity."
- **Unmatched IDs go to a review queue, not the trash.** The ~2% matcher residue (and future
  match conflicts) queue for human resolution — outcome is always a match, an alias, or a
  tombstone; never silent deletion.
- **Timing (his call, 2026-08-24): the maintenance tooling comes late** (Phase 8 in the plan
  below). The principles bind from day one anyway — collectors never delete and unmatched ids
  are logged from the first adapter — but tombstone/alias/dedup *tooling* waits until the
  data is at scale; manual removals wait for tombstone support so nothing resurrects.
- [ ] `leaving_date` semantics per service — does anything besides Criterion expose leaving
      dates?
- [ ] Film identity across sources: Criterion titles vs. Metacritic titles vs. iTunes titles —
      does `film_key(title, year)` hold up, or do we need per-source alias/id columns?
- [ ] Migration path for the existing Criterion data into the generalized model.

### Sync architecture

- [ ] One adapter per service (like `infrastructure/criterion.py`) vs. one Metacritic adapter
      that covers all networks at once?
- [ ] Scheduling: the 3 AM launchd job walks Criterion in minutes; what does a ~405-page
      Metacritic walk cost, and how often should it run?
- [ ] Tripwires per source: today a catalog failure leaves the DB untouched — how does that
      work when one of n sources fails?
- [ ] OMDb load: ~6,700 new films × free-tier 1,000 lookups/day ≈ a week of backlog. Acceptable,
      or time for the paid tier?

### iTunes / owned films

- [x] ~~**Spike: how to export my iTunes/Apple TV purchase list.** Apple API? Family Sharing
      caveats? Manual export from the TV app? One-shot import vs. periodic sync?~~ **Answered
      2026-08-23: AppleScript** — `movie-brain owned import` drives the Apple TV app via
      osascript (no Apple API, no Family Sharing handling), archiving the raw export before
      parsing, one-shot per run (never in nightly sync). Sees 870 cloud purchases; the
      privacy-portal export is the completeness backstop for the rest.
- [ ] Are purchases title+year strings or Apple IDs — and how do they map to `film_key`?

### UI / product

- [ ] How does the table show services — a chip per service, a "services" column with badges,
      or filter dropdown like languages?
- [ ] Per-service links in the drawer (today there's one "Open on Criterion" link).
- [ ] An "owned" filter (hide films I own) and/or an "owned" badge.
- [ ] Does "Departed" mean "left all services" now?
- [ ] Does the metascore from Metacritic's browse replace/augment the OMDb `Metascore` (they
      should agree, but which is authoritative)?

## Open decisions to revisit after spikes

- Buy vs. build per service: Metacritic-as-aggregator (one scrape, all networks) vs. native
  per-service adapters (better links, more truth, much more work).
- Whether ratings sync is in-scope for v1 of this feature or its own follow-on.
