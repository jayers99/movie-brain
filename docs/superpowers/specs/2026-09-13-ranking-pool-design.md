# Ranking pool — Phase A of "ranking before rating"

**Date:** 2026-09-13 (late) · **Status:** implemented 2026-09-13 (plan docs/superpowers/plans/2026-09-13-ranking-pool.md) · **Extends:** the tier ranker (`2026-09-13-tier-ranker-design.md`) and the order mode (`2026-09-13-order-top-tier-design.md`). **Opens:** the ranker's pool as a fact of its own, a "Rank this" mark, and a second ordered tier. **Phase B** (ratings follow the ranking, the Unseen chip) is a separate spec once the backlog is ordered.

## 1. Goal

The owner ruled tonight that ranking is the better instrument, so ranking comes first and the rating will be derived from the tier (Phase B). That inverts today's dependency, where ratings seed tiers and are the only way a non-owned film reaches the ranker. Phase A makes the ranker's pool a defined thing independent of ratings, admits the 48 rated-not-owned films for free, removes the seven films that seeded on a score that means "not for the ranker", and lets the owner strict-order tier 2 the way tier 1 is ordered today. Nothing here writes `my_ratings`; tiering spec D2 still holds until Phase B reverses it deliberately.

Numbers on 2026-09-13: 858 owned, 716 placed (tier tally 93 / 257 / 71 / 171 / 124), 142 unseen, 0 remaining; 337 ratings (16 zeros); 87 rated-not-owned of which 48 score 6–10, 28 score 1–5 and 11 score 0; two owned films score 4; five owned score 0.

## 2. Decisions (owner rulings, 2026-09-13)

| # | Ruling | Evidence / cost if wrong |
|---|---|---|
| P1 | **The pool** is owned ∪ marked "Rank this" ∪ rated 6–10, minus disposed and unseen. Films rated 0–5 are out, owned or not. | A 0 means "not interested, won't watch" (owner's definition); 1–4 is disliked; 5 is watched-and-indifferent. None of those belongs in a ranking of films the owner likes, and the ranker has no "worse than everything" exit — its bottom outcome is tier 5. Cost if wrong: seven films leave the ranking (§4.5) and are one mark away from returning. |
| P2 | **"Rank this"** is an explicit per-film mark on the watchlist pattern: its own table, the drawer toggle its only UI writer, never touched by sync or importers. | Once ratings are derived (Phase B) a rating cannot also be the entry ticket without circularity. Owned films need no mark. |
| P3 | **Seed on read.** A pool film holding a rating 6–10 and no placement is seeded into its tier on the next read, in either mode. | This is what makes the 48 films free, and it closes a latent gap: a film rated after the session started is asked today instead of seeded. |
| P4 | **The seed map's bottom changes**: 10→1, 9→2, 8→3, 7→4, 6→5; 5 and below seed nothing. | Follows from P1. The tiers project to 10/9/8/7/6 in Phase B, with 5 as the hand-set floor outside the ranker. |
| P5 | **Order mode takes a tier**, 1 or 2, as two tabs. Rating (Phase B) stays the tier regardless of position; the order lives in the saved list only. | The owner chose to strict-order tiers 1 and 2 (~2,700 clicks) knowing the tier-2 order changes no rating. The `tier` column in the order tables was built for this; no schema change. |
| P6 | The session's source key stays `owned`; the list slug stays `my-owned-tiers`; the default list name becomes "My films, tiered". | No migration for a rename; URL state and the picker keep working. The docs say what the key now means. |
| P7 | **One-time correction at apply time**: the seven seed placements written on a score ≤ 5 are deleted, announced row by row. | Five zeros (Bill & Ted's Excellent Adventure, Dr. No, Goldfinger, Sullivan's Travels, Wings of Desire) and two fours (West Side Story 2021, Inglourious Basterds). They are not asked again: P1 keeps them out of the pool. |

## 3. Data model (migration 024)

```sql
CREATE TABLE rank_mark (                 -- "Rank this": the pool's entry ticket for a non-owned film (P2)
    film_id   INTEGER PRIMARY KEY REFERENCES films(id),
    marked_on TEXT NOT NULL
);
INSERT INTO schema_version (version) VALUES (24);
```

`rank_mark` joins `_ONE_ROW_TABLES` so `merge_film` moves it survivor-wins. `set_unseen` does not touch it: a marked film that is unseen is out of the pool until unmarked, and returns when unmarked. `FilmView` gains `rank_marked: bool` (LEFT JOIN like `unseen`), served on `/api/films` and `/api/films/<id>`.

No other table changes. `rank_order`, `rank_order_comparison` and `rank_order_deferral` already carry `tier`.

## 4. Behaviour

### 4.1 The pool

`Repository.rank_pool_film_ids() -> set[int]`: film ids that are owned OR in `rank_mark` OR hold a `my_ratings.score` between 6 and 10, minus `film_disposition`, minus `unseen`, minus any film whose score is 0–5 (a low score excludes even an owned or marked film, P1). It is the only definition; `application/rank.py` reads it everywhere it reads `owned_film_ids()` today: the tiering queue, the proposal's fallback candidates, `start_session`'s anchor checks, `swap_anchor`, and the `unseen` count in `session_state` (which becomes "unseen ∩ (owned ∪ marked)", since a pool film cannot be unseen by definition).

`Repository.pool_seed_films() -> list[SeedFilm]` replaces `owned_seed_films`: pool ∩ rated 6–10. `propose_anchors` and the choices table read it.

### 4.2 Seed on read

`_seed_new(repo, s, today)` in `application/rank.py`: for every `pool_seed_films()` entry with no `rank_placement` in the session, `place_film(s.id, fid, tier_for_score(score), "seed", today)`. Called at the top of `session_state` and `order_state` before either queue is derived. A seeded film is never asked (tiering D11) and joins the order queue of its tier like any placed film. `tier_for_score` raises `ValueError` for a score below 6; `pool_seed_films` never returns one.

### 4.3 Order tier 2

`order_state(repo, source, tier, today)`, `order_verdict(..., tier, ...)`, `order_pass(..., tier, ...)`: `ORDER_TIER` becomes `ORDER_TIERS = (1, 2)` and the routes take `tier` — `GET /api/rank/order?tier=1|2`, bodies gain `tier`. A tier outside `ORDER_TIERS` is 400. Each tier's queue, deferrals and order are already scoped by the `tier` column. `last_action` order kinds carry `tier` so undo removes the film from the right order. `save_list` passes both tiers' orders into `tiered_entries` (which already labels any ordered tier bare and its remainder tied). The page's tab bar becomes `Tiers · Order tier 1 · Order tier 2`, hashes `#order-1` and `#order-2` (`#order` is read as `#order-1` so a saved bookmark still works); the progress line names the tier. Nothing enforces finishing tier 1 first.

### 4.4 The drawer

An `Rank this` toggle beside the Unseen toggle in the drawer's row under the title (same `unseen-row`), class `rank-toggle`, `aria-pressed` from the server. `PUT /api/films/<id>/rank-mark` `{marked: bool}` → `{marked: bool}`, 404 for an unknown film; `Repository.set_rank_mark(film_id, marked, today) -> bool | None`, idempotent. Marking an owned film is legal and inert (already in the pool). Marking a film rated 0–5 is legal and inert until the rating changes (P1 wins). No chip in Phase A.

### 4.5 The correction (apply time, not code)

Seven `rank_placement` rows in the live session have `how = 'seed'` and a score of 0 or 4. The apply step lists them, the owner confirms once, and they are deleted. No `rank_order`/`rank_order_comparison` rows name them (tier 5 is not ordered). On the next read they are out of the pool (P1). No repair verb is added: the seed map that wrote them no longer exists, so it cannot recur.

### 4.6 Edges

- A film rated 0–5 from the drawer after being placed or ordered, or a marked film unmarked after placement: it leaves the POOL on the next read, which today changes only the tiering queue (it is never asked again). Its placement, its order position, any anchor seat it holds and its line in the saved list all STAY until it is marked unseen — `_order_queue`, `save_list` and `needs_anchor` read placements, not the pool. Deferred to Phase B: whether leaving the pool should cascade like unseen does; cascading a rating change into ranker tables would make ratings a writer of them, which the tiering spec avoided.
- A pool film later disposed: excluded by the existing disposed guard everywhere; its rows stay as with any tombstone.
- A placed film in the wrong tier (the 1/2 seam, where a 10 seeded tier 1 and a 9 seeded tier 2 with no comparison between them): moved by hand from the drawer since 2026-09-14 — `2026-09-14-move-tier-design.md`, which leaves the old order entirely and waits unordered in the new tier.
- The proposal (before a session exists) reads the pool, so a first session on a fresh DB with marks and no owned films still gets anchors.
- `undo` falls back to tier 1 when a stored `last_action` carries no `tier` (rows written before this phase, when order mode had only tier 1).
- `start_session` and `swap_anchor` accept any pool film as an anchor, not only an owned one — an anchor is just a pool film the owner has seen.

## 5. API

| Route | Change |
|---|---|
| `GET /api/rank/order?tier=N` | `tier` required, 1 or 2; response gains `tier` (already present) — unchanged shape otherwise. |
| `POST /api/rank/order/verdict` | body gains `tier`. |
| `POST /api/rank/order/pass` | body gains `tier`. |
| `PUT /api/films/<id>/rank-mark` | new; `{marked: bool}`. |
| `GET /api/films`, `/api/films/<id>` | `rank_marked` on every view. |
| `GET /api/rank/session` | unchanged shape; `unseen` counts unseen ∩ (owned ∪ marked). |

## 6. Tests

- Unit: `tier_for_score` for 6 → 5 and raising below 6; `rank_pool_film_ids` on a fixture with owned, marked, rated-6, rated-5, rated-0-owned, unseen-marked and disposed films; `set_rank_mark` idempotent and 404-shaped; `merge_film` moves `rank_mark` survivor-wins.
- Feature (`rank.feature` / `rank_order.feature` extended, or a new `rank_pool.feature`): a rated-8 non-owned film seeds into tier 3 on the first read and is never asked; a 0-rated and a 4-rated owned film are not in the queue; a film rated 9 after the session started seeds on the next read; a marked unrated film is asked; unmarking it removes it from the queue; a marked film rated 4 is not in the pool; the proposal's fallback offers a marked film; order tier 2 has its own queue, verdicts and deferrals, independent of tier 1's; undo in tier 2 removes from tier 2's order only; save writes both ordered tiers bare and their remainders tied.
- Web: the rank-mark route (shape, 404, round trip); the drawer toggle round-trips (Playwright, pattern of `test_drawer_unseen_toggle_round_trips`); the Order tier 2 tab serves a pair and `#order` maps to tier 1.
- Live (plan's apply task): after `migrate --apply` (024) and the seven deletions, `rank_placement` count = 716 − 7 + 48 = 757; tier 1's order queue holds the two tens; tiering `remaining` stays 0.

## 7. Out of scope

Writing `my_ratings` (Phase B); the Unseen chip (Phase B); ordering tiers 3–5; a chip for `rank_mark`; cascading a rating change into ranker rows (§4.6); renaming the source key or the slug (P6).

## 8. Documentation

`CLAUDE.md`'s tier-ranker bullet: the pool definition, seed on read, the seed map's new bottom, `rank_mark` and its single writer, the two ordered tiers, and the D2 status ("still never writes `my_ratings`; Phase B reverses it"). `docs/backlog.md` gains "Phase B: ratings follow the ranking + Unseen chip" as a new item. The order spec's O9 line notes that tier 2 is now exposed.
