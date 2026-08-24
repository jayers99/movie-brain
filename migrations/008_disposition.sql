-- M3: identity dispositions (spec: docs/superpowers/specs/2026-08-23-matching-overhaul-design.md, M3).
-- Films are immutable and never deleted; a duplicate or wrongly-created film gets a
-- disposition row instead. kind='merged' aliases the losing identity onto survivor_id
-- (its title still matches, but resolves to the survivor); kind='tombstoned' hides it and
-- blocks every collector from re-creating it. Only human-confirmed repair verbs write here.
BEGIN;
CREATE TABLE film_disposition (
    film_id     INTEGER PRIMARY KEY REFERENCES films(id),
    kind        TEXT NOT NULL CHECK (kind IN ('merged', 'tombstoned')),
    survivor_id INTEGER REFERENCES films(id),
    note        TEXT,
    created_at  TEXT NOT NULL,
    CHECK ((kind = 'merged') = (survivor_id IS NOT NULL))
);
INSERT INTO schema_version (version) VALUES (8);
COMMIT;
