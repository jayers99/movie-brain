# On Sale — working through the canon, with price as the acquisition trigger

**Date:** 2026-08-29 · **Status:** designed with the owner across a long conversation; every decision below is theirs and recorded with its reasoning. **Amended 2026-08-29 (build session)** — the probe evidence in the handoff arrived after this spec was written, and the owner has since chosen a build scope (D9) and a backfill shape (D10). Amendments are §2's Criterion clause, §3's floor analysis and list-size note, §5, §6, §8, and the new §9, §10, §11 and §12. §1's D1–D8 are untouched.

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
| D9 | **Build the IMDb backfill and the canon ranking now; defer all price and watchlist work** | The ranking works for 100% of the catalogue; the price half reaches only the 57% Apple actually sells, and the browse view is empty most days (handoff §2c). Deferring the price work also means **no schema change at all** — see §10 |
| D10 | **The backfill writes the IMDb id alone — a "quiet" backfill, no year canonicalization** | These films already hold their TMDB id, so a full re-key would re-run `record_tmdb_match` and move `films.year` on up to **1,236 commerce-created films** as a side effect of writing a missing id. The quiet form uses the same sanctioned `key_film` path and moves no years — see §9 |
| D11 | **`sight-and-sound-2022` demoted to trust 7; both 1992 Sight & Sound polls added as separate lists — critics at 8, directors at 6** | The owner trusts Moviewise's judgement that the 1992 poll is the better canon and wants it weighted above the 2022 one. Two polls, not one: the 1992 page publishes a critics' top ten and a **separate** directors' top ten with a different electorate, and merging them would invent a ranking nobody published. The trust demotion is **already applied live** (2026-08-29) — `lists trust` is a one-command, reversible change that needed no code |
| D12 | **No membership floor in `canon_score` — the formula in §3 stands unchanged** | Delegated to the controller and decided on the data; see §3's "The floor question, settled" |
| D13 | **BFI Player is shelved, not rejected** | The owner's call after seeing the complication. See §11 |

## 2. The gate — which films are worth buying

A film is a candidate when **all** hold:

- it is **not currently streamable** on any service where `movie_service.subscribed = 1 AND kind = 'svod'`. The `kind` test matters: `apple-tv-store` is marked subscribed but is a shop, and a shop must never suppress a film. Currency uses the existing rule — `last_seen >= tmdb_providers_refreshed_at`, or `MAX(last_seen)` for criterion.
- **The Criterion Channel needs its own clause** (found in the code, 2026-08-29). `criterion` *is* a subscribed `svod` row in `movie_service`, but `_SERVICES_SQL` filters it out (`l.source != 'criterion'`), so it never reaches `FilmView.services`. Testing `services` alone would therefore offer to buy films that are streaming on the Channel right now. On a `FilmView` the test is `criterion AND NOT departed`; in SQL it is a current `listings` row for source `criterion`.
- it is **not owned** (`owned` table)
- it is **not already rated** (`my_ratings`)
- it is not disposed
- and it is **either on at least one curated list, or scores ≥ 90 on Metacritic**

**263 candidates today.** 84 list-only, 22 both, 160 Metacritic-only. *Re-measured against the live DB on 2026-08-29 with the Criterion clause above in place: 263 total — 84 list-only, 21 both, 158 Metacritic-only. The gate reproduces; the small drift is films rated since.*

Note the self-deepening property: rating a film removes it from the set, so the same dial reaches one film further down. The dial exists to outpace that, not to keep up with it.

## 3. The rank — two tiers, and why Metacritic is not in tier 1

**Tier 1 — the canon.** Films on at least one list, ranked by

```
canon_score = Σ over lists ( trust × (1 − (printed_rank − 1) / list_size) )
```

so #1 on a list contributes its full trust and the last entry contributes ~0. Position matters, not just membership: Cahiers #12 outweighs Sight & Sound #243. The original curated-lists spec §5.7 warned against summing ranked and unranked membership blindly; this honours it. A tied `rank_label` (`=196`) uses the printed rank, which is the poll's own judgement.

### The floor question, settled (D12)

A ten-entry list decays to near nothing by its last rank — 2001 at #10 of the 1992 critics' ten would contribute `8 × 0.1 = 0.8`, which reads a genuine honour as noise. The proposed fix was a **membership floor**: a list contributes at least 25% of its trust to any film on it, `trust × (0.25 + 0.75 × positional)`.

**Measured on the live catalogue (348 listed films), with both 1992 polls simulated in, the floor changes almost nothing:**

| comparison | overlap |
|---|---|
| top 10 with floor vs without | 9 / 10 |
| top 25 | 23 / 25 |
| top 50 | 49 / 50 |

The top fifteen are the same films in near-identical order (Vertigo and The Godfather each move up one or two places; nothing enters or leaves). What the floor *does* change is the deep tail: films sitting at **poor** ranks on two lists rise 70–85 places out of 348 — *Star Wars*, *Annie Hall*, *Once Upon a Time in America*, *Letter from an Unknown Woman*. For a canon **study** queue that is the wrong direction: it rewards mediocre placement on two lists over strong placement on one, which is precisely the blind membership-summing the curated-lists spec §5.7 warned against.

**Decision: no floor.** It costs a tunable, changes nothing the owner would act on, and its only measurable effect is one we do not want.

Two mechanics the formula needs and the code does not yet supply (found 2026-08-29):

- **`list_size` is not on `FilmView`.** `_LISTS_SQL` carries slug, name, curator, published, ordered, trust, rank and `rank_label` — not the entry count of the list. The score's denominator needs it, so each `FilmView.lists` entry gains a `size`.
- **`rank_label` is the printed cell and may carry a tie marker.** The score reads `rank_label` when present and falls back to `rank`, parsing a leading `=` off (`"=196"` → 196). An **unordered** list (`ordered = 0`) has no meaningful position; such a list contributes its full trust, since membership is all it asserts.

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

**Amended by D9.** The price half of this section is deferred; what ships now is the ranked queue itself.

**Ships now.** A canned filter chip — `acquire` — carrying the §2 gate, and a **canon rank** sort that orders tier 1 by `canon_score` descending and puts every tier-2 film below every tier-1 film. Both live where the existing ones live: the predicate and the sort key in `domain/filters.py` (the only home for chip names and thresholds), the chip button in `index.html`, `CHIP_PREDICATES` in `static/app.js` kept in lockstep, thresholds read from `/api/config`. The drawer's existing "On lists:" row already shows the evidence behind a film's rank, so no new drawer section is needed.

**Deferred with the price work.** Each row showing the historical low, the at-the-low flag, the button to the film's CheapCharts page, and the `On Sale` chip that narrows to the at-the-low ones. Two states the price data exists to tell apart:

| state | meaning |
|---|---|
| current == historical low | **buy it now** |
| current > historical low | **set a watch at the low** |

## 6. The CheapCharts batch — driving the browser

**Deferred by D9 — nothing in this section is built in this pass.** The limits below stand unchanged for whenever it is, and are not negotiable by a future implementer.

The owner asked whether the watchlist entries could be created automatically. They can, within limits that are part of this design:

- **Never log in, never handle credentials.** If the session has expired, stop and hand back to the owner.
- **Read the existing wishlist first**, in the owner's logged-in session. Anything already present is not re-added. This read also produces the watch-listed snapshot the dashboard displays — answering the owner's original *"I would like to know in the GUI whether I had it watch listed yet."*
- **Establish the write by observation, not inference.** Before any batch, the owner adds one film by hand while the network call is captured. The batch replicates that exact call. If it cannot be reproduced, fall back to per-film deep links and the owner clicks Add — still an improvement, because the price to enter is already on screen.
- **Show the batch and get a yes.** The owner sees every film and target price before anything is written, approves that specific set, and each write is reported. One approval is not standing permission for later batches.
- **Existing entries at a wrong target are corrected** (D7), and every correction is reported as from → to.
- **Record locally what was added or corrected**, so a re-run is idempotent even if the wishlist read fails.

## 7. Out of scope

Alerting from movie-brain (CheapCharts owns that) · buying anything · rental prices · non-US stores · services other than Apple · a weighted variant of the `on 2+ lists` chip · any change to how trust is set.

**Out of scope for this build, deferred by D9, not abandoned:** the `price` table and migration 017 · `prices refresh` / `prices dial` · every CheapCharts HTTP call · all browser automation (§6) · the price columns and `On Sale` chip in §5.

## 8. Gates

`uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`.

**Corrected 2026-08-29.** The original claim here — *"nothing here touches the resolver, the fixture or the identity write path"* — was true of the price feature alone and is **false** now that the backfill (§9) is in scope. The accurate statement:

- The backfill **is** an identity write and goes through `application/keying.py::key_film`, the one identity write path, never `set_external_id` directly.
- It **keys films** — 3,699 of them. It still creates no film and merges none.
- It does **not** touch the resolver: no `resolve()` call, no candidate scoring. The id comes from TMDB's own `movie_detail` for a TMDB id the film already holds.
- `scripts/eval/thumbprint_eval_v1.csv` and the resolver fixture are **never written**. A backfilled id is TMDB's assertion, not resolver ground truth.
- The ranking work (§3, §5) touches none of this and is pure read-model plus domain predicate.

## 9. The IMDb backfill (build item 1)

**Why it is worth doing on its own.** 4,538 films hold a TMDB id, 850 hold an IMDb id, **3,699 hold TMDB but no IMDb** (verified against the live DB, 2026-08-29, schema v16, 4,735 films). That gap is what forced gate 2b during the list imports, what left *Black Narcissus* and *Melancholia* unresolvable by machine, and what held the CheapCharts probe to 10/30 until it was resolved in memory — after which the same probe reached 23/40. It is also a prerequisite for §4 whenever the price work is built.

**The write, exactly.** For each film holding a `tmdb` external id and no `imdb` one, and not disposed:

1. `TmdbClient.imdb_id(tmdb_id)` — one `movie_detail` call, the id TMDB itself publishes for a TMDB id this film already holds. No search, no scoring, no ambiguity to resolve.
2. `key_film(repo, tmdb, film_id, tt, today, tmdb_id=None, resolve_tmdb_id=False)`.

**Why those two arguments (D10).** `resolve_tmdb_id=False` tells `key_film` not to repeat a `find_by_imdb` lookup; `tmdb_id=None` then means it writes the IMDb id and stops. The film's TMDB link already exists and is not rewritten, so `record_tmdb_match` never runs — and neither does its year canonicalization, which would otherwise move `films.year` on up to **1,236 commerce-created films** (measured: that is how many of the 3,699 have no Criterion listing). Writing a missing id must not be a year migration in disguise. This is a documented use of the existing signature, not a new path.

**What still happens, and should.** `key_film` ends by comparing the film's OMDb `imdbID` to the new `tt` and calling `mark_omdb_refresh` when they differ — so every backfilled film is queued for an OMDb refetch **by id** on the next manual sync, filling in director and ratings for Mode-B films. That is a benefit, not a side effect to suppress.

**Failure shapes, none of them silent.**

| result | meaning | handling |
|---|---|---|
| `unlinked` | id written | counted as backfilled |
| `held` | another film already holds that `tt` | a twin. Queue **one durable review row** (`queue_review_once`, authority `imdb`); never overwrite, never guess |
| TMDB has no `imdb_id` for the id | genuine absence | counted and reported; no write |
| network / auth error | transient | counted; consecutive-failure abort like `key_films`, so a re-run resumes |

**Shape.** A CLI verb, dry run by default, `--apply` to write, `--limit N` to batch — the established shape of every `repair` verb. Never scheduled (D6 generalises: syncs are manual by choice).

**Rehearsal is mandatory.** Every run — including subagent runs — sets `MOVIE_BRAIN_CONFIG_DIR` to a scratch copy of the live DB. The owner sees the full result, including a `films.year` diff proving zero years moved, before anything runs live.

## 10. Build scope (D9)

| item | this pass | note |
|---|---|---|
| 0. Trust demotion + the two 1992 lists | **yes** | D11, §11 — the trust demotion is already applied live |
| 1. IMDb backfill | **yes** | §9 |
| 2. Canon ranking + candidate view | **yes** | §2, §3, §5 "ships now" |
| 3. Price + watchlist automation | **no** | §4, §5 "deferred", §6 |
| — BFI Player as a suppressing service | **no** | shelved by D13, §11 |

**Order matters within this pass.** The backfill (item 1) runs **before** the 1992 imports. Gate 1 — "a film already keyed to the winning IMDb id" — is the gate that stops a list import mislinking, and today only 850 of 4,735 films hold an IMDb id at all; 8 of the 1992 critics' ten hold none. Backfilling first is what makes item 0 safe.

**No migration.** The backfill writes `external_ids` rows; the 1992 lists write `film_list` / `film_list_entry` rows through the existing two-verb import; `canon_score` is computed and never denormalized onto `films` (the curated-lists rule). Nothing in this pass changes the schema — the live DB stays at v16 and **017 remains unwritten**.

## 11. The 1992 Sight & Sound polls, and the BFI shelf

**The 1992 lists (D11).** Source: `https://www.bfi.org.uk/sight-and-sound/polls/greatest-films-all-time/1992`. The page publishes **two top tens only** — no top 100 existed before 2012 — so these are ten- and twelve-entry lists (after ties), not peers of `cahiers-100`. Nineteen distinct films across both.

- `sight-and-sound-1992-critics`, trust **8**, 10 entries, ties at `=6` (four films) — `rank_label` carries the printed cell exactly as `sight-and-sound-2022` does.
- `sight-and-sound-1992-directors`, trust **6**, 12 entries, ties at `=2`, `=6`, `=9`.

**All nineteen films are already in the catalogue and already on at least one existing list.** Verified 2026-08-29 — including *The Godfather: Part II*, which a crude title match initially missed. So `lists import --apply` links every entry and **`lists create` has nothing to mint**: this increment adds zero films and cannot produce the duplicate the lists contract exists to prevent. It is the lowest-risk list import the feature has seen.

What it does change is the top of the ranking, more than first estimated: with both polls in, *The Passion of Joan of Arc* moves from 13th to 7th, *Vertigo* from 7th to 4th, *Tokyo Story* from 8th to 5th, and *The Searchers* and *The Godfather* enter the top twelve. The earlier claim that the 1992 poll "sharpens but does not reshape" was measured on the critics' ten alone and on coverage rather than ordering; with both polls weighted at 8 and 6 the top fifteen genuinely moves.

Note `La strada` (film #1812) carries **no year**. The form ladder queries with `year=None` regardless, so this is not a blocker, but it is the entry most likely to need a review row.

**BFI Player — shelved (D13).** The owner subscribed to BFI on Apple TV; adding it as a suppressing service turned out to be more complicated than it is worth today, and they shelved it. Recorded so it is not re-derived:

- `bfi-player-classics` already exists in `movie_service` (svod, region US, `subscribed = 0`) but has **no `service_provider` row**, so TMDB has never written one BFI listing. Flipping `subscribed` alone would suppress nothing.
- TMDB's **US** region knows BFI only as provider **287, "BFI Player Amazon Channel"** (253 films) — and Amazon-channel ids are the one class this project excludes. "BFI Player" (224) and "BFI Player Apple TV Channel" (2041) exist only under **GB**.
- Measured benefit if 287 were adopted for US: **5 of the 263 candidates** would be suppressed — *Contempt*, *Distant Voices, Still Lives*, *Passport to Pimlico*, *The Discreet Charm of the Bourgeoisie*, *The Servant*. *Contempt* is notable: the CheapCharts probe could not find it on iTunes at any price, so BFI reaches a film Apple never sells.
- Doing it would require migration **017** (a `service_provider` row plus the `subscribed` flip — no CLI verb writes either) and a forced providers refresh, plus a deliberate carve-out to the Amazon-channel exclusion.

## 12. Housekeeping

**Known state to clear first.** Films `#4763 Histoire(s) du Cinéma` (`tt6677224`) and `#4764 Twin Peaks: The Return` (`tt4093826`) are deliberately unkeyed pending a sync and `review resolve <row> --tt <id> --series`. Both hold no TMDB id, so the backfill does not touch them; they will appear in the ranked queue with no year until they are keyed.
