---
paths:
  - src/movie_brain/application/viewings.py
  - migrations/031_viewing.sql
  - .claude/skills/log-viewing/SKILL.md
---
# Viewing log contract (brief `docs/superpowers/briefs/2026-09-21-viewing-log/brief-2.md` v2.2, migration 031, built 2026-09-27)

- A viewing is a dated EVENT against a film (`viewing`: film, `watched_on`, optional registry `service`, `logged_on`; `UNIQUE(film_id, watched_on)`); an `artefact` is what he said about it (kind `dictation` only in v1; the CHECK widens by a later migration). The 0–10 stays in `my_ratings`, written through `Repository._write_rating` (the same one-liner `set_rating`'s upsert uses) inside `add_viewing`'s one transaction; nothing on the viewing is a rating.
- `movie-brain viewings add` is the ONLY writer; sync, `enrich` and every import verb never touch these tables; the dashboard reads them (detail-only `viewings`, `old_ratings`; `last_watched` + `viewing_count` on the list payload) and never writes them. The drawer's log has no buttons.
- The title ladder lives in `application/viewings.py::resolve_title`, never in a prompt: rung 1 the film the dashboard reports open (`meta.drawer_film`, a 30 s heartbeat trusted 120 s — `Repository.drawer_film`) when its normalised title equals the dictated one; rung 2 exactly one canonical film (no `film_disposition` row) with that normalised title; rung 3 stop (AMBIGUOUS lists the films, NO-FILM lists the nearest titles via `title_hits` over the words minus articles and vs/versus, then a normalised substring) and write nothing, exit 3. One normaliser, both sides, at query time: `domain/thumbprint.py::title_norm`; the `films.title_norm` column is NEVER read (empty for every film created since the backfill).
- One viewing per film per day; a second add appends an artefact (`ADDED-TO`), moves the rating if given, sets the service only if the line had none — never overwrites one. Refusals (`REFUSED`, exit 2: future date, blank text, unknown slug, rating outside 0–10, unknown viewing/note, non-canonical `--film`) happen before the one transaction and write nothing. Logging clears `unseen` with a bare `DELETE FROM unseen` inside the same transaction — the one-liner `set_unseen(False)` also performs, not a call through it — so nothing else moves; removing restores nothing.
- `merge_film` re-points `viewing.film_id`; a same-date collision moves the loser's artefacts onto the survivor's viewing. A viewed film is always visible in `list_views` (current-or-rated-or-viewed).
- The agent's side is `.claude/skills/log-viewing/SKILL.md`: extraction rules (one film per command; date never invented; service mapped through the film; a rating only when ONE whole number is offered as a rating), and what to do on each exit code. `films add --apply` always waits for the owner's yes.
