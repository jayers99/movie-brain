# Order the top tier — strict order inside tier 1 by binary insertion

**Date:** 2026-09-13 · **Status:** implemented 2026-09-13 (plan docs/superpowers/plans/2026-09-13-order-top-tier.md) · **Extends:** the tier ranker (`2026-09-13-tier-ranker-design.md`, D6's deferral and backlog item 16). **Opens:** a second mode on `/rank`, three tables, and bare ranks inside the ranker's list.

## 1. Goal

The tier ranker stops at five tiers by design (D6). After the first live session the owner has 93 films in tier 1, 29 of them seeded from a score of 10, all saved tied at `=1`. This feature orders that tier strictly: every tier 1 film gets a rank of its own, 1 to k, and the saved `my-owned-tiers` list shows it. The mechanism is the same side-by-side pair with one click per verdict, but the search is a **binary insertion** into the order built so far rather than a search against fixed anchors. About log₂ of the ordered count per film: roughly 470 clicks for 93, more than the tiering cost per film, which is the price of a strict order the owner chose knowingly (§2, O1).

Nothing here touches keying, matching, sync, `my_ratings`, or the tiering's own tables and search.

## 2. Decisions (owner rulings, 2026-09-13)

| # | Ruling | Evidence / cost if wrong |
|---|--------|--------------------------|
| O1 | **Order the whole tier**, not a top slice. | Alternatives costed: split tier 1 once then order the top half (~300 clicks), order a top 20 (~70 plus a way to nominate the 20), or leave it tied. The owner took the full order at ~470 clicks. Resumable, so the cost is spread over sittings. |
| O2 | **The tier being ordered is the live session's tier 1**, not the saved list's snapshot. | A film tiered into tier 1 later joins the order queue on the next request at the same cost as any other film; the order can never disagree with the tiering. A snapshot would go stale the moment the 135 still-queued films start landing. |
| O3 | **A mode switch on `/rank`**: two tabs, "Tiers" and "Order tier 1", same pair layout, keys, Undo and Save. | One page, one script, the pair component reused. A separate page duplicates the header and the save; unlocking only after tiering is done blocks the owner today. |
| O4 | **No ties**: `Better` on either side, nothing else. | Every click is a real bit; the insertion is exactly log₂ per film; the save is a plain 1 to k. A `Same` would end probes early with a weaker claim and spread ties into bands, returning the tier to `=N` labels. Consistent with the tiering's D9. |
| O5 | **Binary insertion with bounds derived from the log.** No stored lo/hi; every verdict is "candidate better/worse than film X", and the bounds are recomputed per request from where those X films sit now. | Same state-free discipline as the tiering (§4.2 there). Removals are safe by construction (§4.3 here). Merge sort was costed at ~500 clicks and is awkward mid-merge; Elo answers a different question and the tiering spec ruled it out. |
| O6 | **`Pass` defers; there is no `Have not seen` in order mode.** | A tier 1 film is one the owner has already judged. The drawer's Unseen toggle remains the way to retract that judgement, and §4.4 says what it does to the order. |
| O7 | **The first film into an empty order takes position 1 with no click.** | There is nothing to compare it with. |
| O8 | **One undo slot for the page.** `rank_session.last_action` gains a `mode` key; Undo reverses whichever click was last in either mode. | Two slots would let a tiering undo run after an order click had already assumed the placement (§4.4). |
| O9 | **The `tier` column is stored but the UI exposes tier 1 only.** | Costs nothing now and spares a migration if tier 2 is ever ordered. Not a feature: no route or tab takes a tier. Tier 2 exposed 2026-09-13, ranking-pool spec P5; every tier (1–5) exposed 2026-09-15 by widening `ORDER_TIERS` alone. |

## 3. Data model (migration 023)

Three tables beside the six from 022. All are per session and film-scoped, and `merge_film` moves each one survivor-wins exactly as it moves the 022 tables.

```sql
CREATE TABLE rank_order (                      -- the result: one row per ordered film, positions dense 1..k per tier
    session_id INTEGER NOT NULL REFERENCES rank_session(id),
    tier       INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    film_id    INTEGER NOT NULL REFERENCES films(id),
    position   INTEGER NOT NULL CHECK (position >= 1),
    ordered_on TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id),
    UNIQUE (session_id, tier, position)
);
CREATE TABLE rank_order_comparison (           -- append-only log; the search's ONLY state (§4.1)
    id            INTEGER PRIMARY KEY,
    session_id    INTEGER NOT NULL REFERENCES rank_session(id),
    tier          INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    film_id       INTEGER NOT NULL REFERENCES films(id),     -- the candidate
    other_film_id INTEGER NOT NULL REFERENCES films(id),     -- the ordered film it was shown against
    verdict       TEXT    NOT NULL CHECK (verdict IN ('better', 'worse')),
    decided_on    TEXT    NOT NULL
);
CREATE INDEX rank_order_comparison_film ON rank_order_comparison(session_id, film_id, id);
CREATE TABLE rank_order_deferral (             -- an order-mode Pass: "not now", queued last (§4.2)
    session_id  INTEGER NOT NULL REFERENCES rank_session(id),
    film_id     INTEGER NOT NULL REFERENCES films(id),
    deferred_on TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id)
);
INSERT INTO schema_version (version) VALUES (23);
```

Why not reuse the 022 tables: `rank_comparison.anchor_tier` and its check constraint mean "which tier's anchor", which an insertion probe is not; `rank_deferral` is the tiering queue's, and a tier 1 placement undone in tiering must not return to that queue carrying an order-mode deferral. `rank_order.position` is dense: inserting at p runs one `UPDATE … SET position = position + 1 WHERE position >= p`; removing compacts the same way. Ninety-odd rows make this trivially cheap.

`rank_session` is unchanged in shape. The order lives inside the open tiering session (its `id`, its `seed`), because the tier it orders is that session's tier 1.

## 4. The algorithm (`domain/rank.py`, pure)

### 4.1 Binary insertion, bounds derived from the log

`order_step(order, verdicts) -> Ask(other_film_id) | Insert(slot)`, where `order` is the tier's film ids by position (index 0 = position 1) and `verdicts` the candidate's logged `(other_film_id, verdict)` pairs in log order. Slots are the k+1 gaps of a k-film order, numbered 0..k.

- Start with `lo = 0`, `hi = len(order)`.
- For each verdict against a film at index i: `better` (the candidate is better than that film) caps the slot, `hi = min(hi, i)`; `worse` floors it, `lo = max(lo, i + 1)`.
- A verdict against a film not in `order` is ignored (§4.3 says why one can exist only transiently).
- If `lo == hi`: `Insert(lo)`. Otherwise probe the midpoint, `Ask(order[(lo + hi) // 2])`.
- `lo > hi` cannot arise (§4.3). If it does, the log is corrupt and the function raises `ValueError`, exactly as `next_step` does for an illegal sequence.

An empty order gives `Insert(0)` on the first request with no verdict logged (O7).

### 4.2 The queue

Derived per request, never stored: the session's tier 1 placements (`rank_placement.tier = 1`, whatever `how`) minus films already in `rank_order`, minus disposed films, minus unseen films (a placement is deleted when a film goes unseen, so this is belt and braces). Order: films with at least one order verdict first (mid-insertion, so a refresh lands on the same pair), then the session's seeded shuffle by `queue_key(seed, film_id)`, deferred films last by `(deferred_on, film_id)`. `order_queue` is reused with the order-mode deferral map.

### 4.3 Why the bounds cannot cross

Two facts hold at all times. **Insertion never reorders existing films**: inserting at a slot shifts positions but preserves every pairwise order among films already placed, so a verdict made against film X when X was at index i still means the same thing when X is at index j. **Removal deletes every verdict naming the removed film, on either side** (§4.4): when X leaves the order, the rows where X was the candidate AND the rows where X was `other_film_id` are deleted, in every session. So every verdict that survives was made against a film still in the order, in a relative order that has not changed, and a candidate's verdicts stay mutually consistent. Re-adding X later (unmarked from the drawer, re-tiered, re-inserted) starts from no verdicts on either side.

The one transient case is a pair served, then X removed from the drawer, then the click arriving: the verdict route re-derives the current pair and answers 409 (stale) rather than logging a verdict against an absent film.

### 4.4 Removal, undo and the tiering

- **Unseen from the drawer** (`set_unseen`): in addition to today's deletion of the film's `rank_placement` and `rank_comparison` rows in every session, delete its `rank_order` row (compacting positions), every `rank_order_comparison` row naming it as candidate OR other, and its `rank_order_deferral` row. An unseen film's clicks, and clicks against it, must audit nothing.
- **Undo** (O8): `last_action` gains `mode: "tiers" | "order"`. Order-mode kinds: `order_verdict` (deletes the comparison row; if that verdict completed an insertion, `inserted: true` and the `rank_order` row is deleted with positions compacted, the film leading the queue again at once) and `order_defer` (deletes the deferral). Tiering kinds are unchanged. Because there is one slot, a tier 1 placement cannot be undone once any order click has followed it — so an ordered film never loses its placement through undo. Undoing a tier 1 placement in tiers mode also removes the film from `rank_order` — a film free-inserted on read has no order verdicts and, undo being one level, nothing can have been probed against it.
- **A film placed into tier 1 later** joins the queue on the next order request (O2). Nothing to do.
- **`merge_film`** moves the three tables survivor-wins. If both loser and survivor hold a `rank_order` row in one session, the loser's is dropped and the survivor's position stands; positions are compacted after the move. The loser's order comparisons are handled per column: as candidate, survivor-wins per (session, candidate) — the loser's rows are dropped when the survivor already holds any in that session, else moved; as the other film, every row naming the loser is deleted, exactly as a removed film's are — a re-point would change the verdict's index whenever the two films sat at different positions (final-review ruling 2026-09-13: order [S, D, E, L], a candidate worse than D and better than L, merge L into S: the re-pointed row said better-than-S at index 0 and crossed the bounds); a moved candidate row that now compares the survivor with itself is deleted.
- **Tombstone** deletes nothing (collectors never delete); the disposed guard keeps the film out of the queue and out of the served order.

### 4.5 The saved list (`tiered_entries`)

`tiered_entries(placed, order)` where `order` maps film id to position for the ordered films. Tier 1 lines come first: the ordered films by position, lines 1..k, `rank_label` NULL (bare); then the still-unordered tier 1 films by title, tied at `=k+1` (a single unordered film is bare, as a tier of one is today); then tiers 2 to 5 exactly as today. When no film is ordered, the output is byte-for-byte what the ranker writes today. Save is the same `POST /api/rank/save` into the same slug; the dashboard's list picker and drawer already render bare and tied labels (migration 015), so nothing on the dashboard changes.

## 5. The screen (`/rank`)

1. **Tabs** in the header, `Tiers` and `Order tier 1`, the active one recorded in the URL hash (`#order`) so a reload stays put. Both are live at once; switching does not touch either mode's state.
2. **The pair** in order mode reuses `sideHtml`: candidate left, headed `Candidate`; the probe film right, headed `Position N of k`. Same posters and memory prompts.
3. **Controls**: `Better` above each film, `Pass` centred, `Undo` in the header. No `Have not seen` and no title trigger. Keys: `←` / `→` Better, `space` Pass, `U` Undo; `1` and `2` do nothing in this mode.
4. **Progress line**: `ordered · remaining`; no tier tally.
5. **Done**: "Every tier 1 film is ordered. Save the list above." A film tiered into tier 1 later reopens the pair on the next request.
6. **No session**: the Order tab shows "Start a tiering session first" and the setup card stays on the Tiers tab.

The page keeps its one promise queue: every click and keydown in either mode is serialised through it.

## 6. API

| Route | Does |
|---|---|
| `GET /api/rank/order` | The order state for the open `owned` session: `tier: 1`, `ordered`, `remaining`, `can_undo`, and either `pair: {candidate, other, position, of, asked}` or `done: true`. 404 with no open session, through the same helper every other rank route uses. |
| `POST /api/rank/order/verdict` | `{film_id, other_film_id, verdict}`. Appends the log row; inserts when §4.1 says the slot is pinned. 409 if the pair is not the current one (stale page, or the other film removed since it was served). |
| `POST /api/rank/order/pass` | `{film_id}`. Defers the candidate. 409 if it is not the current candidate. |
| `POST /api/rank/undo` | Unchanged route; reverses the last action in either mode (§4.4). |
| `POST /api/rank/save` | Unchanged route; the entries now carry tier 1's order (§4.5). |

The two body-taking routes share `_json_object()` for their 400 shape check like the existing five. `application/rank.py` gains `order_state`, `order_verdict`, `order_pass`; `undo` and `save_list` learn the order. The application layer still imports no `sqlite3`.

## 7. Tests

- `tests/unit/test_rank.py`: `order_step` on an empty order (`Insert(0)`), one film (ask it, then insert at 0 or 1), a five-film order probing midpoints to a pinned slot in three verdicts, a verdict against a film not in the order ignored, crossed bounds raising; `tiered_entries` with an order (bare 1..k, `=k+1` for the rest, tiers 2–5 untouched, and identical output to today when the order is empty).
- `tests/features/rank.feature` + step defs: order three tier 1 films to a definite order; pass defers to the back; undo reverses an order verdict and an insertion; unseen from the drawer removes an ordered film, compacts positions and deletes the verdicts naming it; a film placed into tier 1 after ordering started appears in the order queue; save writes 1..k then `=k+1`; one undo slot across modes.
- `tests/web/test_rank_page.py`: switch to the Order tab, insert one film by keyboard, save, and see a bare rank in the dashboard picker's list.
- `tests/unit` repository: `merge_film` moves the three tables survivor-wins and compacts.

## 8. Out of scope

Ordering any tier but tier 1 (O9 stores the column, nothing reads a tier from the owner); ties (O4); re-running insertions after the tiering changes a placement; a viewer for the order log; writing `my_ratings`; any change to keying, matching or sync.

## 9. Documentation

`CLAUDE.md`'s tier-ranker bullet gains the order (the three tables, the log-derived insertion, the one undo slot, the save's bare ranks, the drawer-unseen cascade); `docs/backlog.md` item 16 is ticked when shipped, with the click count actually spent.
