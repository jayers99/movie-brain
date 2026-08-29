-- Curated lists: trust and the cross-list tally
-- (design docs/superpowers/specs/2026-08-29-list-trust-and-tally-design.md §3). The owner's
-- integer judgement of how much a list is worth counting; every existing list starts at 1,
-- which makes the weighted tally identical to a raw count until the owner sets an opinion.
BEGIN;
ALTER TABLE film_list ADD COLUMN trust INTEGER NOT NULL DEFAULT 1;
INSERT INTO schema_version (version) VALUES (16);
COMMIT;
