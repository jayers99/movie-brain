-- Backlog item 9 (shipped in M3): user-set "needs revisit" flag for factually suspect films.
-- Watchlist pattern: user-response data, drawer toggle is the only UI writer, never touched
-- by sync/importers; the repair/review CLI clears it when the film is resolved.
BEGIN;
CREATE TABLE needs_revisit (
    film_id   INTEGER PRIMARY KEY REFERENCES films(id),
    marked_on TEXT NOT NULL,
    note      TEXT
);
INSERT INTO schema_version (version) VALUES (9);
COMMIT;
