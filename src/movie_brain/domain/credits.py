"""Credit rows for the drawer (drawer-redesign spec §3, D2/D3).

Pure: takes the `film_credit` rows the repository reads — cast first in billing order, then
crew in TMDB's order — and shapes them into the three rows the drawer prints. Nothing here
is identity: `person` is a join, never a KEY_AUTHORITY.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from movie_brain.domain.models import CastEntry, FilmCredits, WriterEntry

BARE_JOBS = frozenset({"Screenplay", "Writer"})
WRITING_DEPARTMENT = "Writing"
DIRECTOR_JOB = "Director"
UNCREDITED_MARKER = "(uncredited)"  # TMDB's convention, matched case-insensitively; the row stays in film_credit for `actor:` search

CreditRow = tuple[str, str, str, str, str]  # (kind, name, character, job, department)


def writer_label(name: str, jobs: Sequence[str]) -> str:
    """"Leigh Brackett" for a screenwriter, "Raymond Chandler (novel)" for anyone else (D3).

    A person credited with Screenplay or Writer prints bare whatever else they did; other jobs
    are lowercased, deduplicated in first-seen order and joined with "/"."""
    if any(j in BARE_JOBS for j in jobs):
        return name
    tagged = "/".join(dict.fromkeys(j.lower() for j in jobs if j))
    return f"{name} ({tagged})" if tagged else name


def build_credits(rows: Iterable[CreditRow]) -> FilmCredits | None:
    """Shape ordered credit rows into director / cast / writers.

    Cast keeps its billing order; the director is the first `Director` crew row; writers are
    every Writing-department row, ONE entry per person in first-seen order, labelled by
    `writer_label`. None when there are no rows at all — the drawer then falls back to OMDb's
    comma-separated strings.
    """
    cast: list[CastEntry] = []
    director: str | None = None
    writer_jobs: dict[str, list[str]] = {}
    seen = False
    for kind, name, character, job, department in rows:
        seen = True
        if kind == "cast":
            if UNCREDITED_MARKER in character.lower():
                continue  # the owner sees no sense in listing uncredited players, even in the full list
            cast.append(CastEntry(name, character))
        elif job == DIRECTOR_JOB and director is None:
            director = name
        elif department == WRITING_DEPARTMENT:
            writer_jobs.setdefault(name, []).append(job)
    if not seen:
        return None
    writers = tuple(WriterEntry(n, writer_label(n, jobs)) for n, jobs in writer_jobs.items())
    return FilmCredits(director, tuple(cast), writers)
