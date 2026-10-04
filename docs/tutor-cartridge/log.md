# tutor-cartridge — log

Append-only. Entry format: `## [YYYY-MM-DD] <ingest|query|lint|build> | <title>`.

## [2026-09-13] ingest | Bundle 2026-09-13-movie-brain-cartridge received

Copied `raw/` (6 files) and `wiki/` (9 files) from the private coach vault's `handoff/movie-brain-cartridge/` bundle, byte-identical to it. First cut was built from vault commit `86fbaf6`; raw/149 was re-scrubbed and re-copied from vault commit `70e2ebd`, which is the bundle commit this receipt stands on. The vault's scrub checker reported ok on all 15 derivative files, 0 FAIL, 74 WARN (the accepted residue: NotebookLM citations, `.nlm.` in PubMed URLs, "150-film", spirits judging as a trade, pronouns for named philosophers). The first cut's raw/149 gendered the learner at lines 302 and 341 and credited the learner with a spirits-judging background; the 70e2ebd re-scrub removed all of it (verified by grep). `index.md` and `log.md` are not derivatives and the checker reports them FAIL for lacking provenance frontmatter and for wikilinks it resolves only within one directory — structural, not a leak; every deny hit on them was removed. `raw/` is immutable from this entry on. Reconciliation with `docs/criticism-syllabus.md` deliberately not started.

## [2026-10-04] lint | The "MovieWise rubric" was NotebookLM's; weighted rubrics ruled out for good

A check of all 128 raw transcripts of the Moviewise notebook found none of these: the 30/30/15/10/10/5 weights, the 92/100 canon threshold, or the eight-dimension 1–5 rubric in `docs/criticism-syllabus.md`. NotebookLM synthesized all three in chat, and the notebook confirms it. Owner ruling the same day: no weighted or summed rubric will ever be used. `index.md` gains a Settled section (the rubric item closed, raw/137's premise flagged, teleological grounding replaced by *imagine the alternative* and *name the film that did it right*, a provenance rule for NotebookLM output). raw/ and the wiki derivatives are untouched and stay byte-identical to the bundle. The origin pages upstream (the epistemology summary and the canon-admission criterion) still need the same correction in the source vault.
