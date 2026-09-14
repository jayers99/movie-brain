-- Move a film to another tier (spec 2026-09-14-move-tier-design.md M1/M9): a hand-set tier is
-- recorded as `how = 'moved'` so the audit can tell it from a search result. SQLite cannot
-- ALTER a CHECK, so this is a table rebuild inside one transaction (012's precedent). The
-- composite PK (place_film's INSERT OR REPLACE and merge_film's twin checks rely on it) and
-- both FKs are preserved; nothing references or indexes rank_placement.
BEGIN;
CREATE TABLE rank_placement_new (
    session_id INTEGER NOT NULL REFERENCES rank_session(id),
    film_id    INTEGER NOT NULL REFERENCES films(id),
    tier       INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    how        TEXT    NOT NULL CHECK (how IN ('seed', 'compared', 'anchor', 'moved')),
    placed_on  TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id)
);
INSERT INTO rank_placement_new (session_id, film_id, tier, how, placed_on)
    SELECT session_id, film_id, tier, how, placed_on FROM rank_placement;
DROP TABLE rank_placement;
ALTER TABLE rank_placement_new RENAME TO rank_placement;
INSERT INTO schema_version (version) VALUES (25);
COMMIT;
