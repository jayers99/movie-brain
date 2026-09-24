-- Backlog 41 (search-recall spec D1–D2). The keyword stage gets an English stemmer.
--
-- Edited 2026-09-23 BEFORE any real database applied it (unmerged branch, never pushed), which
-- is the only reason editing an applied-looking migration is legitimate here.
--
-- What stays: film_keyword_fts, a STANDALONE FTS5 table (film_id unindexed + the keyword) with
-- tokenize='porter unicode61', not an external-content index, because film_keyword has a
-- composite PRIMARY KEY and no INTEGER PRIMARY KEY, so its rowids are not stable across VACUUM.
-- 43k short strings cost nothing to duplicate. Two triggers keep it in step: film_keyword is
-- only ever inserted into or deleted from (write_credits, merge_film), never updated in place.
-- An INSERT OR IGNORE that is ignored fires no trigger, which is exactly right.
--
-- What was measured and removed: the first cut also dropped and recreated film_text_fts (the
-- prose index) with Porter. On a migrated copy with the prose index reverted, verbatim
-- recall@10 was 0.686 (0.627 with prose Porter, baseline 0.705) and plural 0.855 (0.676), and
-- `time loops` and `dystopian` still hit through the keyword index and ladder. Prose Porter
-- widened prose hits (`hypnotism` -> `hypnot` -> "hypnotic") and raw -bm25 prose scores (7–12)
-- outrank W_TAG 3. Owner decision 2026-09-23: film_text_fts keeps 018's unicode61.
--
-- Porter measured 2026-09-23 on SQLite 3.54: loops/loop, vampires/vampire, robots/robot,
-- haunting/haunted unify; dystopian/dystopia do NOT (no -ian rule) — that case is the
-- freeform keyword ladder's job (application code), not this migration's.
BEGIN;
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
