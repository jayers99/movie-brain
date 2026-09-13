-- Tier ranker (spec docs/superpowers/specs/2026-09-13-tier-ranker-design.md §3). Six tables:
-- a session per source, its five anchors, one placement per film (the whole result), an
-- append-only click log that is never read to compute a tier, a "not now" deferral, and the
-- durable `unseen` bucket on the watchlist pattern (drawer toggle + the page's pass are its
-- only writers). `last_action` is the one-level undo record (§4.4). `how = 'anchor'` marks a
-- film swapped in as an anchor while unplaced (§4.5).
BEGIN;
CREATE TABLE rank_session (
    id          INTEGER PRIMARY KEY,
    source      TEXT    NOT NULL,
    seed        INTEGER NOT NULL,
    started_on  TEXT    NOT NULL,
    finished_on TEXT,
    list_slug   TEXT REFERENCES film_list(slug),
    last_action TEXT
);
CREATE UNIQUE INDEX rank_session_open ON rank_session(source) WHERE finished_on IS NULL;

CREATE TABLE rank_anchor (
    session_id INTEGER NOT NULL REFERENCES rank_session(id),
    tier       INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    film_id    INTEGER REFERENCES films(id),
    set_on     TEXT    NOT NULL,
    PRIMARY KEY (session_id, tier)
);

CREATE TABLE rank_placement (
    session_id INTEGER NOT NULL REFERENCES rank_session(id),
    film_id    INTEGER NOT NULL REFERENCES films(id),
    tier       INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    how        TEXT    NOT NULL CHECK (how IN ('seed', 'compared', 'anchor')),
    placed_on  TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id)
);

CREATE TABLE rank_comparison (
    id              INTEGER PRIMARY KEY,
    session_id      INTEGER NOT NULL REFERENCES rank_session(id),
    film_id         INTEGER NOT NULL REFERENCES films(id),
    anchor_film_id  INTEGER NOT NULL REFERENCES films(id),
    anchor_tier     INTEGER NOT NULL CHECK (anchor_tier BETWEEN 1 AND 5),
    verdict         TEXT    NOT NULL CHECK (verdict IN ('better', 'worse')),
    decided_on      TEXT    NOT NULL
);
CREATE INDEX rank_comparison_film ON rank_comparison(session_id, film_id, id);

CREATE TABLE rank_deferral (
    session_id  INTEGER NOT NULL REFERENCES rank_session(id),
    film_id     INTEGER NOT NULL REFERENCES films(id),
    deferred_on TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id)
);

CREATE TABLE unseen (
    film_id   INTEGER PRIMARY KEY REFERENCES films(id),
    marked_on TEXT NOT NULL,
    note      TEXT
);
INSERT INTO schema_version (version) VALUES (22);
COMMIT;
