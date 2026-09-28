-- Backlog 27 (viewing log, brief 2.2). A viewing is a dated EVENT against a film, one per film
-- per day; an artefact is something the owner said or wrote about that viewing — v1 knows one
-- kind, `dictation` (his words, whole). The 0–10 stays in my_ratings; nothing here is a rating.
-- Many rows per film (NOT in _ONE_ROW_TABLES): merge_film re-points viewing.film_id and folds a
-- same-date collision's artefacts onto the survivor's viewing. `service` is a registry slug or
-- NULL (a disc, a cinema). Only `movie-brain viewings add` writes here; sync and every import
-- verb never do.
--
-- Edited 2026-09-27 BEFORE any real database applied it (unmerged branch, never pushed), which
-- is the only reason editing an applied-looking migration is legitimate here (point-C gap check
-- finding 1): both PKs gained AUTOINCREMENT so a removed viewing's or artefact's number is never
-- handed to the next one created — a second `viewings remove N` (a retried or re-run command)
-- must refuse rather than silently delete whatever now sits at N.
BEGIN;
CREATE TABLE viewing (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    film_id    INTEGER NOT NULL REFERENCES films(id),
    watched_on TEXT    NOT NULL,
    service    TEXT    REFERENCES movie_service(slug),
    logged_on  TEXT    NOT NULL,
    UNIQUE (film_id, watched_on)
);
CREATE TABLE artefact (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    viewing_id INTEGER NOT NULL REFERENCES viewing(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL CHECK (kind IN ('dictation')),
    text       TEXT    NOT NULL CHECK (length(trim(text)) > 0),
    added_on   TEXT    NOT NULL
);
CREATE INDEX artefact_viewing ON artefact(viewing_id);
INSERT INTO schema_version (version) VALUES (31);
COMMIT;
