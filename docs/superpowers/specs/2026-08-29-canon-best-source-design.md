# Best source for a canon film — design

**Date:** 2026-08-29 · **Status:** DESIGNED IN PART. Sections 1-5 record decisions and measurements the owner and controller made together; §7 lists what is still open. Not ready to plan until §7 is closed.

## 0. What this is

The owner is working through the film canon over about a year. For each canon film the question is **"what is the best place to watch this?"** — and, over the whole set, **"which subscriptions are actually earning their keep?"**

This grew out of a concrete failure. The `acquire` chip ("Worth buying") listed films the owner could not buy, and omitted the fact that many were streamable for free. *The Ladykillers* (#3309, Metacritic 91) sat in the queue as something to acquire while being free on Kanopy — the only US availability TMDB knows for it. A Google search found in seconds what the database could not.

## 1. Owner decisions

| # | Decision | Reasoning |
|---|---|---|
| C1 | **The canon is the top 200 by `canon_score`** | Measured: convergent canon (films on 2+ lists) effectively ends at rank 100 — 80% of ranks 1-100 are multi-list, 18% of 101-150, and 4-10% past that. Past 150 the set is one poll's opinion, weighted. 200 is the owner's chosen line, costing ~11 more films to research than 180 |
| C2 | **The monetization tier is irrelevant** | *"I don't think it makes any difference whether they're free or flat rate or have ads. I'm just interested in maximum coverage of the Canon."* `flatrate`, `free` and `ads` are all "I can watch this" |
| C3 | **Watch once cheaply, then decide whether to buy** | *"before I buy anything, it would be good to know that I can watch it once and have it included in my monthly streaming fees. Then, once I've watched it at least once, I can decide whether I want to buy it"* |
| C4 | **Buying stays worthwhile opportunistically** | A canon film at $5 is worth owning for re-viewing, independently of whether it streams |
| C5 | **Already-rated films stay in scope** | *"a lot of them I already have seen once, I just want to re-watch them."* The working filter is "not yet **bought**", not "not yet seen" — the opposite of the `acquire` chip's current gate |
| C6 | **An Apple TV application is preferred** | Streaming from a laptop works but is worse. A service with an Apple TV app beats one without, all else equal. Not a veto: *"if it's available nowhere else, I'm fine with that option"* |
| C7 | **Quality matters** | Resolution, bitrate, streaming quality are a ranking factor. NOT yet quantified — see §7 |

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

## 4. Proposed shape (not yet approved)

- **Record every streaming provider TMDB reports** — `flatrate`, `free` and `ads` alike — as a `listings` row, auto-registering unknown providers as services with `subscribed = 0`.
- **`subscribed` then decides everything downstream**: what suppresses a film from the acquisition queue, and what merely shows in the drawer. That is what the flag was always for, and it removes the need to curate a provider allow-list.
- `rent`/`buy` stay as they are: `apple-tv-store` only, since a storefront is not a subscription.
- The owner flips `subscribed = 1` for Criterion, Kanopy, Tubi and Fawesome; everything else arrives at 0.

This needs **migration 017** — the first schema write since v16 — for the new `movie_service` and `service_provider` rows, plus two code changes: `TmdbProviders` gains `free` and `ads` tuples, and the write path unions them with `flatrate`.

## 5. What this replaces

The `acquire` chip's gate is wrong in two ways this design corrects: it excludes rated films (C5 says they belong), and it calls itself "Worth buying" while checking nothing about buyability. The owner has also reversed **D1** of the on-sale design (*"don't show movies to buy that are available on the streaming services I subscribe to"*) in favour of showing them with a badge — measured at 480 candidates rather than 263, 217 of them badged.

## 6. Out of scope

Non-US regions · rental prices · the CheapCharts price watchlist (deferred, on-sale design §6) · any change to `canon_score` itself · BFI Player, which TMDB's US region knows only as an Amazon Channel (2 canon films) despite the owner holding a subscription.

## 7. Still open — this spec is not ready to plan until these are settled

1. **Per-film answer, portfolio answer, or both?** The controller asked and the conversation moved to data before it was answered. "Best source for *this* film" and "which subscriptions earn their keep" share data but are different features, and "best" means different things in each: a single winner versus coverage per dollar.
2. **How is quality (C7) actually measured?** TMDB's provider data carries no resolution or bitrate. There may be no machine-readable source, in which case quality becomes a per-service constant the owner sets by hand rather than a per-film fact.
3. **How does the Apple TV app preference (C6) enter the ranking** — a tiebreaker, a weight, or a per-service flag the owner maintains?
4. **Does a "best source" get stored per film, or computed on read?** Stored means staleness and a refresh verb; computed means a provider lookup per film per view.
5. **What is the refresh cadence** for provider data, given syncs are manual by choice?

## 8. Gates

`uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (**baseline n=573 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance` (the apple review ceiling is 6.0; see the on-sale design for why).
