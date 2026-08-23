-- Phase 4: watchlist + availability transitions
-- (spec: docs/superpowers/specs/2026-08-23-phase4-watchlist-alerts-design.md).
-- Additive only. watchlist is my-response data (like my_ratings), not collector data.
-- availability_transitions is append-only: one row per time a film newly appears
-- (insert or reappearance) on a service; collectors never delete. No backfill —
-- existing listings rows are upserts, not inserts, so migration causes no event flood.
BEGIN;
CREATE TABLE watchlist (
    film_id  INTEGER PRIMARY KEY REFERENCES films(id),
    added_on TEXT NOT NULL
);
CREATE TABLE availability_transitions (
    id          INTEGER PRIMARY KEY,
    film_id     INTEGER NOT NULL REFERENCES films(id),
    source      TEXT NOT NULL,
    appeared_on TEXT NOT NULL
);
CREATE INDEX idx_transitions_appeared ON availability_transitions(appeared_on);
INSERT INTO schema_version (version) VALUES (6);
COMMIT;
