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
- [ ] Verify TMDB watch-provider coverage ≥ Metacritic's on a sample of titles (especially
      the "All Watch Options" tail, MUBI/BFI, and rent/buy vs. subscription splits).
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
      scratchpad `match_spike.py` (promote into the repo when the adapter is built).
- [x] ~~Re-run the matching spike with normalization fixes.~~ **Confirmed 2026-08-24: 98%**
      (94/96; 93 exact-title, 1 near-year fallback). Winning rules: strip
      `(re-release)`/`(NNNN)` annotations · punctuation/case-insensitive title compare
      (`Lie$`→`lies`) · accept exact-title results whose **original year ≤ MC year + 2**
      (MC stamps US re-release years). The two residuals both have known fixes: *Dekalog* is
      a TV series on TMDB (needs a TV/multi-search fallback) and *Intolerance* carries a
      subtitle on TMDB (needs prefix-tolerant compare). Verdict: **matching is solved** —
      normalization function + tiny review queue; scripts `match_spike.py`/`match_spike2.py`
      in the session scratchpad, promote when building the adapter.
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

- [ ] **Spike: pick the ownership model** — pseudo-service rows vs. kind-on-the-join (or a
      separate `owned` table). Decide with the iTunes-export spike in hand.
- [ ] Formalize `movie_service`: what does a service row carry (name, slug, kind, base URL)?
      Does `listings.source` become a foreign key to it?
- [ ] Retention rules per service: "rated films kept forever, unrated purged after 7 days
      absent" is Criterion-shaped. Does it generalize when a film can leave one service but
      remain on another?
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

- [ ] **Spike: how to export my iTunes/Apple TV purchase list.** Apple API? Family Sharing
      caveats? Manual export from the TV app? One-shot import vs. periodic sync?
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
