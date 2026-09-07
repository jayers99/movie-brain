-- Power search, Plan C (design docs/superpowers/specs/2026-09-06-power-search-c-semantic-design.md §3, D14).
-- One vector per film over its PROSE (overview + plot + tagline, never the title), stored as a
-- plain BLOB of `dim` little-endian float32 values, L2-normalised so cosine is a dot product.
-- No sqlite-vec: brute-force cosine over the whole catalogue measured 0.08 ms per query with
-- numpy, so a virtual table that must be loaded on every connection buys nothing.
-- `model` is a column, not part of the key: a model change is a full re-embed and two models
-- never coexist. Byte layout is yt-brain's `_to_blob` (struct '384f'), so vectors read across.
-- Nothing here is identity — `film_embedding` is search data, moved by merge_film survivor-wins.
BEGIN;
CREATE TABLE film_embedding (
    film_id     INTEGER PRIMARY KEY REFERENCES films(id),
    model       TEXT    NOT NULL,
    dim         INTEGER NOT NULL,
    vector      BLOB    NOT NULL,
    embedded_on TEXT    NOT NULL
);
INSERT INTO schema_version (version) VALUES (19);
COMMIT;
