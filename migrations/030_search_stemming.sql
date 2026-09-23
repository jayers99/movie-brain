-- Backlog 41 (search-recall spec D1–D2). Two word stages get an English stemmer.
--
-- 1. film_text_fts: an FTS5 tokenizer cannot be changed in place, so the virtual table is
--    dropped and recreated with Porter, then rebuilt from film_text — the base table is the
--    truth (018's own rule). The three triggers on film_text reference the index by name and
--    survive the drop untouched. `time loops` now reaches "finds himself in a time loop".
-- 2. film_keyword_fts: a STANDALONE FTS5 table (film_id unindexed + the keyword), not an
--    external-content index, because film_keyword has a composite PRIMARY KEY and no INTEGER
--    PRIMARY KEY, so its rowids are not stable across VACUUM. 43k short strings cost nothing
--    to duplicate. Two triggers keep it in step: film_keyword is only ever inserted into or
--    deleted from (write_credits, merge_film), never updated in place. An INSERT OR IGNORE
--    that is ignored fires no trigger, which is exactly right.
-- Porter measured 2026-09-23 on SQLite 3.54: loops/loop, vampires/vampire, robots/robot,
-- haunting/haunted unify; dystopian/dystopia do NOT (no -ian rule) — that case is the
-- freeform keyword ladder's job (application code), not this migration's.
BEGIN;
DROP TABLE film_text_fts;
CREATE VIRTUAL TABLE film_text_fts USING fts5(title, overview, plot, content='film_text', content_rowid='film_id', tokenize='porter unicode61');
INSERT INTO film_text_fts(film_text_fts) VALUES ('rebuild');

CREATE VIRTUAL TABLE film_keyword_fts USING fts5(film_id UNINDEXED, keyword, tokenize='porter unicode61');
INSERT INTO film_keyword_fts (film_id, keyword) SELECT film_id, keyword FROM film_keyword;
CREATE TRIGGER film_keyword_ai AFTER INSERT ON film_keyword BEGIN
    INSERT INTO film_keyword_fts (film_id, keyword) VALUES (new.film_id, new.keyword);
END;
CREATE TRIGGER film_keyword_ad AFTER DELETE ON film_keyword BEGIN
    DELETE FROM film_keyword_fts WHERE film_id = old.film_id AND keyword = old.keyword;
END;
INSERT INTO schema_version (version) VALUES (30);
COMMIT;
