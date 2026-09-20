-- Remember a store-id miss (backlog 22; owner ruling 2026-09-20: every new film gets its full
-- enrichment when it is added, so the database is never scoured again for the same missing data).
-- `cheapcharts resolve` used to re-ask CheapCharts about EVERY film holding no `itunes` id on every
-- run — 2,262 films on 2026-09-20, one paced search each, about an hour — which is what kept it out
-- of sync. One row per film CheapCharts was asked about and had no confirmed product for; the
-- worklist skips it unless `--retry-misses` is given. A film that later gains a store id simply
-- stops being on the worklist; its row is harmless. merge_film moves it survivor-wins
-- (_ONE_ROW_TABLES).
--
-- Seeded for the films the September full passes already covered (the backfill of 2026-09-05 and
-- the recheck of 2026-09-07 asked about every film then holding an IMDb id): a film whose `imdb`
-- external id dates from on or before 2026-09-07 and that still holds no store id WAS asked and had
-- nothing. Films keyed since then (74 when written) are left unseeded, so the next run asks them.
BEGIN;
CREATE TABLE store_lookup (
    film_id  INTEGER PRIMARY KEY REFERENCES films(id),
    asked_on TEXT NOT NULL
);
INSERT INTO store_lookup (film_id, asked_on)
SELECT x.film_id, '2026-09-07' FROM external_ids x
WHERE x.authority = 'imdb' AND x.first_seen <= '2026-09-07'
  AND NOT EXISTS (SELECT 1 FROM external_ids i WHERE i.film_id = x.film_id AND i.authority = 'itunes')
GROUP BY x.film_id;
INSERT INTO schema_version (version) VALUES (29);
COMMIT;
