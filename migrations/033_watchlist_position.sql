-- Backlog 46 (brief docs/superpowers/briefs/2026-10-02-watchlist-order/brief.md, amendment 1.1).
-- The watchlist gains the owner's hand order: a dense 1…n `position`, written only by the
-- repository (a fresh star at 1, a put-back above its remembered neighbour, an un-star closing the
-- gap, a move past one visible neighbour, a merge never leaving a hole). Seeded in the dashboard's
-- default order at the time of the migration — Metacritic (scraped over OMDb), then RT, then IMDb,
-- each descending with missing last, then title, then id — so nothing on screen moves on day one.
BEGIN;
ALTER TABLE watchlist ADD COLUMN position INTEGER;
CREATE TEMP TABLE _wl_seed AS
SELECT w.film_id,
       ROW_NUMBER() OVER (ORDER BY
           (COALESCE(mc.score, o.metacritic) IS NULL), COALESCE(mc.score, o.metacritic) DESC,
           (o.rt IS NULL), o.rt DESC,
           (o.imdb IS NULL), o.imdb DESC,
           f.title COLLATE NOCASE, f.id) AS rn
FROM watchlist w
JOIN films f ON f.id = w.film_id
LEFT JOIN omdb o ON o.film_id = f.id
LEFT JOIN (SELECT e.film_id, e.value FROM external_ids e WHERE e.authority = 'metacritic'
           AND NOT EXISTS (SELECT 1 FROM external_ids e2 WHERE e2.film_id = e.film_id AND e2.authority = 'metacritic'
             AND (e2.first_seen < e.first_seen OR (e2.first_seen = e.first_seen AND e2.value < e.value)))) x
       ON x.film_id = f.id
LEFT JOIN metacritic mc ON mc.slug = x.value;
UPDATE watchlist SET position = (SELECT rn FROM _wl_seed s WHERE s.film_id = watchlist.film_id);
DROP TABLE _wl_seed;
INSERT INTO schema_version (version) VALUES (33);
COMMIT;
