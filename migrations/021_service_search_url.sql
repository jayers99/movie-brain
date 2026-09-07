-- The drawer's one watch link (drawer-redesign spec D6/D7): "Watch on HBO Max ↗" must land on
-- HBO Max, and a TMDB-fed listing only ever holds themoviedb.org's watch page for the film, never
-- a service URL. `search_url` is the service's own title-search template with a `{title}`
-- placeholder — an owner-set registry fact like `quality` and `has_apple_app` (migration 017),
-- written by `movie-brain services url` and by nothing else. NULL default so the feature ships
-- inert: with no template the link falls back to the listing's stored URL.
BEGIN;
ALTER TABLE movie_service ADD COLUMN search_url TEXT;
INSERT INTO schema_version (version) VALUES (21);
COMMIT;
