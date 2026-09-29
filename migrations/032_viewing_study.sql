-- Backlog 48 (the study mark, brief docs/superpowers/briefs/2026-09-29-study-mark/brief.md). One
-- mark on a VIEWING — `study`: there is a technique here to watch for a second time. It lives on
-- the line (the log's rule: everything hangs off the viewing); a film is "to study" when any of
-- its lines is marked, which is a read, never a column on films. Set by `viewings add --study`
-- or `viewings study VID`, cleared only by `viewings study VID --off`; a later viewing touches
-- no other line. One tag does not justify a table — a second tag, if one ever comes, is a
-- later migration.
BEGIN;
ALTER TABLE viewing ADD COLUMN study INTEGER NOT NULL DEFAULT 0;
INSERT INTO schema_version (version) VALUES (32);
COMMIT;
