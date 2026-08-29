-- Optional fourth column on the curated-list file format (design
-- docs/superpowers/specs/2026-08-28-list-supplied-ids-design.md §4). Records the
-- IMDb id a source claimed for a list entry, when it supplied one.
BEGIN;
ALTER TABLE film_list_entry ADD COLUMN tt_listed TEXT;
INSERT INTO schema_version (version) VALUES (14);
COMMIT;
