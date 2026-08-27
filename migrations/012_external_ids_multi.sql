-- Thumbprint T2 (spec 2026-08-26-thumbprint-t2-editions-design.md §3): a work may hold several
-- native ids from one CLAIM authority (metacritic slugs for each cut, apple titles for each
-- edition). tmdb/imdb stay single per film BY POLICY (Repository.set_external_id), not by
-- schema. UNIQUE(authority, value) — the dedup guard — is unchanged. SQLite cannot drop a
-- PK, so this is a table rebuild inside one transaction.
BEGIN;
CREATE TABLE external_ids_new (
    film_id INTEGER NOT NULL REFERENCES films(id),
    authority TEXT NOT NULL,
    value TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (film_id, authority, value),
    UNIQUE (authority, value)
);
INSERT INTO external_ids_new (film_id, authority, value, first_seen)
    SELECT film_id, authority, value, first_seen FROM external_ids;
DROP TABLE external_ids;
ALTER TABLE external_ids_new RENAME TO external_ids;
CREATE INDEX external_ids_film ON external_ids(film_id);
INSERT INTO schema_version (version) VALUES (12);
COMMIT;
