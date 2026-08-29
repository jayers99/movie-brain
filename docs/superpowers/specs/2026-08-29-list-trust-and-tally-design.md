# Curated lists: trust and the cross-list tally — design

**Date:** 2026-08-29 · **Status:** owner-confirmed on all three open questions; ready to plan. The third increment on [2026-08-28-curated-lists-design.md](2026-08-28-curated-lists-design.md), whose **§5.7** this finally delivers. All three earlier specs stay binding.

**Why now.** §5.7 was written when there were no lists, and deliberately deferred the tally while insisting v1 not preclude it. There are now three lists, **23 films on all three and 70 on two**, and the owner has a ranked ordering of list quality to fill a trust column with. A raw count of three lists is already less informative than a weighted one.

## 1. What §5.7 pre-committed us to, and what it costs now

Four constraints were locked in v1 so this increment would be a badge and a predicate rather than a rewrite. All four held:

| §5.7 constraint | Status |
|---|---|
| 1. Fetch membership in ONE query for the whole view | Held. `_LISTS_SQL` / `_lists_by_film` gains one column; still one query. |
| 2. `FilmView.lists` is a list of dicts, not a count | Held. The tally is `f.lists.length` client-side; no new field, no second query. |
| 3. Never denormalize a count onto `films` | Held, and it earns its keep immediately — "how many lists" now means "how many, weighted by trust", which a stored column would have frozen. |
| 4. Leave room for list quality | This document. Purely additive, as promised. |

## 2. Owner decisions (2026-08-29, do not relitigate)

| # | Question | Decision |
|---|---|---|
| T1 | How is trust modelled? | **Integer weight, `NOT NULL DEFAULT 1`.** Not a boolean, not Moviewise's rank stored directly. |
| T2 | What does the card badge show? | **The count** (`3 lists`), with the names and ranks in the drawer as they already are. Not the weighted score. |
| T3 | A filter chip now? | **Yes** — an "on 2+ lists" chip. |

**Why `DEFAULT 1` matters:** with every list at 1 the weighted tally is *identical* to the raw count, so the feature ships inert and only diverges as the owner expresses opinions. No list is ever silently worth zero, and no import has to know about trust.

**Why not Moviewise's rank in the schema:** it bakes one person's ordering into the data model and has no answer for a list they never ranked — including the Sight & Sound **2022** poll just imported, since the video ranks the **1992** poll. Trust is the owner's judgement about a list; the registry stores that, not its provenance.

## 3. Migration 016

```sql
BEGIN;
ALTER TABLE film_list ADD COLUMN trust INTEGER NOT NULL DEFAULT 1;
INSERT INTO schema_version (version) VALUES (16);
COMMIT;
```

Additive; SQLite permits `NOT NULL` on an added column when a default is given, so the three existing rows become `trust = 1` with no backfill statement.

## 4. Setting it — `movie-brain lists trust [SLUG] [N]`

- No arguments: print every list with its trust, ordered by trust descending then slug. This is also the answer to "which lists do I actually rate?"
- `SLUG N`: set one list's trust. `N` must be a non-negative integer; **0 is legal and means "keep it visible in the drawer but score it nothing"**, which is the boolean behaviour available inside the integer model.
- Unknown slug is an error naming the known ones. Nothing else writes this column — not `lists import`, not `lists create`, so a re-import never resets a judgement.

## 5. Read model

`_LISTS_SQL` selects `l.trust`; each dict in `FilmView.lists` becomes `{slug, name, curator, published, ordered, trust, rank, rank_label}`. Still one query for the whole view — §5.7 constraint 1, and the existing `set_trace_callback` test stays as written.

## 6. The badge (T2)

`app.js` renders a small badge on the film card when `f.lists.length > 0`, reading `3 lists` (`1 list` singular). It is derived client-side from data the view already carries — no new endpoint, no server change beyond §5. The drawer's "On lists:" row is unchanged and remains where the names, ranks and tie labels live.

Trust does not appear on the card. It orders the drawer's list line (highest trust first, then name) so the most-rated list is named first, and it is what a later weighted sort would use. Making the badge itself weighted was considered and declined by T2: a bare `27` needs explaining and means nothing until trust values are set.

## 7. The chip (T3)

Per CLAUDE.md, canned-filter thresholds and chip names live **only** in `domain/filters.py`, JS reads thresholds from `/api/config`, and `CHIP_PREDICATES` in `app.js` and the buttons in `index.html` stay in lockstep with `_PREDICATES`.

- `MULTI_LIST = 2` joins the threshold constants and is exported by `thresholds()` as `multi_list`.
- `_PREDICATES["multi_list"] = lambda v, _: len(v.lists) >= MULTI_LIST`.
- `CHIP_PREDICATES.multi_list = (f) => (f.lists || []).length >= state.cfg.canned_thresholds.multi_list`.
- One chip button in `index.html`, labelled "on 2+ lists".

Counting **lists**, not weighted trust, keeps the chip's meaning stable when trust changes — a film does not silently leave the shortlist because a list was downgraded. A weighted chip is a separate, later decision.

## 8. Out of scope

Sorting the table by tally or by weight · a per-list filter ("show me only Cahiers") · rank-order sort within a list · any further list import · repairing film #493's mis-keyed IMDb id (a real defect this corpus surfaced, tracked separately).

## 9. Gates (unchanged)

`uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`. Nothing here touches `domain/thumbprint.py`, `infrastructure/thumbprint_fetch.py`, the eval fixture, the four gates or the reconciliation policy — this increment is display and one registry column. 
