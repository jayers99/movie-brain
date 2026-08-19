CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE films (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    year INTEGER,
    director TEXT,
    key TEXT NOT NULL UNIQUE
);
CREATE TABLE listings (
    film_id INTEGER NOT NULL REFERENCES films(id),
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    leaving_date TEXT,
    PRIMARY KEY (film_id, source)
);
CREATE INDEX listings_source_last_seen ON listings(source, last_seen);
CREATE TABLE omdb (
    film_id INTEGER PRIMARY KEY REFERENCES films(id),
    found INTEGER NOT NULL,
    imdb REAL,
    rt INTEGER,
    language TEXT,
    looked_up TEXT NOT NULL,
    year_fallback INTEGER NOT NULL DEFAULT 1,
    needs_refresh INTEGER NOT NULL DEFAULT 0,
    payload TEXT
);
CREATE TABLE my_ratings (
    film_id INTEGER PRIMARY KEY REFERENCES films(id),
    score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 10),
    rated_at TEXT NOT NULL
);
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT INTO schema_version (version) VALUES (1);
