-- The drawer's "▶ Trailer" link (brief docs/superpowers/briefs/2026-09-20-trailer-link/brief.md).
-- One row per film that has been LOOKED UP; `trailers` is a JSON array in play order of
-- {"source": "youtube", "ref": <video key>, "name": …} — the TMDB-typed trailers, at most three —
-- then at most one {"source": "apple", "ref": <preview file URL>, "name": …}. '[]' means "looked up,
-- nothing found", which is what keeps the film off the worklist. `tmdb_id` / `itunes_id` are the ids
-- the lookup was made UNDER: a re-key, or a store id gained later, puts the film back on the
-- worklist by itself. The only writer is `enrich trailers` (write_trailers); merge_film moves it
-- survivor-wins (_ONE_ROW_TABLES). Nothing is fetched when the drawer opens.
BEGIN;
CREATE TABLE film_trailer (
    film_id    INTEGER PRIMARY KEY REFERENCES films(id),
    tmdb_id    INTEGER,
    itunes_id  TEXT,
    trailers   TEXT NOT NULL,
    fetched_on TEXT NOT NULL
);
INSERT INTO schema_version (version) VALUES (28);
COMMIT;
