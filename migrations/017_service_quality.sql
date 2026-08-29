-- Best source for a canon film: the two owner-set per-service constants
-- (design docs/superpowers/specs/2026-08-29-canon-best-source-design.md §5, decisions C9 + C10).
-- `quality` is the owner's integer judgement of a service's transfer quality — resolution barely
-- varies across this canon, the restoration does, and no API exposes it. `has_apple_app` is C6's
-- preference as a boolean, ranked BELOW quality so it can only ever break a tie.
-- Both default to their inert value: with every service equal the ordering is the old one plus a
-- tiebreak, and the feature diverges only once the owner sets an opinion (the film_list.trust
-- precedent, migration 016). Only `movie-brain services` writes either column.
BEGIN;
ALTER TABLE movie_service ADD COLUMN quality INTEGER NOT NULL DEFAULT 1;
ALTER TABLE movie_service ADD COLUMN has_apple_app INTEGER NOT NULL DEFAULT 0;
INSERT INTO schema_version (version) VALUES (17);
COMMIT;
