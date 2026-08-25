-- Thumbprint step 0 (spec 2026-08-25-thumbprint-resolver-design.md §3): claims.
-- A claim is one source's assertion about a work (film). Pure additive: no existing row
-- changes; `thumbprint backfill --apply` copies owned/criterion/metacritic evidence in.
-- films.title_norm is derived (grammar output, backfilled by the app); films.kind is
-- 'movie' until series keying (memo step 3+).
BEGIN;
CREATE TABLE claim (
    id              INTEGER PRIMARY KEY,
    film_id         INTEGER NOT NULL REFERENCES films(id),
    authority       TEXT    NOT NULL,
    value           TEXT    NOT NULL,
    title_ingested  TEXT    NOT NULL,
    year_claimed    INTEGER,
    edition_label   TEXT,
    edition_year    INTEGER,
    runtime_min     INTEGER,
    first_seen      TEXT    NOT NULL,
    UNIQUE (authority, value)
);
CREATE INDEX claim_film ON claim(film_id);
ALTER TABLE films ADD COLUMN title_norm TEXT;
ALTER TABLE films ADD COLUMN kind TEXT NOT NULL DEFAULT 'movie' CHECK (kind IN ('movie', 'series'));
INSERT INTO schema_version (version) VALUES (11);
COMMIT;
