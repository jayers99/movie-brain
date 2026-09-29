"""The viewing log's use cases (brief docs/superpowers/briefs/2026-09-21-viewing-log/brief-2.md).

One dictation → one deterministic write. The title ladder is HERE, not in the agent's prompt:
rung 1 the film the dashboard has open (a fresh drawer report) when its normalised title equals
the dictated one; rung 2 exactly one canonical film with that normalised title; rung 3 stop —
AMBIGUOUS with the same-title films, or NO-FILM with the nearest titles — and write nothing.
One normaliser on both sides at query time (domain/thumbprint.py::title_norm); the films.title_norm
column is never read. No SQL, no HTTP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

from movie_brain.domain.thumbprint import parse_title, title_norm
from movie_brain.infrastructure.database import Repository

STOP_WORDS = frozenset({"the", "a", "an", "of", "and", "vs", "versus"})
NEAREST = 5
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Candidate:
    film_id: int
    title: str
    year: int | None
    director: str | None
    best_source: str | None

    def line(self) -> str:
        parts = [f"#{self.film_id}", f"{self.title} ({self.year or '-'})", self.director or "—"]
        if self.best_source:
            parts.append(self.best_source)
        return "  " + "  ".join(parts)


@dataclass(frozen=True)
class Resolution:
    film_id: int | None
    how: str
    candidates: tuple[Candidate, ...] = ()


@dataclass(frozen=True)
class Outcome:
    kind: str
    line: str
    exit_code: int
    film_id: int | None = None
    viewing_id: int | None = None


def _words(title: str) -> list[str]:
    return [w for w in _WORD.findall(title_norm_words(title)) if w not in STOP_WORDS]


def title_norm_words(title: str) -> str:
    """Lower-cased, accent-folded, apostrophes dropped, but WORDS KEPT APART (title_norm joins them)."""
    import unicodedata

    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    return t.replace("'", "").replace("’", "")


def _candidate(
    repo: Repository, film_id: int, title: str, year: int | None, director: str | None, today: date
) -> Candidate:
    if director is None:
        # films.director is NULL for 1,857 of 5,274 canonical films (finding 10) — the same
        # credits fallback the drawer uses, so an AMBIGUOUS line does not show a dash where the
        # question needs a name.
        credits = repo.film_credits(film_id)
        if credits is not None:
            director = credits.director
    view = repo.get_view(film_id, today)
    best = cast("str | None", view.best_source["name"]) if view is not None and view.best_source else None
    return Candidate(film_id, title, year, director, best)


def resolve_title(
    repo: Repository, title: str, *, year: int | None, now: datetime, today: date | None = None
) -> Resolution:
    today = today or now.date()
    if year is None:
        # A year said INSIDE the title ("Solaris (1972)") is as good as `--year`: title_norm
        # strips it before matching, so without this the command would call it AMBIGUOUS
        # although the owner already named the year.
        year = parse_title(title).embedded_year
    wanted = title_norm(title)
    rows = repo.canonical_titles()
    by_id = {r[0]: r for r in rows}
    open_id = repo.drawer_film(now)
    if open_id in by_id and wanted:
        _, t, y, _d = by_id[open_id]
        if title_norm(t) == wanted and (year is None or y == year):
            return Resolution(open_id, "matched the open film")
    hits = [r for r in rows if wanted and title_norm(r[1]) == wanted and (year is None or r[2] == year)]
    if len(hits) == 1:
        return Resolution(hits[0][0], "the one film with that title")
    if len(hits) > 1:
        return Resolution(None, "ambiguous", tuple(_candidate(repo, *r, today) for r in hits))
    near: list[tuple[int, str, int | None, str | None]] = []
    words = _words(title)
    # Gated on `words` (post-stop-word filtering), not `wanted`: a title of only stop words
    # ("The") must yield NO nearest list at all, and a bare `wanted` guard would let its
    # normalised form ("the") match as a substring of "theblueangel" etc. — spurious near hits.
    if words:
        ids = repo.title_hits(" ".join(words))
        near = [r for r in rows if r[0] in ids and (year is None or r[2] == year)]
        if not near:
            # title_hits' film_text_fts stage is empty pre-enrichment and its LIKE fallback is a
            # plain substring test, so a dictated "versus" never finds a stored "vs." title (the
            # words are out of order with a token dropped in between); comparing word SETS (after
            # the same stop-word filter on both sides) recovers it without ever calling title_hits("").
            near = [r for r in rows if all(w in _words(r[1]) for w in words) and (year is None or r[2] == year)]
        if not near and wanted:
            # Films whose normalised title CONTAINS the normalised dictation — one direction only
            # (spec: "films whose normalised title contains the normalised dictation"). The reverse
            # test floods the list with one-letter titles ("M" contains nothing, but "M" IS contained
            # in almost anything) whenever the dictated title is longer than a stored one.
            near = [r for r in rows if title_norm(r[1]) and wanted in title_norm(r[1])]
    near = sorted(near, key=lambda r: (r[2] or 0, r[0]))[:NEAREST]
    return Resolution(None, "no-film", tuple(_candidate(repo, *r, today) for r in near))


def _refused(reason: str) -> Outcome:
    return Outcome("refused", f"REFUSED   {reason} — nothing written", 2)


def log_viewing(
    repo: Repository,
    *,
    title: str | None,
    film_id: int | None,
    year: int | None,
    on: date | None,
    service: str | None,
    rate: int | None,
    text: str | None,
    today: date,
    now: datetime,
    study: bool = False,
) -> Outcome:
    # text None = "just mark the date" (--no-note): a viewing with no artefact. A dictation that
    # was GIVEN but is blank is still a refusal. `study` (backlog 48) marks the line the add
    # writes — created or found — and is never cleared here.
    if text is not None and not text.strip():
        return _refused("the dictation is empty")
    on = on or today
    if on > today:
        return _refused(f"{on.isoformat()} is in the future")
    if rate is not None and (isinstance(rate, bool) or not isinstance(rate, int) or not 0 <= rate <= 10):
        return _refused("a rating is a whole number 0–10")
    service_name = None
    if service is not None:
        service_name = repo.service_name(service)
        if service_name is None:
            return _refused(f"no service '{service}' in the registry (movie-brain services list)")
    canonical = {r[0]: r for r in repo.canonical_titles()}
    if film_id is not None:
        if film_id not in canonical:
            return _refused(f"no film #{film_id} (merged away, tombstoned or unknown)")
        if title and title.strip():
            # `--title` and `--film` must agree (finding 7): a mistyped id in a rerun must not
            # silently log some OTHER film under the words meant for this one.
            _, cftitle, cfyear, _cd = canonical[film_id]
            wanted, stored = title_norm(title), title_norm(cftitle)
            if wanted and stored and wanted not in stored and stored not in wanted:
                return _refused(f"--film {film_id} is '{cftitle}' ({cfyear or '-'}), not '{title}'")
        res = Resolution(film_id, "by id")
    else:
        if not title or not title.strip():
            return _refused("say a title or a film id")
        res = resolve_title(repo, title, year=year, now=now, today=today)
    if res.film_id is None:
        if res.how == "ambiguous":
            body = "\n".join(c.line() for c in res.candidates)
            line = (
                f"AMBIGUOUS {len(res.candidates)} films titled '{title}' — nothing written\n{body}\n"
                "  say which: --film ID or --year YYYY"
            )
            return Outcome("ambiguous", line, 3)
        if res.candidates:
            body = " · ".join(f"#{c.film_id} {c.title} ({c.year or '-'})" for c in res.candidates)
            line = (
                f"NO-FILM   no film titled '{title}' — nothing written\n  nearest: {body}\n"
                "  say --film ID if one of these is it; otherwise films add ttNNN mints a new film"
            )
            return Outcome("no-film", line, 3)
        line = (
            f"NO-FILM   no film titled '{title}' — nothing written\n"
            "  nothing close by title either; films add ttNNN mints a new film"
        )
        return Outcome("no-film", line, 3)
    fid, (_, ftitle, fyear, _d) = res.film_id, canonical[res.film_id]
    w = repo.add_viewing(fid, on, service, text.strip() if text is not None else None, rate, today, study=study)
    rated = (f" · rated {rate}" if rate is not None else "") + (" · study" if study else "")
    if w.created:
        svc = f" · {service}" if service else ""
        line = (
            f"LOGGED    #{fid} '{ftitle}' ({fyear or '-'}) · {on.isoformat()}{svc} · "
            f"viewing #{w.viewing_id} · {res.how}{rated}"
        )
        return Outcome("logged", line, 0, fid, w.viewing_id)
    dropped = f" · service kept: {w.service} ({service} noted)" if service and w.service != service else ""
    line = (
        f"ADDED-TO  viewing #{w.viewing_id} (#{fid} '{ftitle}', {on.isoformat()}) · "
        f"{f'note {w.note_count}' if text is not None else f'no new note ({w.note_count} kept)'}{dropped}{rated}"
    )
    return Outcome("added-to", line, 0, fid, w.viewing_id)


def study(repo: Repository, viewing_id: int, *, off: bool) -> Outcome:
    """Mark one line for study, or clear it (backlog 48). Idempotent: a repeated mark or clear
    answers `already marked` / `already clear` and writes nothing; an unknown number refuses."""
    got = repo.set_study(viewing_id, not off)
    if got is None:
        return _refused(f"no viewing #{viewing_id}")
    if off:
        tail = "mark cleared" if got["changed"] else "already clear"
    else:
        tail = "marked for study" if got["changed"] else "already marked"
    line = f"STUDY     viewing #{viewing_id} (#{got['film_id']} '{got['title']}', {got['watched_on']}) · {tail}"
    return Outcome("study", line, 0, cast(int, got["film_id"]), viewing_id)


def remove(repo: Repository, viewing_id: int, note: int | None) -> Outcome:
    if note is None:
        gone = repo.remove_viewing(viewing_id)
        if gone is None:
            return _refused(f"no viewing #{viewing_id}")
        n = cast(int, gone["notes"])
        line = (
            f"REMOVED   viewing #{viewing_id} (#{gone['film_id']} '{gone['title']}', {gone['watched_on']}) and its "
            f"{n} note{'' if n == 1 else 's'} · rating and Unseen untouched"
        )
        return Outcome("removed", line, 0, cast(int, gone["film_id"]), viewing_id)
    gone = repo.remove_artefact(viewing_id, note)
    if gone is None:
        n_have = repo.note_count(viewing_id)
        if n_have is None:
            return _refused(f"no viewing #{viewing_id}")
        return _refused(f"viewing #{viewing_id} has {n_have} note{'' if n_have == 1 else 's'}, no note {note}")
    left = cast(int, gone["notes_left"])
    line = (
        f"REMOVED   note {note} of viewing #{viewing_id} "
        f"(#{gone['film_id']} '{gone['title']}', {gone['watched_on']}) · "
        f"{left} note{'' if left == 1 else 's'} left · the viewing, the rating and Unseen untouched"
    )
    return Outcome("removed", line, 0, cast(int, gone["film_id"]), viewing_id)


def listing(repo: Repository, since: date | None, film_id: int | None, study_only: bool = False) -> str:
    rows = repo.list_viewings(since=since, film_id=film_id, study_only=study_only)
    if not rows:
        if study_only:
            return "no viewing marked for study"
        return f"no viewing{' since ' + since.isoformat() if since else ''}"
    # Only with --film (finding 3): the note numbers "scratch that remark" and `remove --note N`
    # need, since nothing else ever prints them. One extra read, keyed by viewing id.
    artefacts_by_viewing: dict[int, list[dict[str, object]]] = {}
    if film_id is not None:
        artefacts_by_viewing = {cast(int, v["id"]): cast(list, v["artefacts"]) for v in repo.viewings_for(film_id)}
    out = []
    for r in rows:
        n = cast(int, r["notes"])
        svc = (f"  {r['service']}" if r["service"] else "") + ("  study" if r["study"] else "")
        rated = f"  rated {r['my_rating']}" if r["my_rating"] is not None else ""
        out.append(
            f"{r['watched_on']}  #{str(r['film_id']).ljust(5)} {r['title']} ({r['year'] or '-'}){svc}  "
            f"{n} note{'' if n == 1 else 's'}{rated}"
        )
        for i, a in enumerate(artefacts_by_viewing.get(cast(int, r["id"]), []), start=1):
            text = cast(str, a["text"])
            first60 = text[:60] + ("…" if len(text) > 60 else "")
            out.append(f"    note {i}  {first60}")
    return "\n".join(out)


def open_line(repo: Repository, now: datetime) -> str:
    fid = repo.drawer_film(now)
    if fid is None:
        return "OPEN      nothing — no drawer has reported in for two minutes (closed, or the dashboard is not running)"
    view = repo.get_view(fid, now.date())
    if view is None:
        return "OPEN      nothing — the reported film is not a film the dashboard can show"
    return f"OPEN      #{fid} '{view.title}' ({view.year or '-'})"
