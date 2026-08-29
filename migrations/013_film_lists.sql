-- Backlog item: curated top-N lists (seed docs/superpowers/specs/2026-08-28-curated-lists-seed.md,
-- design docs/superpowers/specs/2026-08-28-curated-lists-design.md §3). Registers imported
-- curated lists (e.g. the Cahiers 100) and their ranked entries; entries link to films lazily.
BEGIN;
CREATE TABLE film_list (
    slug           TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    curator        TEXT,
    published_year INTEGER,
    source_url     TEXT,
    ordered        INTEGER NOT NULL DEFAULT 1,
    imported_at    TEXT NOT NULL
);
CREATE TABLE film_list_entry (
    list_slug       TEXT NOT NULL REFERENCES film_list(slug),
    rank            INTEGER NOT NULL,
    film_id         INTEGER REFERENCES films(id),
    title_listed    TEXT NOT NULL,
    director_listed TEXT,
    PRIMARY KEY (list_slug, rank)
);
CREATE INDEX film_list_entry_film ON film_list_entry(film_id);
INSERT INTO schema_version (version) VALUES (13);
COMMIT;
