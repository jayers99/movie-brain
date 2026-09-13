-- "Rank this" (spec 2026-09-13-ranking-pool §3, P2): the ranker pool's entry ticket for a film the
-- owner does not own. Watchlist pattern: one row per film, the drawer toggle and set_rank_mark
-- the only writers, never touched by sync. merge_film moves it survivor-wins (_ONE_ROW_TABLES).
BEGIN;
CREATE TABLE rank_mark (
    film_id   INTEGER PRIMARY KEY REFERENCES films(id),
    marked_on TEXT NOT NULL
);
INSERT INTO schema_version (version) VALUES (24);
COMMIT;
