-- Tied ranks (design docs/superpowers/specs/2026-08-28-tied-ranks-design.md §2). Separates
-- position (film_list_entry.rank, unique 1..N, what makes an entry addressable) from the
-- rank as printed (ties, `=` markers), which this column carries. Additive; no backfill —
-- the two existing lists print 1..100 in line order, so their rank_label stays NULL.
BEGIN;
ALTER TABLE film_list_entry ADD COLUMN rank_label TEXT;
INSERT INTO schema_version (version) VALUES (15);
COMMIT;
