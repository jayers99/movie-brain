# On Sale / canon acquisition — handoff seed

**Written:** 2026-08-29, end of a long design session. **Branch:** `feature/on-sale` (spec only, `18d7b05`; nothing implemented). **Live DB:** schema v16; snapshots `movie-brain.db.bak-pre-trust`, `.bak-pre-rekey493`. **Next migration is 017.**

**Read first:** `docs/superpowers/specs/2026-08-29-on-sale-canon-acquisition-design.md` — the full design with every owner decision and its reasoning. This handoff carries what that spec does *not*: the probe evidence gathered after it was written, and the reshaping that evidence forces.

## 1. What this is (do not rebuild the smaller idea)

Backlog item 3 says *"CheapCharts price-watch integration — a button that adds a film to my price watch list."* **That is not the feature.** The owner's goal, in their words: *"what I'm interested in studying is the canonical canon… after my study period I could watch modern films and apply the skills and refined taste acquired from studying the canon."*

This is **a study tool: a ranked queue of canon films worth acquiring, with price as the trigger.** The ranking is the product; the price is the smallest part. Two framings were tried and rejected *by the owner* — don't revisit them:

- *Show the lowest price in the drawer.* Useless: *"that price comes right up when you do it."* The labour was the **pair** of steps — look up the floor, then hand-enter it as a target.
- *Replace CheapCharts' watchlist with our own alerts.* Rejected: *"I want to keep my watchlist on CheapCharts… I get a nice alert to my iPhone and they make it easy for me to purchase from there."*

## 2. The probe, and what it changed (2026-08-29, after the spec was written)

Ran against the top 40 candidates by canon rank, live API, no writes.

| outcome | n |
|---|---|
| **confirmed on iTunes US** | **23 / 40 (57%)** |
| genuinely not on iTunes US | 15 |
| no IMDb id derivable at all | 2 |

Three findings that reshape the build:

**a) The IMDb-id gap is a hard prerequisite.** A first probe scored only 10/30 — **11 of those 20 failures were our fault**, films holding a TMDB id and no IMDb id, so nothing could confirm a match. Resolving them in memory rescued 13 films outright (*Metropolis, Rio Bravo, The Leopard, Touch of Evil, Do the Right Thing, The Conformist, Man with a Movie Camera, Nashville*…). Live counts: **4,538 films hold a TMDB id, 850 hold an IMDb id, 3,699 hold TMDB but no IMDb.** Of the 255 On Sale candidates, 172 lack an IMDb id and 166 of those have a TMDB id — i.e. one `movie_detail` call each away.

**b) The 43% miss is real, not a search bug.** Checked by hand at `limit=20` under English *and* original titles: *Notorious* returns only the 2009 Biggie film; *Le Mépris* returns unrelated French titles; *La Grande Illusion* returns nothing relevant. These are Criterion-catalogue films licensed for streaming and disc but **never sold on Apple**. No tool can fix that — but "not buyable on Apple" is itself useful output and should be surfaced, not silently dropped.

**c) Almost nothing is at its low at any given moment.** All 23 confirmed films priced $9.99–$14.99 on the day; **none at $4.99**. So an "On Sale" browse view is empty most days. **The watchlist half is the valuable half**; the browse chip is secondary. Build accordingly.

Also noted: CheapCharts' own search is weak (`"Contempt"` returns *Killer Concept*, *The Christmas Contest*), so confirming on `imdbId` is mandatory — it prevents wrong matches but cannot find what search never returns. Apple's own iTunes Search API was tried as a better join and returns `resultCount: 0` even for `vertigo` — dead end from this IP.

## 3. The recommended order — and the open decision

The controller recommended, and the owner has **not yet chosen**:

1. **IMDb backfill** — standalone. ~3,699 films, one TMDB `movie_detail` call each, on demand. Independently valuable: this same gap forced gate 2b during the list imports and left *Black Narcissus* and *Melancholia* unresolvable by machine.
2. **Canon ranking + candidate view** — what the owner asked for first, and it works for **100%** of films rather than 57%. If only one thing gets built, build this.
3. **Price + watchlist automation** — real value, but 57% coverage and a usually-empty browse list.

**First question for the new session:** all three, or 1 and 2 only, leaving the price work until the owner has lived with the queue?

## 4. Constraints that bind this work

- **The IMDb backfill is an identity write.** `application/keying.py::key_film` is the ONE identity write path (`.claude/rules/thumbprint.md`) — the backfill must go through it, never `set_external_id` directly. Note `key_film` → `record_tmdb_match` canonicalizes `films.year` for a **commerce-created** film (no Criterion listing); that is documented, correct, and will move some years. Rehearse on a scratch copy and show the owner the year changes before applying live.
- **Never write to `scripts/eval/thumbprint_eval_v1.csv` or the fixture.** A backfilled id is not resolver ground truth.
- **Syncs are manual by choice.** No scheduled job, no launchd. The price refresh is an on-demand verb; `prices dial [N]` follows `metacritic dial`'s show/set shape.
- **Browser automation limits (spec §6) are not negotiable:** never log in, never handle credentials; read the existing wishlist first and skip what is there; establish the write by having the owner add one film while the network call is observed, never by inferring it; show the batch and get a yes before writing; one approval is not standing permission.
- **Owner decision D7:** existing watchlist entries at a wrong target **are corrected**, and every correction reported as from → to. The owner overrode a report-only recommendation, having been told that correcting a target *downward* stops alerts at the higher price.
- Gates after every task: `uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`.
- Markdown is never hard-wrapped. Never edit an applied migration. Films are immutable.

## 5. Reusable probe code

`/tmp/probe2.py` from this session does candidate selection, canon ranking, in-memory IMDb resolution, CheapCharts search + `imdbId` confirmation. It is scratch, not checked in, and `/tmp` may be cleared — but the API shapes it proved are recorded in spec §4 and are the non-obvious part.

Verified API surface, unauthenticated, `Referer: https://www.cheapcharts.com/` required:

```
buster.cheapcharts.de/v1/gptapi/Search.php?action=search&store=itunes&country=us&itemType=movies&query=<t>&limit=N
buster.cheapcharts.de/v1/DetailData.php?store=itunes&country=us&itemType=movies&idInStore=<iTunes track id>
```

`DetailData` returns `imdbId`, `priceHd`, `priceHdIsLowest`, `priceHdEvolution` (full history as `date:±price~…`), `iTunesUrl`, `cheapChartsProductPageUrl`, plus trailers/cast/awards/Letterboxd — which is most of **backlog item 4 (richer drawer)** for free, and worth noting when that item comes up.

## 6. State to be aware of

- Three lists live and 100% linked: `cahiers-100` (trust 10), `bergan-100` (9), `sight-and-sound-2022` (8). 23 films on all three, 70 on two.
- **255–263 On Sale candidates** today (the number moves as films are rated).
- Two films created but deliberately **unkeyed**, awaiting a sync then `review resolve <row> --tt <id> --series`: `#4763 Histoire(s) du Cinéma` (`tt6677224`) and `#4764 Twin Peaks: The Return` (`tt4093826`). Both appear in candidate lists with no year until keyed.
- `movie-brain repair links --film ID --tt ttNNN [--apply]` was added this session (merged `07318dc`) for a film keyed confidently to the wrong work — the shape no other repair verb can see./
