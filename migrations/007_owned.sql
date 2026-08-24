-- Apple TV owned films (spec: docs/superpowers/specs/2026-08-23-apple-tv-owned-design.md).
-- Additive only. owned is possession data on the watchlist pattern — written only by
-- `movie-brain owned import`, never by sync; rows are permanent (never unmarked).
BEGIN;
CREATE TABLE owned (
    film_id        INTEGER PRIMARY KEY REFERENCES films(id),
    source         TEXT NOT NULL DEFAULT 'apple-tv',
    first_imported TEXT NOT NULL
);
INSERT INTO schema_version (version) VALUES (7);
COMMIT;
