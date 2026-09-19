-- Old ratings (spec 2026-09-19-old-ratings §3): the owner's 1–5★ ratings from 2004–08, a watching
-- signal and never a rating — nothing here feeds my_ratings or the ranker. One row per SOURCE LINE
-- (the film_list_entry shape): film_id is a nullable but ENFORCED foreign key, NULL meaning only
-- "the resolver has not placed this row yet" (O3). film_id is deliberately not unique — a source
-- may list one film twice. The `oldratings` verbs are the only writers; merge_film re-points.
BEGIN;
CREATE TABLE old_rating (
    source    TEXT    NOT NULL,
    line      INTEGER NOT NULL,
    title     TEXT    NOT NULL,
    year      INTEGER,
    stars     INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    rented_on TEXT,
    film_id   INTEGER REFERENCES films(id),
    linked_by TEXT CHECK (linked_by IN ('resolver', 'created', 'hand')),
    linked_on TEXT,
    PRIMARY KEY (source, line),
    CHECK ((film_id IS NULL) = (linked_by IS NULL))
);
CREATE INDEX old_rating_film ON old_rating(film_id);
INSERT INTO schema_version (version) VALUES (26);
COMMIT;
