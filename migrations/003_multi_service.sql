-- Phase 1: GUID identity + services model (spec: docs/superpowers/specs/2026-08-23-phase1-schema-redesign-design.md).
-- Runs on init_db's plain sqlite3 connection, where foreign_keys is OFF — so parent
-- tables can be dropped and recreated while child tables keep referencing them by name.

CREATE TABLE movie_service (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('svod', 'store')),
    subscribed INTEGER NOT NULL DEFAULT 0,
    region TEXT NOT NULL DEFAULT 'US'
);
INSERT INTO movie_service (slug, name, kind, subscribed) VALUES
    ('criterion', 'Criterion Channel', 'svod', 1),
    ('apple-tv-plus', 'Apple TV+', 'svod', 1),
    ('apple-tv-store', 'Apple TV Store (iTunes)', 'store', 1),
    ('max', 'HBO Max', 'svod', 1),
    ('peacock', 'Peacock', 'svod', 1),
    ('prime-video', 'Prime Video', 'svod', 1),
    ('mubi', 'MUBI', 'svod', 0),
    ('bfi-player-classics', 'BFI Player Classics', 'svod', 0);

CREATE TABLE service_provider (
    tmdb_provider_id INTEGER PRIMARY KEY,
    service_slug TEXT NOT NULL REFERENCES movie_service(slug),
    label TEXT NOT NULL
);
-- Amazon-channel ids (1825, 201, 287) and GB BFI Player (224) deliberately excluded.
INSERT INTO service_provider (tmdb_provider_id, service_slug, label) VALUES
    (258, 'criterion', 'Criterion Channel'),
    (350, 'apple-tv-plus', 'Apple TV+'),
    (2, 'apple-tv-store', 'Apple TV'),
    (1899, 'max', 'HBO Max'),
    (386, 'peacock', 'Peacock Premium'),
    (387, 'peacock', 'Peacock Premium Plus'),
    (9, 'prime-video', 'Amazon Prime Video'),
    (11, 'mubi', 'MUBI');

-- Rebuild films with a NOT NULL guid; existing rows get a SQL-generated UUIDv4.
CREATE TABLE films_new (
    id INTEGER PRIMARY KEY,
    guid TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    year INTEGER,
    director TEXT,
    key TEXT NOT NULL UNIQUE
);
INSERT INTO films_new (id, guid, title, year, director, key)
SELECT id,
       lower(hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' ||
             substr(hex(randomblob(2)), 2) || '-' ||
             substr('89ab', (abs(random()) % 4) + 1, 1) || substr(hex(randomblob(2)), 2) ||
             '-' || hex(randomblob(6))),
       title, year, director, key
FROM films;
DROP TABLE films;
ALTER TABLE films_new RENAME TO films;

CREATE TABLE external_ids (
    film_id INTEGER NOT NULL REFERENCES films(id),
    authority TEXT NOT NULL,
    value TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (film_id, authority),
    UNIQUE (authority, value)
);
-- Criterion's native id is its film URL. OR IGNORE: a duplicate URL should skip
-- one row, not abort the whole migration.
INSERT OR IGNORE INTO external_ids (film_id, authority, value, first_seen)
SELECT film_id, 'criterion', url, first_seen FROM listings WHERE source = 'criterion';

-- Rebuild listings so source becomes a foreign key into the registry.
CREATE TABLE listings_new (
    film_id INTEGER NOT NULL REFERENCES films(id),
    source TEXT NOT NULL REFERENCES movie_service(slug),
    url TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    leaving_date TEXT,
    PRIMARY KEY (film_id, source)
);
INSERT INTO listings_new SELECT film_id, source, url, first_seen, last_seen, leaving_date FROM listings;
DROP TABLE listings;
ALTER TABLE listings_new RENAME TO listings;
CREATE INDEX listings_source_last_seen ON listings(source, last_seen);

INSERT INTO schema_version (version) VALUES (3);
