-- Phase 3: TMDB availability (spec: docs/superpowers/specs/2026-08-23-phase3-tmdb-availability-design.md).
-- Additive only. tmdb caches the one-shot match verdict (found=0 is never retried by sync)
-- and the latest raw US watch-providers payload; the TMDB numeric id itself lives in
-- external_ids (authority 'tmdb'), never here.
BEGIN;
CREATE TABLE tmdb (
    film_id INTEGER PRIMARY KEY REFERENCES films(id),
    found INTEGER NOT NULL,
    looked_up TEXT NOT NULL,
    providers_checked_at TEXT,
    payload TEXT
);
INSERT INTO schema_version (version) VALUES (5);
COMMIT;
