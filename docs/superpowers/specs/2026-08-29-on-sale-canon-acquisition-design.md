# On Sale — working through the canon, with price as the acquisition trigger

**Date:** 2026-08-29 · **Status:** designed with the owner across a long conversation; every decision below is theirs and recorded with its reasoning. Ready to plan.

## 0. What this actually is

Backlog item 3 reads *"CheapCharts price-watch integration — add a button on a film that adds it to my CheapCharts price watch list."* That is a smaller idea than the one this became, and building to it would have been a mistake.

The owner's actual goal, in their words: *"what I'm interested in studying is the canonical canon… after my study period it's interesting that I could watch modern films and apply the skills learned and refined taste acquired from studying the canon to those films."*

So this is **a study tool: an ordered, ranked queue of the canon films worth acquiring, with price as the trigger to acquire the next one.** The ranking is the product. The price is the smallest part.

Two earlier framings were tried and discarded, both by the owner:

- *Show the lowest price in the drawer.* Useless — *"that price comes right up when you do it"*. The labour was never looking the price up; it was the **pair** of steps: look up the floor, then hand-enter it as a watch target.
- *Replace CheapCharts' watchlist with our own alerts.* Rejected: *"I want to keep my watchlist on CheapCharts… I get a nice alert to my iPhone and it's all integrated and they make it easy for me to purchase from there."* CheapCharts stays the thing that pings the phone and takes the money.

## 1. Owner decisions (do not relitigate)

| # | Decision | Reasoning |
|---|---|---|
| D1 | **Gate:** exclude films streamable on a subscribed SVOD, owned, or already rated | *"don't show movies to buy that are available on the streaming services I subscribe to"*, and no point buying what you own or have seen |
| D2 | **Two tiers, no Metacritic term in the canon rank** | The owner's data proves Metacritic unfit for canon — see §3 |
| D3 | **Trust stays Cahiers 10 / Bergan 9 / Sight & Sound 8** | Owner trusts Moviewise's ranking over the controller's voter-count argument. Their evidence is better: they have seen the lists |
| D4 | **Target price = the exact historical low, no slack** | Measured, not assumed — see §4 |
| D5 | **Depth is a dial; 100+ entries is fine** | *"as I get more and more films watched I can tune that downward to pick up lower ranking films"* |
| D6 | **Price refresh is on demand, never scheduled** | Standing preference: syncs are run manually, deliberately. The controller repeatedly said "nightly sync" and was wrong to |
| D7 | **Correct the target price on existing watchlist entries** | Owner overrode the controller's report-only recommendation. Noted consequence: correcting a target DOWNWARD stops alerts at the higher price |
| D8 | **The watchlist itself lives on CheapCharts** | See §0 |

## 2. The gate — which films are worth buying

A film is a candidate when **all** hold:

- it is **not currently streamable** on any service where `movie_service.subscribed = 1 AND kind = 'svod'`. The `kind` test matters: `apple-tv-store` is marked subscribed but is a shop, and a shop must never suppress a film. Currency uses the existing rule — `last_seen >= tmdb_providers_refreshed_at`, or `MAX(last_seen)` for criterion.
- it is **not owned** (`owned` table)
- it is **not already rated** (`my_ratings`)
- it is not disposed
- and it is **either on at least one curated list, or scores ≥ 90 on Metacritic**

**263 candidates today.** 84 list-only, 22 both, 160 Metacritic-only.

Note the self-deepening property: rating a film removes it from the set, so the same dial reaches one film further down. The dial exists to outpace that, not to keep up with it.

## 3. The rank — two tiers, and why Metacritic is not in tier 1

**Tier 1 — the canon.** Films on at least one list, ranked by

```
canon_score = Σ over lists ( trust × (1 − (printed_rank − 1) / list_size) )
```

so #1 on a list contributes its full trust and the last entry contributes ~0. Position matters, not just membership: Cahiers #12 outweighs Sight & Sound #243. The original curated-lists spec §5.7 warned against summing ranked and unranked membership blindly; this honours it. A tied `rank_label` (`=196`) uses the printed rank, which is the poll's own judgement.

**Tier 2 — acclaimed but uncanonised.** MC ≥ 90 and on no list, ranked among themselves by score, **always below every tier-1 film**.

### Why Metacritic is excluded from tier 1, measured on this catalogue

| | |
|---|---|
| list films with **no** Metascore at all | **152 of 348 (44%)** |
| pre-1960 list films with a score | 51% |
| 1990+ list films with a score | 72% |
| of scored list films, those at 90+ | **58%** |

Three findings, each disqualifying on its own. **Coverage:** it does not have a score for nearly half the canon. **Era bias:** it covers the pre-1960 half — precisely what the owner is studying — worst. **No discrimination:** where it does score, most of the canon lands in a ten-point band, so it confirms rather than ranks.

And structurally it measures the wrong thing. Metacritic aggregates reviews at release; canon is the product of **re-evaluation**. *Vertigo* had mixed notices in 1958 and is now #2 on Sight & Sound. A Metascore is a snapshot of reception; a curated list is the verdict of history.

Excluding it also dissolves the missing-data problem: *Contempt* has no Metascore and does not need one — it is Cahiers #15.

## 4. Price data

Source: CheapCharts' own JSON API, which its web app calls and which needs **no authentication** — only a `Referer` header.

```
GET buster.cheapcharts.de/v1/DetailData.php?store=itunes&country=us&itemType=movies&idInStore=<iTunes id>
```

Relevant fields: `imdbId` (the join key to `external_ids`), `priceHd`, `priceHdIsLowest`, `priceHdEvolution` (the full history, `date:±price~…`), `iTunesUrl`, `cheapChartsProductPageUrl`.

**The historical low is computed from `priceHdEvolution`, not taken from a flag** — we then own the number and can recompute it if the format changes.

### D4's evidence — why the exact low, with no slack

Ten films' complete histories, sampled 2026-08-29:

| film | now | low | times at low | high |
|---|---|---|---|---|
| To Catch a Thief | 14.99 | **4.99** | 35 | 14.99 |
| Rear Window | 14.99 | **4.99** | 31 | 14.99 |
| The Birds | 14.99 | **4.99** | 27 | 14.99 |
| Vertigo | 4.99 | **4.99** | 26 | 14.99 |
| Strangers on a Train | 9.99 | **4.99** | 22 | 14.99 |
| North by Northwest | 12.99 | **4.99** | 20 | 16.99 |
| Marnie | 14.99 | **4.99** | 17 | 17.99 |
| Torn Curtain | 14.99 | **4.99** | 13 | 14.99 |
| Suspicion | 9.99 | **4.99** | 6 | 17.99 |
| The 39 Steps | 14.99 | **4.99** | 4 | 19.99 |

**Zero of ten had a one-off low.** $4.99 is Apple's structural sale price for catalogue titles, and these films return to it repeatedly. Slack would add noise for no gain.

### The join problem

The API is keyed by **iTunes track id**, which the catalogue does not hold. Resolution: search CheapCharts by title, then **confirm the match on the `imdbId` the API returns against our stored `imdb` id** — never on title similarity. A film whose id cannot be confirmed is reported, never guessed. Confirmed ids are cached so the lookup happens once per film.

### Storage and the dial

A new table holds, per film: the iTunes id, current price, computed historical low, whether current is at the low, the raw evolution string, and when it was checked. `movie-brain prices refresh` fetches for the top *N* candidates by rank; `movie-brain prices dial [N]` shows or sets *N*, following `metacritic dial`'s established show/set shape.

## 5. The view

The dashboard list is **quality-sorted** (tier 1 then tier 2), not filtered to on-sale. Each row shows the historical low, flags films currently at it, and carries a button to that film's CheapCharts page. An `On Sale` chip narrows to the at-the-low ones.

Two states, and the price data exists to tell them apart:

| state | meaning |
|---|---|
| current == historical low | **buy it now** |
| current > historical low | **set a watch at the low** |

## 6. The CheapCharts batch — driving the browser

The owner asked whether the watchlist entries could be created automatically. They can, within limits that are part of this design and not negotiable by a future implementer:

- **Never log in, never handle credentials.** If the session has expired, stop and hand back to the owner.
- **Read the existing wishlist first**, in the owner's logged-in session. Anything already present is not re-added. This read also produces the watch-listed snapshot the dashboard displays — answering the owner's original *"I would like to know in the GUI whether I had it watch listed yet."*
- **Establish the write by observation, not inference.** Before any batch, the owner adds one film by hand while the network call is captured. The batch replicates that exact call. If it cannot be reproduced, fall back to per-film deep links and the owner clicks Add — still an improvement, because the price to enter is already on screen.
- **Show the batch and get a yes.** The owner sees every film and target price before anything is written, approves that specific set, and each write is reported. One approval is not standing permission for later batches.
- **Existing entries at a wrong target are corrected** (D7), and every correction is reported as from → to.
- **Record locally what was added or corrected**, so a re-run is idempotent even if the wishlist read fails.

## 7. Out of scope

Alerting from movie-brain (CheapCharts owns that) · buying anything · rental prices · non-US stores · services other than Apple · a weighted variant of the `on 2+ lists` chip · any change to how trust is set.

## 8. Gates

`uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`. Nothing here touches the resolver, the fixture or the identity write path — the iTunes id is confirmed against an IMDb id we already hold, and no film is ever created, keyed or merged by this feature.
