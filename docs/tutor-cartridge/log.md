# tutor-cartridge — log

Append-only. Entry format: `## [YYYY-MM-DD] <ingest|query|lint|build> | <title>`.

## [2026-09-13] ingest | Bundle 2026-09-13-movie-brain-cartridge received

Copied `raw/` (6 files) and `wiki/` (9 files) from the private coach vault's `handoff/movie-brain-cartridge/` bundle, byte-identical to it. First cut was built from vault commit `86fbaf6`; raw/149 was re-scrubbed and re-copied from vault commit `70e2ebd`, which is the bundle commit this receipt stands on. The vault's scrub checker reported ok on all 15 derivative files, 0 FAIL, 74 WARN (the accepted residue: NotebookLM citations, `.nlm.` in PubMed URLs, "150-film", spirits judging as a trade, pronouns for named philosophers). The first cut's raw/149 gendered the learner at lines 302 and 341 and credited the learner with a spirits-judging background; the 70e2ebd re-scrub removed all of it (verified by grep). `index.md` and `log.md` are not derivatives and the checker reports them FAIL for lacking provenance frontmatter and for wikilinks it resolves only within one directory — structural, not a leak; every deny hit on them was removed. `raw/` is immutable from this entry on. Reconciliation with `docs/criticism-syllabus.md` deliberately not started.
