-- Order inside a tier (spec docs/superpowers/specs/2026-09-13-order-top-tier-design.md §3).
-- Three tables beside 022's six: the order itself (dense positions per session+tier), the
-- insertion search's append-only log (its ONLY state — bounds are derived from it on every
-- read), and the order-mode Pass. All film-scoped; merge_film moves them survivor-wins.
BEGIN;
CREATE TABLE rank_order (
    session_id INTEGER NOT NULL REFERENCES rank_session(id),
    tier       INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    film_id    INTEGER NOT NULL REFERENCES films(id),
    position   INTEGER NOT NULL CHECK (position >= 1),
    ordered_on TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id),
    UNIQUE (session_id, tier, position)
);
CREATE TABLE rank_order_comparison (
    id            INTEGER PRIMARY KEY,
    session_id    INTEGER NOT NULL REFERENCES rank_session(id),
    tier          INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    film_id       INTEGER NOT NULL REFERENCES films(id),
    other_film_id INTEGER NOT NULL REFERENCES films(id),
    verdict       TEXT    NOT NULL CHECK (verdict IN ('better', 'worse')),
    decided_on    TEXT    NOT NULL
);
CREATE INDEX rank_order_comparison_film ON rank_order_comparison(session_id, film_id, id);
CREATE INDEX rank_order_comparison_other ON rank_order_comparison(other_film_id);
CREATE TABLE rank_order_deferral (
    session_id  INTEGER NOT NULL REFERENCES rank_session(id),
    film_id     INTEGER NOT NULL REFERENCES films(id),
    deferred_on TEXT    NOT NULL,
    PRIMARY KEY (session_id, film_id)
);
INSERT INTO schema_version (version) VALUES (23);
COMMIT;
