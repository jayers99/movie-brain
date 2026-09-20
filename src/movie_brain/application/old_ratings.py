"""Old ratings: the owner's 1-5★ ratings from 2004-08, linked to films as a WATCHING SIGNAL
(spec `docs/superpowers/specs/2026-09-19-old-ratings-design.md`).

The second caller of the curated-list pipeline's resolve → gate → create helpers, reused as
they stand rather than abstracted: a row is a title plus a typed year, exactly the director-less
shape migration 020's listed year made resolvable, so each row rides through `resolve_entry` as
a `ListEntry`. The foreign key is assigned by the resolver and gates 1/2/2b — never by a title
join (O4): a refusal costs one hand-link, a wrong link silently hangs a 1★ warning on the
wrong film.

Three differences from the list verbs, all deliberate:

- **No review rows** (O6). A row the resolver refuses or a gate blocks stays `film_id NULL` and
  is printed on the scorecard; `link_row` is the hand path.
- **No duplicate-entry block.** Two rows may name one film (the source lists one twice), and
  both link.
- **No claim rows.** `old_rating` keeps the typed title verbatim itself, and the source is not
  an ingester of films — it writes nothing the resolver should later read back.

`import_old_ratings` never creates a film on any path. `create_films` is the only creating
path, only for rows rated `MINT_MIN_STARS` or better (O5), and it re-resolves and re-gates
every row rather than trusting the import's verdict. Nothing here touches `my_ratings` (O1).
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.lists import (
    KEYED_OK,
    _candidates,
    _catalog,
    _film_label,
    _key_new_film,
    _veto_label,
    _winner,
    _would_create_label,
    corpus_veto,
    entry_forms,
    find_holder,
    resolve_entry,
    veto_forms,
)
from movie_brain.domain.matching import Candidate, CandidateIndex, build_candidate_index
from movie_brain.domain.models import Film, ListEntry, OldRating
from movie_brain.domain.thumbprint import Verdict
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.thumbprint_fetch import CandidateFetcher
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

DEFAULT_SOURCE = "ntc"
MINT_MIN_STARS = 4  # O5: a film worth rewatching has to exist; a film to avoid does not


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class RowOutcome:
    """One scorecard line. `kind`: linked / created / would-create / absent / unresolved /
    blocked / error. `absent` is a resolved work the catalog does not hold and this feature
    will not mint (rated below `MINT_MIN_STARS`) — a re-run links it the day it arrives."""

    row: OldRating
    kind: str
    detail: str
    film_id: int | None = None


@dataclass(frozen=True)
class OldRatingsReport:
    exit_code: int
    total: int
    rows: list[RowOutcome]

    def count(self, kind: str) -> int:
        return sum(1 for r in self.rows if r.kind == kind)


@dataclass(frozen=True)
class _Placed:
    kind: str
    detail: str
    film_id: int | None = None
    verdict: Verdict | None = None


def _place(
    repo: Repository,
    row: OldRating,
    *,
    fetcher: CandidateFetcher,
    tmdb: TmdbClient | None,
    index: CandidateIndex,
    catalog: dict[int, tuple[str, int | None, str | None]],
    minted: dict[str, int],
    log: Callable[[str], None],
) -> _Placed:
    """Resolve one row and run the gates; writes nothing. Shared by both verbs so the import's
    card predicts the confirmed create run."""
    entry = ListEntry(row.line, row.title, None, year_listed=row.year)
    verdict, _form = resolve_entry(fetcher, entry, log)
    if verdict is None:
        return _Placed("error", "resolver lookup failed for every form")
    if verdict.kind != "match" or verdict.tt is None:
        return _Placed("unresolved", f"resolver {verdict.reason!r}  cands: {_candidates(verdict)}")

    holder, label = minted.get(verdict.tt), "minted this run"
    if holder is None:
        holder, label = find_holder(repo, tmdb, verdict, log)
    if label == "tmdb lookup failed":
        return _Placed("error", f"gate 2b: tmdb lookup failed — holder unknown  [{verdict.reason}]")
    if holder is None and label.startswith("tombstoned"):
        return _Placed("blocked", f"tombstoned-holder  {label}  [{verdict.reason}]")
    if holder is not None:
        return _Placed("linked", f"{_film_label(catalog, holder)}  via {label}  [{verdict.reason}]", holder, verdict)

    if row.stars < MINT_MIN_STARS:
        return _Placed("absent", f"not in the catalog: {_would_create_label(verdict)}  [{verdict.reason}]")
    hits = corpus_veto(index, veto_forms(entry_forms(row.title), _winner(verdict)))
    if hits:
        return _Placed("blocked", f"corpus-veto  {_veto_label(hits)}  [{verdict.reason}]")
    return _Placed("would-create", f"{_would_create_label(verdict)}  [{verdict.reason}]", None, verdict)


def import_old_ratings(
    repo: Repository,
    source: str,
    rows: Sequence[OldRating],
    today: date,
    *,
    fetcher: CandidateFetcher,
    tmdb: TmdbClient | None,
    apply: bool = False,
    log: Callable[[str], None] = _stderr,
) -> OldRatingsReport:
    """Store every row, link what the catalog already holds (spec §4.1). NEVER creates a film.

    Dry run by default and a dry run writes nothing. Idempotent: a row already carrying a
    `film_id` is settled and skipped before the fetcher is touched; `upsert_old_rating` never
    clears or re-points a link. So a re-run only ever links rows that were NULL — which is how
    an `absent` 1★ film picks up its warning after sync or a list brings it in.
    """
    settled = {r.line: r.film_id for r in repo.old_ratings(source) if r.film_id is not None}
    if apply:
        for row in rows:
            repo.upsert_old_rating(source, row)

    film_rows = repo.films_for_matching()
    index = build_candidate_index(film_rows)
    catalog = _catalog(repo, film_rows)

    out: list[RowOutcome] = []
    for row in rows:
        try:
            held = settled.get(row.line)
            if held is not None:
                out.append(RowOutcome(row, "linked", f"{_film_label(catalog, held)}  already linked", held))
                continue
            p = _place(repo, row, fetcher=fetcher, tmdb=tmdb, index=index, catalog=catalog, minted={}, log=log)
            if p.kind == "linked" and p.film_id is not None and apply:
                repo.link_old_rating(source, row.line, p.film_id, "resolver", today)
            out.append(RowOutcome(row, p.kind, p.detail, p.film_id))
        except Exception as exc:  # one bad row must never abort the run
            log(f"old rating {source}#{row.line} failed: {exc}")
            out.append(RowOutcome(row, "error", f"unexpected failure: {exc}"))
    return OldRatingsReport(0, len(rows), out)


def create_films(
    repo: Repository,
    source: str,
    today: date,
    *,
    fetcher: CandidateFetcher,
    tmdb: TmdbClient | None,
    apply: bool = False,
    log: Callable[[str], None] = _stderr,
) -> OldRatingsReport:
    """The ONE path here that creates a film (spec §4.2): stored rows with no film and
    `stars >= MINT_MIN_STARS`, each re-resolved and re-gated. A holder that appeared since the
    import is linked, never twinned; two rows naming one work mint once (`minted`), the second
    linking to the first. Born keyed through `_key_new_film`. `tmdb=None` refuses the whole run:
    gate 2b is not optional on a creating path.
    """
    if tmdb is None:
        log("no TMDB client — gate 2b cannot run, so creation would be unguarded; refusing")
        return OldRatingsReport(1, 0, [])

    worklist = [r for r in repo.old_ratings(source) if r.film_id is None and r.stars >= MINT_MIN_STARS]
    film_rows = repo.films_for_matching()
    index = build_candidate_index(film_rows)
    catalog = _catalog(repo, film_rows)
    tombstoned = repo.tombstoned_keys()
    minted: dict[str, int] = {}

    out: list[RowOutcome] = []
    for row in worklist:
        try:
            p = _place(repo, row, fetcher=fetcher, tmdb=tmdb, index=index, catalog=catalog, minted=minted, log=log)
            if p.kind == "linked" and p.film_id is not None:
                if apply:
                    repo.link_old_rating(source, row.line, p.film_id, "resolver", today)
                out.append(RowOutcome(row, "linked", p.detail, p.film_id))
                continue
            if p.kind != "would-create" or p.verdict is None or p.verdict.tt is None:
                out.append(RowOutcome(row, p.kind, p.detail))
                continue

            verdict = p.verdict
            tt = p.verdict.tt
            winner = _winner(verdict)
            title = winner.titles[0] if winner is not None and winner.titles else row.title
            year = winner.year if winner is not None else row.year
            film = Film(title, year, None, "")
            if film.key in tombstoned:
                out.append(RowOutcome(row, "blocked", f"tombstoned-holder  key {film.key!r} is tombstoned"))
                continue
            if not apply:
                out.append(RowOutcome(row, "would-create", p.detail))
                continue

            film_id = repo.create_film(film)
            if film_id is None:
                # A films.key holder the gates did not surface. Never adopt it: that is how a
                # wrong link is made.
                clash = repo.canonical_film_id(repo.film_id_by_key(film.key) or 0)
                detail = f"key-collision  {film.key!r} is held by {_film_label(catalog, clash)}"
                out.append(RowOutcome(row, "blocked", detail))
                continue
            index.add(Candidate(id=film_id, title=title, year=year))
            catalog[film_id] = (title, year, None)
            minted[tt] = film_id
            repo.link_old_rating(source, row.line, film_id, "created", today)
            status = _key_new_film(repo, tmdb, film_id, tt, winner.tmdb_id if winner else None, today, log)
            keyed = status if status in KEYED_OK else f"{status} (the next sync retries)"
            detail = f"{_film_label(catalog, film_id)}  {keyed}  from {p.detail}"
            out.append(RowOutcome(row, "created", detail, film_id))
        except Exception as exc:  # one bad row must never abort the run
            log(f"old rating {source}#{row.line} failed: {exc}")
            out.append(RowOutcome(row, "error", f"unexpected failure: {exc}"))
    return OldRatingsReport(0, len(worklist), out)


class LinkError(ValueError):
    pass


def link_row(repo: Repository, source: str, line: int, film_id: int | None, today: date) -> int | None:
    """The hand path (spec §4.3): point one row at a film, or clear it with `film_id=None`.
    A merged-away film is followed to its survivor; a tombstoned or unknown one is refused."""
    if not any(r.line == line for r in repo.old_ratings(source)):
        raise LinkError(f"no old rating {source}#{line}")
    target: int | None = None
    if film_id is not None:
        target = repo.canonical_film_id(film_id)
        if repo.get_view(target) is None:
            raise LinkError(f"film #{film_id} does not exist or is tombstoned")
    repo.link_old_rating(source, line, target, "hand" if target is not None else None, today)
    return target


_TT = re.compile(r"tt\d{7,}")


def create_by_hand(
    repo: Repository,
    source: str,
    line: int,
    tt: str,
    today: date,
    *,
    tmdb: TmdbClient | None,
    apply: bool = False,
    log: Callable[[str], None] = _stderr,
) -> RowOutcome:
    """The hand CREATING path (spec §6 deferred it; built 2026-09-20 for the four 4★ rows the
    resolver cannot read): the owner supplies the IMDb id of one unlinked row.

    The id settles WHICH work the row names — never whether the catalog already holds it, so
    the gates run unchanged: gate 1 and gate 2b through `find_holder` (a holder is LINKED, by
    "hand", never twinned) and gate 3 over the row's own forms plus TMDB's titles. The film is
    minted under TMDB's title and year, because the row's title is the very thing that could not
    be read, and is born keyed. `MINT_MIN_STARS` holds here too: 1-3★ never mint (O5).
    A refusal to even try raises `LinkError`; everything after that is a `RowOutcome`.
    """
    row = next((r for r in repo.old_ratings(source) if r.line == line), None)
    if row is None:
        raise LinkError(f"no old rating {source}#{line}")
    if row.film_id is not None:
        raise LinkError(f"{source}#{line} is already linked to film #{row.film_id} — clear it first")
    if row.stars < MINT_MIN_STARS:
        raise LinkError(f"{source}#{line} is {row.stars}★ — only {MINT_MIN_STARS}★ and better mint a film")
    if not _TT.fullmatch(tt):
        raise LinkError(f"{tt!r} is not an IMDb id (tt1234567)")
    if tmdb is None:
        raise LinkError("no TMDB client — gate 2b cannot run, so creation would be unguarded")

    film_rows = repo.films_for_matching()
    catalog = _catalog(repo, film_rows)
    holder, label = find_holder(repo, tmdb, Verdict("match", tt, "id supplied by hand", ()), log)
    if label == "tmdb lookup failed":
        return RowOutcome(row, "error", "gate 2b: tmdb lookup failed — holder unknown")
    if holder is None and label.startswith("tombstoned"):
        return RowOutcome(row, "blocked", f"tombstoned-holder  {label}")
    if holder is not None:
        if apply:
            repo.link_old_rating(source, line, holder, "hand", today)
        return RowOutcome(row, "linked", f"{_film_label(catalog, holder)}  via {label}  [id supplied by hand]", holder)

    try:
        tmdb_id = tmdb.find_by_imdb(tt)
        facts = tmdb.movie_facts(tmdb_id) if tmdb_id is not None else None
    except (requests.RequestException, AuthError) as exc:
        return RowOutcome(row, "error", f"tmdb lookup failed for {tt}: {exc}")
    if tmdb_id is None or facts is None:
        return RowOutcome(row, "blocked", f"TMDB does not know {tt} as a film")
    film = Film(facts.title, facts.year, None, "")
    wanted = f"{tt} {facts.title!r} ({facts.year or '-'})"
    titles = [t for t in (facts.title, facts.original_title) if t]
    hits = corpus_veto(build_candidate_index(film_rows), entry_forms(row.title) + titles)
    if hits:
        return RowOutcome(row, "blocked", f"corpus-veto  {_veto_label(hits)}  wanted {wanted}")
    if film.key in repo.tombstoned_keys():
        return RowOutcome(row, "blocked", f"tombstoned-holder  key {film.key!r} is tombstoned")
    if not apply:
        return RowOutcome(row, "would-create", f"{wanted}  [id supplied by hand]")

    film_id = repo.create_film(film)
    if film_id is None:
        clash = repo.canonical_film_id(repo.film_id_by_key(film.key) or 0)
        return RowOutcome(row, "blocked", f"key-collision  {film.key!r} is held by {_film_label(catalog, clash)}")
    repo.link_old_rating(source, line, film_id, "created", today)
    status = _key_new_film(repo, tmdb, film_id, tt, tmdb_id, today, log)
    keyed = status if status in KEYED_OK else f"{status} (the next sync retries)"
    return RowOutcome(row, "created", f"#{film_id} {wanted}  {keyed}  [id supplied by hand]", film_id)


_ORDER = ("linked", "created", "would-create", "absent", "unresolved", "blocked", "error")


def scorecard(rows: Sequence[RowOutcome]) -> str:
    """Every row gets its two-line block — a wrong link is silent, so nothing is abbreviated."""
    lines: list[str] = []
    for r in rows:
        year = f" ({r.row.year})" if r.row.year is not None else ""
        lines.append(f"{r.row.line:>4}  {'★' * r.row.stars:<5}  {r.kind.upper():<13} {r.row.title}{year}")
        lines.append(f"      {r.detail}")
    tally = Counter(r.kind for r in rows)
    lines.append("")
    lines.append("  ".join(f"{k} {tally[k]}" for k in _ORDER) + f"  (of {len(rows)})")
    return "\n".join(lines)
