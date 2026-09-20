-- "Wishlist it" (brief 2026-09-19-price-watch): which films are on the owner's CheapCharts
-- wishlist. The wishlist itself lives on CheapCharts; this is the local mirror that draws the
-- heart. Watchlist pattern: one row per film, exactly two writers — the drawer button
-- (mark_wishlisted) and the wholesale wishlist read (replace_wishlist). No price is stored.
-- merge_film moves it survivor-wins (_ONE_ROW_TABLES).
BEGIN;
CREATE TABLE cheapcharts_wishlist (
    film_id  INTEGER PRIMARY KEY REFERENCES films(id),
    added_on TEXT NOT NULL
);
INSERT INTO schema_version (version) VALUES (27);
COMMIT;
