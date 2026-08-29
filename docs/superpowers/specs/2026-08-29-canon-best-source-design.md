# Best source for a canon film — design

**Date:** 2026-08-29 · **Status:** READY TO PLAN. Every open question is closed — C1-C7 were settled with the owner on 2026-08-29 and C8-C12 later the same day, closing what the first pass left open. Next step is the writing-plans skill.

## 0. What this is

The owner is working through the film canon over about a year. For each canon film the question is **"what is the best place to watch this?"** The set-wide question — **"which subscriptions are actually earning their keep?"** — was answered once by hand in §2 and, per C8, is deliberately NOT a feature.

This grew out of a concrete failure. The `acquire` chip ("Worth buying") listed films the owner could not buy, and omitted the fact that many were streamable for free. *The Ladykillers* (#3309, Metacritic 91) sat in the queue as something to acquire while being free on Kanopy — the only US availability TMDB knows for it. A Google search found in seconds what the database could not.

## 1. Owner decisions

| # | Decision | Reasoning |
|---|---|---|
| C1 | **The canon is the top 200 by `canon_score`** | Measured: convergent canon (films on 2+ lists) effectively ends at rank 100 — 80% of ranks 1-100 are multi-list, 18% of 101-150, and 4-10% past that. Past 150 the set is one poll's opinion, weighted. 200 is the owner's chosen line, costing ~11 more films to research than 180 |
| C2 | **The monetization tier is irrelevant** | *"I don't think it makes any difference whether they're free or flat rate or have ads. I'm just interested in maximum coverage of the Canon."* `flatrate`, `free` and `ads` are all "I can watch this" |
| C3 | **Watch once cheaply, then decide whether to buy** | *"before I buy anything, it would be good to know that I can watch it once and have it included in my monthly streaming fees. Then, once I've watched it at least once, I can decide whether I want to buy it"* |
| C4 | **Buying stays worthwhile opportunistically** | A canon film at $5 is worth owning for re-viewing, independently of whether it streams |
| C5 | **Already-rated films stay in scope** | *"a lot of them I already have seen once, I just want to re-watch them."* The working filter is "not yet **bought**", not "not yet seen" — the opposite of the `acquire` chip's current gate |
| C6 | **An Apple TV application is preferred** | Streaming from a laptop works but is worse. A service with an Apple TV app beats one without, all else equal. Not a veto: *"if it's available nowhere else, I'm fine with that option"*. Enters the ranking as C10's last tiebreak |
| C7 | **Quality matters** | Resolution, bitrate, streaming quality are a ranking factor. Quantified by C9 as a per-service constant |
| C8 | **Per-film only — there is no portfolio feature** | The portfolio question, "which subscriptions earn their keep", was already answered by hand in §2, and that answer (Criterion is the only paid subscription stranding anything) is stable across a year. A few-times-a-year analysis over 200 films is a throwaway script in `scripts/discovery/`, not a feature. The per-film answer is the one that pays every day, and the one the *Ladykillers* failure in §0 actually asked for |
| C9 | **Quality is a hand-set per-service constant, not a fetched per-film fact** | No obtainable source carries per-film quality for the services doing this canon's work (§5.1). And resolution barely varies: Criterion Channel, Kanopy, Tubi, Fawesome and Plex all cap at 1080p, and HBO Max's 4K is for new originals rather than 1949 catalogue, so a fetched field would return the same answer for nearly all 139. What DOES vary is the transfer — which restoration, correct aspect ratio, real subtitles — which no API exposes and which a per-service constant captures exactly |
| C10 | **The Apple TV app is a boolean, sorted last** | C6 rules out a veto, and a weight would need a number the owner never gave. A flag ranked BELOW quality is precisely "all else equal, prefer this". Kept as its own column rather than folded into C9's constant, so that "has an app, poor transfer" stays expressible instead of the two silently cancelling |
| C11 | **The best source is computed on read, never stored** | It costs two extra keys on an ORDER BY the whole-view query already runs. Storing it would need a refresh verb, and the stored value would go stale the moment a merge re-points a listing — the argument this codebase has already settled twice, for the list tally and for a list's `size` (`.claude/rules/lists.md`: "computed, never denormalized onto `films`") |
| C12 | **No refresh-cadence change** | `meta.tmdb_providers_refreshed_at` with `REFRESH_DAYS = 7` is a STALENESS gate, not a clock, so manual syncs do the right thing unattended: sync daily and providers refresh weekly, sync monthly and they refresh on the next run. The watchlist and `FIRST_CHECK_BATCH` passes already run ahead of the gate on every run. No new verb, and never a launchd agent |

## 2. What was measured (2026-08-29, live TMDB, US region)

**The canon at 200:** 199 of 200 hold a TMDB id. The one exception is `#4763 Histoire(s) du Cinéma`, correctly keyed as a series by IMDb id alone — TMDB movie and TV ids share a namespace, so a series holds no TMDB id by policy.

**60 of the 200 are already owned**, leaving **139 to source.**

### Coverage of the full 200

| service | films | note |
|---|---|---|
| Criterion Channel | 88 (44%) | paid |
| Kanopy | 69 (34%) | free, library card |
| HBO Max | 62 (31%) | paid |
| Tubi TV | 54 (27%) | free, ads |
| Fawesome | 41 (20%) | free, ads |
| Plex Channel | 41 (20%) | |
| Hoopla | 23 (11%) | free, library card |
| TCM | 17 (8%) | |
| Amazon Prime Video | 11 (5%) | paid |
| MUBI | 0 | |

### Marginal coverage over the 139 unowned films, after the owner added Kanopy, Tubi and Fawesome

| service | covers | **adds** | running |
|---|---|---|---|
| Criterion Channel | 86 | 86 | 86 (61%) |
| Kanopy | 51 | 24 | 110 (79%) |
| Tubi TV | 39 | 6 | 116 (83%) |
| Fawesome | 30 | 3 | 119 (85%) |
| HBO Max | 54 | 2 | 121 (87%) |
| Amazon Prime Video | 8 | **0** | 121 |
| Peacock Premium | 1 | **0** | 121 |
| Apple TV+ | 0 | **0** | 121 |

### Cancellation cost — films stranded with nothing else streaming

| service | covers | stranded if cancelled |
|---|---|---|
| **Criterion Channel** | 86 | **17** |
| HBO Max | 54 | 0 |
| Amazon Prime Video | 8 | 0 |
| Peacock Premium | 1 | 0 |
| Apple TV+ | 0 | 0 |

**Criterion is the only subscription doing irreplaceable canon work** — *The Mother and the Whore*, *La Jetée*, *Pickpocket*, *Gertrud*, *Casque d'or*, *Le plaisir* and 11 others exist nowhere else streaming. Every other paid service strands nothing.

**Raw coverage overstates worth.** Sole-source counts across the whole 200 are tiny: YouTube TV 3, Fawesome 2, Disney+ 2, Kanopy 2, Criterion 0 measured that way (its 17 emerge only when the other *paid* services are also removed). Most canon films are streamable in several places, so "which service has the most" is the wrong question and "which service holds what nothing else does" is the right one.

### What remains after the owner's current stack

**18 of 139 are not streamable on anything the owner has.** Ten of those stream nowhere at all and are genuine buy-or-rent candidates; three are unavailable in the US at any price (*La Dolce Vita*, *Moonfleet*, *Chelsea Girls*) and are the only genuine physical-media cases in the canon.

## 3. The root defect this exposed

`src/movie_brain/application/availability.py` builds svod listings from `providers.flatrate` **only**, and `TmdbProviders` has no `free` or `ads` field at all — `infrastructure/tmdb.py` never reads those buckets. Separately, only **8 TMDB provider ids** are mapped in `service_provider`, so a film's availability is discarded unless it happens to be on one of those eight.

Both gaps are load-bearing. Of the 46 checkable canon films with no listings recorded, 29 have US availability TMDB knows about: 22 under `free`, 19 under `flatrate` (on unmapped providers), 15 under `ads`. **Kanopy alone accounts for 15 of them, every one under `free`.** Adding Kanopy to the registry without reading `free` would have captured exactly 1.

TMDB files the same service inconsistently across buckets — Kanopy's US catalogue is 16,817 titles under `free`, 9,241 under `flatrate`, 8,141 under `ads` — so reading `free` *alongside* `flatrate` is the fix, not switching between them.

## 4. Approved shape — the data layer

- **Record every streaming provider TMDB reports** — `flatrate`, `free` and `ads` alike — as a `listings` row, auto-registering unknown providers as services with `subscribed = 0`.
- **`subscribed` then decides everything downstream**: what suppresses a film from the acquisition queue, and what merely shows in the drawer. That is what the flag was always for, and it removes the need to curate a provider allow-list.
- `rent`/`buy` stay as they are: `apple-tv-store` only, since a storefront is not a subscription.
- The owner flips `subscribed = 1` for Criterion, Kanopy, Tubi and Fawesome; everything else arrives at 0.

This needs **migration 017** — the first schema write since v16 — for the new `movie_service` and `service_provider` rows plus §5's two new `movie_service` columns, and two code changes: `TmdbProviders` gains `free` and `ads` tuples, and the write path unions them with `flatrate`.

**One consequence the plan must carry.** Widening the buckets changes what gets WRITTEN, not what gets READ, and `refresh_providers` (`application/availability.py`) re-reads a film only on the watchlist pass, the `FIRST_CHECK_BATCH` pass, or a full pass after the weekly stamp expires. So the new `free`/`ads` listings for films already checked arrive up to a week after the code lands. Deleting the `tmdb_providers_refreshed_at` meta row forces the next sync's full pass (~4,600 TMDB calls) to pick them up at once. That is a step in the plan, not a design change.

## 5. The ranking — the per-film answer

`_SERVICES_SQL` (`infrastructure/database.py`) already fetches every film's services in ONE query for the whole view, ordered `s.subscribed DESC, s.kind DESC, s.name`. **The best source for a film is the first entry of its ranked svod set** — the whole feature is that ORDER BY's keys, which is what makes C11 (computed, never stored) cost nothing. Two things have to be right: which keys sort the set (the table below) and what goes into the set (the Criterion paragraph after it).

| # | key | decision it serves | source |
|---|---|---|---|
| 1 | `s.subscribed DESC` | C3 — watch it once on something already paid for | existing column |
| 2 | `s.quality DESC` | C7 via C9 — the hand-set per-service constant | **new column, migration 017** |
| 3 | `s.has_apple_app DESC` | C6 via C10 — tiebreak only, never a veto | **new column, migration 017** |
| 4 | `s.name` | stable ordering | existing column |

**Criterion is not in `services`, and the ranking must not lose it.** `_SERVICES_SQL` carries `WHERE l.source != 'criterion'`, because the Criterion listing reaches the read model through `_VIEW_SQL`'s own LEFT JOIN and surfaces as `FilmView.criterion` / `FilmView.departed` rather than as a `services` entry — which is also why the `acquire` chip needs a separate Criterion clause. Criterion covers 88 of the canon's 200, so a ranking blind to it answers the wrong question for 44% of the set. The ranking's input is therefore **the film's svod `services` entries PLUS a synthetic `criterion` entry when the film holds a CURRENT Criterion listing** (`criterion AND NOT departed`). No new data is needed: `movie_service` already holds the `criterion` row (slug `criterion`, `subscribed = 1`), so it carries `quality` and `has_apple_app` exactly like every other service and sorts on the same four keys.

The assembly happens at the ranking site, and `_SERVICES_SQL`'s `!= 'criterion'` exclusion is deliberately left alone: removing it would fan Criterion into the drawer's "Also streaming on:" row, into the `reachable` scope's service test and into the `acquire` chip's gate all at once, for no gain the synthetic entry does not already give. If the plan finds that assembly awkward in practice, unifying the two is a follow-up with its own measurement, not a silent widening of a query three features read.

**The dropped key is the point.** `s.kind DESC` leaves the svod ranking entirely, because C2 says `flatrate`, `free` and `ads` all mean "I can watch this" — a free-with-ads service that carries a better transfer must be allowed to win. `kind` keeps its other job unchanged: splitting the drawer's "Also streaming on:" (svod) from "Buy on:" (store), which is a display split and not a ranking.

Both new columns follow `film_list.trust`'s precedent exactly (migration 016, `.claude/rules/lists.md`): `quality INTEGER NOT NULL DEFAULT 1` and `has_apple_app INTEGER NOT NULL DEFAULT 0`, written by ONE verb and by nothing else — `movie-brain services quality SLUG [N]` and `movie-brain services apple SLUG [0|1]`, with a bare `movie-brain services` listing the registry. As with `upsert_film_list`, the registry's own writers must name neither column in their `INSERT` column list or their `ON CONFLICT DO UPDATE SET` clause, so §4's provider auto-registration — which will run on every sync, for every newly seen provider — can never reset a value the owner has set. With every service at its default the ordering is today's plus a tiebreak: the feature ships inert and diverges only once the owner expresses an opinion.

The winner needs no prose explanation attached to it. The ordering IS the reason, and the drawer badges the first entry; inventing a per-film sentence would be precision neither C6 nor C7 asked for.

### 5.1 Quality sources evaluated (2026-08-29) — and why C9 rejects all of them

| source | per-film quality? | covers the services that do this canon's work? | cost |
|---|---|---|---|
| **TMDB** (in use today) | No — provider id, name, logo and display priority only | Yes | free |
| JustWatch partner API | Yes — `presentation_type`, documented as SD/HD | Yes | B2B contract, no public pricing, partner token required |
| JustWatch GraphQL (unofficial) | Yes, including 4K | Yes — TMDB's provider data IS JustWatch data | reverse-engineered, undocumented, breaks without notice, outside JustWatch's licensed terms |
| Streaming Availability API (movieofthenight) | Yes — SD/HD/UHD/QHD | **No** — 20 US services; Kanopy, Fawesome, Hoopla and Plex are all absent, and Kanopy alone covers 69 of the 200 and adds 24 to the unowned 139, second only to Criterion | free tier 1,000 req/month |
| Watchmode | Unconfirmed — a per-source format field could not be verified from the published documentation | Yes — Kanopy, Hoopla, Tubi, Plex and Fawesome are all indexed | free tier 2,500 req/month, non-commercial, attribution required |
| the providers' own APIs | None public for Criterion, Kanopy, Tubi or Fawesome | — | — |

Two of these would work mechanically — the unofficial JustWatch endpoint and possibly Watchmode. C9 still rejects them, on the C8 principle that the cheapest thing that answers the question wins: both add a second availability authority to reconcile against `listings`, and both would return the same 1080p for nearly every row in the 139.


## 6. What this replaces

The `acquire` chip's gate is wrong in two ways this design corrects: it excludes rated films (C5 says they belong), and it calls itself "Worth buying" while checking nothing about buyability. The owner has also reversed **D1** of the on-sale design (*"don't show movies to buy that are available on the streaming services I subscribe to"*) in favour of showing them with a badge — measured at 480 candidates rather than 263, 217 of them badged.

## 7. Out of scope

Non-US regions · rental prices · the CheapCharts price watchlist (deferred, on-sale design §6) · any change to `canon_score` itself · BFI Player, which TMDB's US region knows only as an Amazon Channel (2 canon films) despite the owner holding a subscription · a portfolio / coverage-per-dollar feature of any kind (C8) — §2's tables are the answer, and re-deriving them is a throwaway script in `scripts/discovery/`, never a verb · any per-film quality lookup against a second availability source (C9, §5.1).

## 8. Gates

`uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (**baseline n=573 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance` (the apple review ceiling is 6.0; see the on-sale design for why).
