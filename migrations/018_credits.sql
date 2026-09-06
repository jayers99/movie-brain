-- Power search, Plan A (design docs/superpowers/specs/2026-09-06-power-search-design.md §4, D3).
-- Cast, crew, characters and keywords from TMDB, stored as ROWS rather than a payload, because
-- the owner's spelling requirement needs ~60k names to be trigram-indexable: a misspelled
-- name is corrected against `person_fts` BEFORE the query runs, which a JSON blob forecloses.
-- `person` is NOT an identity (no guid, not a KEY_AUTHORITY); `tmdb_person_id` is the join.
-- `job`/`department`/`character` are NOT NULL DEFAULT '' so the UNIQUE actually dedups —
-- SQLite treats two NULLs as distinct in a unique index.
-- The three FTS5 tables are external-content indexes kept in step by triggers; the base
-- tables are the truth and the indexes can be rebuilt with INSERT INTO x(x) VALUES('rebuild').
-- `film_text` exists only because its columns come from three sources (films, tmdb_facts,
-- the OMDb payload) and an external-content FTS index needs ONE content table.
BEGIN;

CREATE TABLE person (
    id              INTEGER PRIMARY KEY,
    tmdb_person_id  INTEGER NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    first_seen      TEXT    NOT NULL
);

CREATE TABLE film_credit (
    film_id     INTEGER NOT NULL REFERENCES films(id),
    person_id   INTEGER NOT NULL REFERENCES person(id),
    kind        TEXT    NOT NULL CHECK (kind IN ('cast', 'crew')),
    job         TEXT    NOT NULL DEFAULT '',
    department  TEXT    NOT NULL DEFAULT '',
    character   TEXT    NOT NULL DEFAULT '',
    ord         INTEGER NOT NULL,
    UNIQUE (film_id, person_id, kind, job, character)
);
CREATE INDEX film_credit_person ON film_credit(person_id);
CREATE INDEX film_credit_film   ON film_credit(film_id);

CREATE TABLE film_keyword (
    film_id  INTEGER NOT NULL REFERENCES films(id),
    keyword  TEXT    NOT NULL,
    PRIMARY KEY (film_id, keyword)
);

CREATE TABLE film_text (
    film_id   INTEGER PRIMARY KEY REFERENCES films(id),
    title     TEXT NOT NULL,
    overview  TEXT,
    plot      TEXT
);

ALTER TABLE tmdb_facts ADD COLUMN overview           TEXT;
ALTER TABLE tmdb_facts ADD COLUMN tagline            TEXT;
ALTER TABLE tmdb_facts ADD COLUMN genres             TEXT;
ALTER TABLE tmdb_facts ADD COLUMN credits_fetched_on TEXT;

CREATE VIRTUAL TABLE person_fts    USING fts5(name,      content='person',      content_rowid='id',      tokenize='trigram');
CREATE VIRTUAL TABLE character_fts USING fts5(character, content='film_credit', content_rowid='rowid',   tokenize='trigram');
CREATE VIRTUAL TABLE film_text_fts USING fts5(title, overview, plot, content='film_text', content_rowid='film_id', tokenize='unicode61');

CREATE TRIGGER person_ai AFTER INSERT ON person BEGIN
    INSERT INTO person_fts(rowid, name) VALUES (new.id, new.name);
END;
CREATE TRIGGER film_credit_ai AFTER INSERT ON film_credit BEGIN
    INSERT INTO character_fts(rowid, character) VALUES (new.rowid, new.character);
END;
CREATE TRIGGER film_credit_ad AFTER DELETE ON film_credit BEGIN
    INSERT INTO character_fts(character_fts, rowid, character) VALUES ('delete', old.rowid, old.character);
END;
CREATE TRIGGER film_text_ai AFTER INSERT ON film_text BEGIN
    INSERT INTO film_text_fts(rowid, title, overview, plot) VALUES (new.film_id, new.title, new.overview, new.plot);
END;
CREATE TRIGGER film_text_ad AFTER DELETE ON film_text BEGIN
    INSERT INTO film_text_fts(film_text_fts, rowid, title, overview, plot) VALUES ('delete', old.film_id, old.title, old.overview, old.plot);
END;
CREATE TRIGGER film_text_au AFTER UPDATE ON film_text BEGIN
    INSERT INTO film_text_fts(film_text_fts, rowid, title, overview, plot) VALUES ('delete', old.film_id, old.title, old.overview, old.plot);
    INSERT INTO film_text_fts(rowid, title, overview, plot) VALUES (new.film_id, new.title, new.overview, new.plot);
END;

INSERT INTO schema_version (version) VALUES (18);
COMMIT;
