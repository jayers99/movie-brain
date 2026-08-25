-- Data audit (spec 2026-08-24-data-audit-design.md): read-only consistency flags, an
-- append-only human verdict ledger, and a cache of the TMDB facts the checks compare against.
-- audit_flags is a derived report (replaced each run); audit_verdict is never updated/deleted
-- and the dashboard verdict endpoint is its only writer; sync/repair never touch either.
BEGIN;
CREATE TABLE audit_flags (
    film_id INTEGER NOT NULL REFERENCES films(id),
    reason  TEXT    NOT NULL,
    detail  TEXT    NOT NULL,
    score   INTEGER NOT NULL,
    run_on  TEXT    NOT NULL,
    PRIMARY KEY (film_id, reason)
);
CREATE TABLE audit_verdict (
    id        INTEGER PRIMARY KEY,
    film_id   INTEGER NOT NULL REFERENCES films(id),
    verdict   TEXT    NOT NULL,
    reasons   TEXT    NOT NULL,
    note      TEXT,
    marked_on TEXT    NOT NULL
);
CREATE INDEX audit_verdict_film ON audit_verdict(film_id, id);
CREATE TABLE tmdb_facts (
    film_id        INTEGER PRIMARY KEY REFERENCES films(id),
    tmdb_id        INTEGER NOT NULL,
    imdb_id        TEXT,
    title          TEXT    NOT NULL,
    original_title TEXT    NOT NULL,
    alt_titles     TEXT    NOT NULL,
    release_year   INTEGER,
    runtime_min    INTEGER,
    fetched_on     TEXT    NOT NULL
);
INSERT INTO schema_version (version) VALUES (10);
COMMIT;
