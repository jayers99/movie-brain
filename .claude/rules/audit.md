---
paths:
  - src/movie_brain/domain/audit.py
  - src/movie_brain/application/audit.py
---

# Data audit contract (moved from CLAUDE.md)

- Data audit (`docs/superpowers/specs/2026-08-24-data-audit-design.md`): `audit_flags` is a derived
  report replaced by every `audit run`; `tmdb_facts` is a one-call-per-film cache refetched only when
  the film's `tmdb` link changes; `audit_verdict` is append-only user-response data — the drawer's
  verdict endpoint is its ONLY writer, sync/repair/review never touch it, and a `fine` verdict
  suppresses the Suspect chip only while the film's reason set is unchanged. Checks live in
  `domain/audit.py` (weights are named constants); the verb never fixes anything. The first
  `audit run` fetches one TMDB call per linked film (~4.3k films ≈ 18 min at the polite delay),
  logs progress every 100 films, and is resumable — each film's facts commit as fetched, so
  Ctrl-C keeps progress and a re-run continues.
