-- Phase 2: Metacritic Mode A (spec: docs/superpowers/specs/2026-08-23-phase2-metacritic-mode-a-design.md).
-- Additive only. metacritic stages parsed browse-walk cards (slug = Metacritic's native id;
-- also the Phase 5 Mode B foundation). match_review is the durable review queue for match
-- anomalies — collectors never delete; unresolved rows are recomputed by each match run.
BEGIN;
CREATE TABLE metacritic (
    slug TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    year INTEGER,
    score INTEGER,
    rank INTEGER NOT NULL,
    page INTEGER NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE match_review (
    id INTEGER PRIMARY KEY,
    authority TEXT NOT NULL,
    film_id INTEGER REFERENCES films(id),
    value TEXT,
    reason TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0
);
INSERT INTO schema_version (version) VALUES (4);
COMMIT;
