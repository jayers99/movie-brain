"""Curated top-N lists: the resolution helpers the import and create verbs share.

A list entry is a curator's title plus, usually, a director — no year, no id, no url. Turning
that into a film id is the accuracy test of the T1-T5 identity stack, and **duplicate films
are the failure it must not produce**: under-creating costs one review row, over-creating
costs a merge. So the four helpers here are deliberately timid.

- `entry_forms` — every title string one entry could be known by, primary first.
- `resolve_entry` — the fallback-only form ladder over those forms (design §1 A2).
- `find_holder` — gates 1 / 2 / 2b: does a film in the catalog already hold this work's ids?
- `corpus_veto` — gate 3: does the catalog hold anything *resembling* any of these titles?

`find_holder` is the third sibling of the resolve-first block in `owned.py::import_owned` and
`metacritic.py::promote_top_n`, with one addition — gate 2b (design §1 A4): a resolver winner
that exists only in OMDb carries no TMDB id, so the plain gate 2 asks nothing at all. Asking
TMDB for the mapping — the same `find_by_imdb` call `key_film` already trusts on every keying
path — can only find *more* holders, so it strictly reduces creations.

The verbs that use these (`lists import`, `lists create`) live in later tasks. Nothing here
writes anything.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import requests

from movie_brain.domain.matching import Candidate, CandidateIndex
from movie_brain.domain.models import ListEntry
from movie_brain.domain.thumbprint import Verdict, make_query, parse_title, resolve
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.omdb import QuotaExceeded
from movie_brain.infrastructure.thumbprint_fetch import CacheMiss, CandidateFetcher
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

AUTHORITY = "list"


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def entry_forms(title_listed: str) -> list[str]:
    """Every title string this entry could be known by, primary form first.

    One shared definition for the ladder and for gate 3's veto — the two must never disagree
    about what counts as "this entry's title". `ParsedTitle.forms()` already returns
    `(title, base, *alt_titles)` de-duplicated; a plain title therefore yields one form.
    """
    return list(parse_title(title_listed).forms())


def resolve_entry(
    fetcher: CandidateFetcher,
    entry: ListEntry,
    log: Callable[[str], None] = _stderr,
) -> tuple[Verdict | None, str]:
    """Resolve one list entry through the fallback-only form ladder; returns (verdict, form).

    The primary form is asked first and a `match` there is returned immediately — a form
    further down the ladder can never override an already-corroborated match. Only when the
    primary misses are `base` and then each alt title tried, stopping at the first `match`.
    When nothing matches, the **primary** form's verdict is what comes back — it was asked
    against the title the curator actually wrote, so its reason is the one worth reviewing —
    or the first form that answered at all, when the primary's own lookup failed. When every
    form's lookup failed, `(None, primary_form)` comes back.

    The query year is always `None`: the list carries no years, and inventing one actively
    misleads the resolver. Source `"list"` lands on `YearClass.APPLE_FIELD`, inert while
    `q.year is None`.
    """
    forms = entry_forms(entry.title_listed)
    answered: tuple[Verdict, str] | None = None
    for form in forms:
        # The literal, not AUTHORITY: the resolver's `source` and the claim/review authority
        # are different concepts that happen to share a string. Renaming one must not move
        # the query's YearClass.
        q = make_query(form, None, "list", director=entry.director_listed)
        try:
            verdict = resolve(q, fetcher.fetch(q))
        except (CacheMiss, requests.RequestException, AuthError, QuotaExceeded) as exc:
            log(f"resolver lookup failed for {form!r}: {exc}")
            continue
        if verdict.kind == "match" and verdict.tt is not None:
            return verdict, form
        if answered is None:
            answered = (verdict, form)
    return answered if answered is not None else (None, forms[0])


def find_holder(
    repo: Repository,
    tmdb: TmdbClient | None,
    verdict: Verdict,
    log: Callable[[str], None] = _stderr,
) -> tuple[int | None, str]:
    """Gates 1, 2 and 2b: the film already holding this work, and the gate that found it.

    The label is contract text the scorecard reads; a caller may branch on it. Seven values:

    | label | film_id | meaning |
    |---|---|---|
    | `imdb tt0006864`     | set  | gate 1 — a film is already keyed to this IMDb id |
    | `tmdb 3059`          | set  | gate 2 — a film holds the winning candidate's TMDB id |
    | `tmdb(find 3059)`    | set  | gate 2b — a film holds the TMDB id `find_by_imdb` maps this tt to |
    | `tombstoned #412`    | None | a holder exists but a human hid it: never create over it |
    | `no holder`          | None | every gate ran and missed — the would-create path |
    | `tmdb lookup failed` | None | gate 2b raised: the holder is unknown, NOT disproved |
    | `""`                 | None | the verdict is not a match, so nothing was asked |
    """
    if verdict.kind != "match" or verdict.tt is None:
        return None, ""

    # Gate 1 — a film already keyed to this IMDb id is the same work under some other title.
    holder = repo.film_id_for_external("imdb", verdict.tt)
    label = f"imdb {verdict.tt}"

    if holder is None:
        winner = next((s.candidate for s in verdict.ranked if s.candidate.tt == verdict.tt), None)
        if winner is not None and winner.tmdb_id is not None:
            # Gate 2 — the winning candidate's own TMDB id.
            holder = repo.film_id_for_external("tmdb", str(winner.tmdb_id))
            label = f"tmdb {winner.tmdb_id}"
        elif tmdb is not None:
            # Gate 2b — gate 2 asked nothing, either because the winner is OMDb-only and
            # carries no TMDB id, or because `resolve` truncates `ranked` to the top three
            # and the winner fell outside it. Both are the same question here, and gate 2b's
            # only input is `verdict.tt` — never the winner (design §1 A4, live case #69
            # Intolerance). Failing to ask fails in the CREATING direction, which is the one
            # failure this import must not make.
            try:
                tmdb_id = tmdb.find_by_imdb(verdict.tt)
            except (requests.RequestException, AuthError) as exc:
                log(f"tmdb find_by_imdb failed for {verdict.tt}: {exc}")
                return None, "tmdb lookup failed"
            if tmdb_id is not None:
                holder = repo.film_id_for_external("tmdb", str(tmdb_id))
                label = f"tmdb(find {tmdb_id})"

    if holder is None:
        return None, "no holder"
    film_id = repo.canonical_film_id(holder)
    d = repo.disposition_of(film_id)
    if d is not None and d[0] == "tombstoned":
        return None, f"tombstoned #{film_id}"
    return film_id, label


def corpus_veto(index: CandidateIndex, forms: list[str]) -> list[Candidate]:
    """Gate 3: every catalog film resembling ANY of these forms, de-duplicated, order stable.

    A veto, not a matcher — a weak, ambiguous or tied hit is reason enough for the caller to
    refuse creation and hand the entry to a human. This deliberately inverts `owned import`,
    where the corpus matcher is a *fallback* that picks a winner. Gate 3 covers the films
    holding neither id, and the case where TMDB's own id mapping does not reunite two records
    of one work.
    """
    hits: dict[int, Candidate] = {}
    for form in forms:
        for c in index.lookup(form)[1]:
            hits.setdefault(c.id, c)
    return list(hits.values())
