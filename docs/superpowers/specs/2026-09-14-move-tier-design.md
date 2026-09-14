# Move a film to another tier

**Date:** 2026-09-14 · **Status:** implemented 2026-09-14 (plan-mode plan, branch `feature/STORY-18-move-tier`) · **Extends:** the tier ranker (`2026-09-13-tier-ranker-design.md`), the order mode (`2026-09-13-order-top-tier-design.md`) and the ranking pool (`2026-09-13-ranking-pool-design.md`). **Opens:** a hand-set tier from the dashboard drawer, and "Rank this" as the drawer's one "the ranker still owes this film a pass" signal.

## 1. Goal

The ranker places a film once — seeded from `my_ratings` or binary-searched against the anchors — and nothing ever moved it across a tier line afterwards. With tiers 1 (95) and 2 (264) both fully ordered in the live session, the seam between them is visibly wrong: a 10 seeded tier 1 and a 9 seeded tier 2, and no comparison ever crossed that line, so the saved "My Ranking" list has Star Trek V (tier 1, #95) above The Shining (tier 2, #96). The owner marked the films that should move with "Rank this", which is inert on a film already in the pool, so nothing happened.

This spec adds a **move verb**: the owner sets a placed film's tier by hand from the drawer, the film leaves its old tier's order entirely, and it waits unordered in the new tier until the Order tab binary-inserts it. The seam merge that was brainstormed first (auto-promote across the 1/2 seam by binary insertion) is parked; this verb is the primitive it would need.

## 2. Decisions (owner rulings, 2026-09-14)

| # | Ruling | Evidence / cost if wrong |
|---|--------|--------------------------|
| M1 | **A move writes the tier by hand:** `rank_placement.how = 'moved'`, the row REPLACED in place (`INSERT OR REPLACE`), never deleted and re-inserted. | `_seed_new` (application/rank.py) re-seeds any pool film with no placement row back to its rating's tier on the next read; a replaced row cannot race that. `moved` lets the audit tell a hand move from a search result. |
| M2 | **The moved film leaves its old tier's order:** its order row (gap closed), every `rank_order_comparison` naming it on EITHER side, and its `rank_order_deferral` — scoped to the open session. | Necessary, not tidy: `order_verdicts_for` / `films_with_order_verdicts` read the candidate log with NO tier filter and `rank_order_deferral` has no tier column, so without the purge a film moved 1→2 would arrive in tier 2 "mid-insertion" and deferred-last, and a tier-1 verdict could later bound a tier-2 search. Finished sessions' logs stay intact (the unseen purge is cross-session; this one is not). Other candidates probed against it re-probe (order spec §4.4). |
| M3 | **The film waits unordered in the new tier**; `_order_queue` picks it up. No edge placement, no new ordering code. O7 still applies: into an EMPTY ordered tier it is inserted on the next read with no click. | Every order position is a real comparison. The alternative — land at the new tier's edge for free — plants a position no comparison made and is wrong the moment a move is not a seam move. |
| M4 | **"Rank this" lights while the film awaits ordering.** `awaiting_order = tier in ORDER_TIERS and film not in rank_order(session, tier)`, computed on read, never stored. While awaiting, the button is pressed AND disabled, title `Waiting for Order tier N`; otherwise it is the pool toggle it was. `rank_mark` is untouched. | One signal for "the ranker still owes this film a pass" — pool entry or re-ordering. Disabling while awaiting avoids the conflation where un-marking a marked-and-awaiting film would visibly un-press a button that should stay lit. Derived, so nothing has to clear it when the Order tab inserts the film. |
| M5 | **Refused:** 400 tier outside 1–5; 404 no open session; 409 not placed in the session; 409 the film anchors its tier (`swap the anchor first`); 409 already in that tier — checked in that order. **No pool or unseen gate.** | Mirrors `swap_anchor`. Emptying an anchor seat would block the Tiers tab, and the swap-anchor UI is parked. A placed film that left the pool keeps its placement by ruling (pool spec §4.6), and the tier control edits the placement, which exists. An unseen film has no placement, so "not placed" covers it. The anchor check runs before the same-tier check so moving an anchor "to its own tier" gets the right message. |
| M6 | **A move clears `last_action`** (the rank page's one-level undo) instead of joining it. | The drawer has no undo; the inverse of a move is a move back. A stale undo of a `verdict` carrying `placed_tier` would unplace the moved film and `_seed_new` would re-seed it. `pass_film` already clears the slot on `anchor_unseen`. |
| M7 | **`rank_tier`, `rank_how`, `awaiting_order` are DETAIL-ONLY keys** on `/api/films/<id>`, never `FilmView` fields. The detail read never calls `_seed_new`. | `FilmView.to_dict()` is `asdict`, so a field would ride `/api/films` for 4,600 films for a control only the drawer shows. A GET must not become a writer of placements — so a film rated 6–10 since the last rank-page load shows no tier row until `/rank` is next opened. |
| M8 | **Tiering verdicts (`rank_comparison`) are left alone.** | `_queue` excludes placed films and `corrupt` is derived only inside that loop, so a placed film's trail is never read; it stays as the audit log. |
| M9 | **Migration 025 rebuilds `rank_placement`** to widen the `how` CHECK. | SQLite cannot ALTER a CHECK. Precedent `012_external_ids_multi.sql`; inside BEGIN/COMMIT; preserves `PRIMARY KEY (session_id, film_id)` (`place_film`'s INSERT OR REPLACE and `merge_film`'s twin checks rely on it) and both FKs; nothing references or indexes the table; `init_db` runs migrations on a bare connection with foreign keys OFF, so the DROP is safe. |
| M10 | **The rank page recovers from a stale pair:** `verdict`, `pass` and `undo` in `rank.js` refresh even when the request fails. | Before this, `api()` threw on a non-OK answer and `refresh()` never ran, so after a move from another tab the page kept the moved candidate on screen and every click re-409ed until a reload. |
| M11 | **Accepted race:** `order_verdict` reads the pair and appends in a second connection; a move landing between them could log one comparison naming the moved film after the purge. | Single user, microseconds, and `order_step` ignores verdicts against films not in the order. Same class as the existing tiers/order window. |

## 3. Data model (migration 025)

`rank_placement` is rebuilt with `CHECK (how IN ('seed', 'compared', 'anchor', 'moved'))`; rows, the composite PK and both FKs are copied unchanged. No new table, no new column.

## 4. Behaviour

- `Repository.move_placement(session_id, film_id, tier, today)` — one transaction: the placement row replaced with `how = 'moved'`, then `_purge_order_rows(c, film_id, session_id)` (the unseen purge, given an optional session scope exactly like `_remove_ordered` already has).
- `Repository.rank_placement_for(session_id, film_id) -> (tier, how) | None`.
- `application.rank.move_film(repo, source, film_id, tier, today)` — the M5 checks in order, `move_placement`, `set_last_action(None)`; returns `{"film_id", "tier", "from_tier", "awaiting_order"}`.
- `application.rank.rank_status(repo, source, film_id)` — `{"tier", "how", "awaiting_order"}`, all `None`/`False` without an open session or a placement; a READ.
- The drawer: a `.tier-row` under the Unseen / Rank this row — "Tier" plus five `button.tier-pick`, `aria-current="true"` on the film's tier — rendered only when `rank_tier` is not null. A click POSTs the move and patches `aria-current` and the Rank this button in place (never re-opens the drawer: `closeDrawer()`'s history bookkeeping); a refusal is a toast with the server's message.
- `save_list` needs nothing: `tiered_entries` ties a moved-unordered film at its tier's first unordered line, as any unordered film.
- `merge_film` and `set_unseen` need nothing: `how` rides along survivor-wins, and unseen deletes by film id.

## 5. API

- `POST /api/rank/move` body `{"film_id": int, "tier": int}` → 200 `{"film_id", "tier", "from_tier", "awaiting_order"}`; errors per M5 in the `{"error"}` shape every rank route uses.
- `GET /api/films/<id>` gains `rank_tier`, `rank_how`, `awaiting_order` (detail-only, M7).

## 6. Tests

- Unit: migration 025 rebuild (rows, `moved` accepted, `bogus` and a duplicate PK refused, FKs intact); `move_placement` keeps the row as `moved` and purges the session's order rows only, other sessions untouched, tiering log untouched; `rank_placement_for`; a moved placement dies on unseen and survives a merge; `tiered_entries` with a moved-unordered film.
- Feature `rank_move.feature`: the move leaves the old order and waits unordered, is the new tier's next candidate and is never re-seeded; a move into an unordered tier is not awaiting; a move invalidates undo; the five refusals; the stale order pair is refused; `rank_status` reads the order's own state.
- Web: the route's shape and refusals, the detail keys (and their absence on `/api/films`), 404 without a session, the non-object body; Playwright `test_move_tier_page.py` with its own server: the rank page recovers from a moved candidate, the drawer's tier row moves a film and lights Rank this, the row is absent for an unplaced film and an anchor move toasts.

## 7. Out of scope

Hand-placing an unplaced film (the Tiers tab's job); moving an anchor (swap first — the API exists, the UI is parked); the bulk seam merge; a rank-page browse view of the tiers (the saved list is that view); a session-scoped `set_unseen`; Phase B.

## 8. Documentation

`CLAUDE.md`'s tier-ranker bullet (the move, `how ∈ seed/compared/anchor/moved`, migration 025, the rank.js recovery); `docs/backlog.md` item 18; the ranking-pool spec's §4.6 cross-reference.
