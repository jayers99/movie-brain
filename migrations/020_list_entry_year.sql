-- Curated lists: the year AS PRINTED, fifth column of the list file (backlog item 15's lesson).
-- A title-and-year source that prints no director (List Obsession's slapstick 200, Rotten
-- Tomatoes' noir 100) left the resolver with nothing to separate Laura 1944 from Laura 1979 —
-- 81 of 100 entries came back `weak`. A curator's printed year is the work's year, not a
-- remaster date, so `resolve_entry` passes it through as a DATABASE-class year and it
-- corroborates exactly as the director does. Stored beside `tt_listed` because phase 2
-- (`lists create`) re-resolves from the STORED entry, never the file. Additive, no backfill:
-- every existing list printed no year and keeps NULL throughout.
ALTER TABLE film_list_entry ADD COLUMN year_listed INTEGER;
INSERT INTO schema_version (version) VALUES (20);
