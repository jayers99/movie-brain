# Curated lists: tied ranks — design

**Date:** 2026-08-28 · **Status:** ready to plan. A second increment on [2026-08-28-curated-lists-design.md](2026-08-28-curated-lists-design.md), alongside [the supplied-ids increment](2026-08-28-list-supplied-ids-design.md). Both stay binding; this document changes only what it names.

**Why:** the Sight & Sound polls cannot be imported at all today. `film_list_entry` has `PRIMARY KEY (list_slug, rank)` and `parse_list_file` rejects a duplicate rank — both written when rank happened to be unique. On the BFI 2022 page, **233 of 273 rank tokens are ties**: rank `=243` covers 22 films, `=225` covers 18, `=211` covers 14, and ~250 films share only ~80 distinct rank values. Ties are not an edge case on a critics' poll; they are most of the list.

## 1. The shape

Two things were conflated and need separating:

- **position** — where the entry sits in the list. Unique, 1..N, the thing that makes an entry addressable.
- **rank as printed** — what the curator published. May tie, may carry an `=` marker, and is not a number at all in the general case.

`film_list_entry.rank` keeps the first meaning, which is what the primary key and every existing query already assume. A new nullable `rank_label TEXT` carries the second.

**This deliberately avoids repointing the primary key at a new `position` column.** That would mean a table rebuild — the riskiest migration shape on a live database — for exactly the same outcome. `ALTER TABLE ADD COLUMN` is additive, instant, and needs no backfill.

## 2. Migration 015

```sql
BEGIN;
ALTER TABLE film_list_entry ADD COLUMN rank_label TEXT;
INSERT INTO schema_version (version) VALUES (15);
COMMIT;
```

Cahiers' and Bergan's 200 rows keep `rank_label IS NULL`, because for them the printed rank and the position are the same string.

## 3. File format — column one becomes the rank as printed

```
=243	Born in Flames	Lizzie Borden
=243	Pandora's Box	G.W. Pabst
=243	Sullivan's Travels	Preston Sturges
```

The first cell is what the source printed. The entry's `rank` is its **line order** among data rows, 1..N. `rank_label` is stored only when the printed cell differs from `str(rank)` — so `1`, `2`, `3` store `NULL` and the two existing files parse byte-identically to how they parse today.

This keeps the verbatim principle the format already follows for titles and directors: the file records what the curator wrote, and the derived value is derived.

### The check that replaces contiguity

Deriving position from line order gives up the current parser's real safety net — contiguous unique ranks catch a shuffled or truncated file. It is replaced by a stricter rule:

**The numeric part of the labels must be non-decreasing down the file.**

`1, 2, 3, …` passes. `=243, =243, =225` fails. This permits ties, forbids shuffling, and catches the specific mistake this feature invites: the BFI page defaults to listing **250 → 1**, so an extraction that forgets to reverse comes out backwards and is rejected rather than imported upside down.

A label parses as an optional leading `=`, then a positive integer, then nothing else. Anything else is a `ListFileError`, same as a malformed id.

## 4. Read model and display

`_LISTS_SQL` selects `e.rank_label` alongside `e.rank`; `FilmView.lists` entries become `{slug, name, curator, published, ordered, rank, rank_label}`. Still **one query for the whole view** — the standing §5.7 constraint, unchanged.

The drawer renders `rank_label ?? rank`, so a tied film reads honestly:

```
On lists:  Sight & Sound 2022 #=243, Cahiers du Cinéma 2008 #3
```

An unordered list still renders with no rank at all. The scorecard's `#N` prefix likewise shows the label when there is one, so the card the owner reads matches the poll.

## 5. What does NOT change

The four gates, the reconciliation policy, the two-verb split, `film_rank_on_list`'s duplicate-entry guard (it answers in positions, which stay unique), and every existing scenario. A tie is a display fact, not an identity fact.

## 6. Out of scope

Extracting or importing any Sight & Sound poll — that is the next step and needs its own rehearsal. The `trust`/weight column and the weighted cross-list tally. Re-ordering an imported list.

## 7. Gates (unchanged)

`uv run pytest` · `uv run ruff check .` · `uv run mypy` · `uv run python scripts/thumbprint_benchmark.py --assert` (baseline **n=571 / WRONG=0 / 92.0% over 526**) · `uv run python scripts/matching_benchmark.py --assert-dominance`. Nothing here touches `domain/thumbprint.py` or `infrastructure/thumbprint_fetch.py`, so the thumbprint gate must not move.
