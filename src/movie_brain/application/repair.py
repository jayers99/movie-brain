from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.availability import MAX_CONSECUTIVE_FAILURES, TMDB_AUTHORITY, queue_review_once
from movie_brain.domain.matching import norm_title, split_annotations
from movie_brain.domain.models import ReviewEntry
from movie_brain.infrastructure.database import RepairFilm, Repository
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class DupGroup:
    key: str
    films: tuple[RepairFilm, ...]
    verdict: str  # "twin" | "distinct" | "undecided"
    survivor: int | None
    losers: tuple[int, ...]
    source: str  # "norm-title" | "id-conflict"


@dataclass(frozen=True)
class DupesReport:
    groups: int
    twins: int
    distinct: int
    undecided: int
    merged: int
    declined: int


def _rank(f: RepairFilm) -> tuple[int, ...]:
    """Survivor policy: Criterion-listed > rated > owned > watchlisted > OMDb-found > oldest id."""
    return (f.criterion, f.rated, f.owned, f.watchlisted, f.omdb_found, -f.id)


def _group_key(title: str) -> str:
    return norm_title(split_annotations(title)[0])


def _classify(key: str, films: tuple[RepairFilm, ...], source: str) -> DupGroup:
    ids = {f.tmdb for f in films}
    if source == "id-conflict" and len({_group_key(f.title) for f in films}) != 1:
        # The loser was lent the holder's own tmdb id purely so this function can reuse the
        # id-equality test below — that makes every id-conflict pair look like a twin by
        # construction. A title mismatch means the flagged film's claim is bogus (it's not
        # the holder's twin at all), so refuse to classify on the borrowed id.
        return DupGroup(key, films, "undecided", None, (), source)
    if len(films) >= 2 and len(ids) == 1 and None not in ids:
        survivor = max(films, key=_rank)
        return DupGroup(key, films, "twin", survivor.id, tuple(f.id for f in films if f.id != survivor.id), source)
    if None not in ids and len(ids) == len(films):
        return DupGroup(key, films, "distinct", None, (), source)
    return DupGroup(key, films, "undecided", None, (), source)


def audit_dupes(repo: Repository) -> list[DupGroup]:
    """Norm-title groups plus id-conflict pairs, classified by TMDB id equality (re-derived now)."""
    films = {f.id: f for f in repo.films_for_repair()}
    # id-conflict rows: the flagged film could not claim the id its twin holds — lend it the
    # claimed id for classification (value re-derived against the current holder).
    claimed: dict[int, str] = {}
    pairs: list[tuple[int, int]] = []
    for r in repo.open_reviews(TMDB_AUTHORITY):
        if r["reason"] != "id-conflict" or r["film_id"] not in films or not r["value"]:
            continue
        holder = repo.film_id_for_external(TMDB_AUTHORITY, str(r["value"]))
        if holder is None or holder not in films or holder == r["film_id"]:
            continue
        claimed[int(r["film_id"])] = str(r["value"])
        pairs.append((int(r["film_id"]), holder))
    by_key: dict[str, list[RepairFilm]] = defaultdict(list)
    for f in films.values():
        by_key[_group_key(f.title)].append(f)
    groups: list[DupGroup] = []
    paired: set[int] = set()
    for loser, holder in pairs:
        lent = films[loser]._replace(tmdb=claimed[loser])
        groups.append(_classify(_group_key(films[holder].title), (films[holder], lent), "id-conflict"))
        paired.update((loser, holder))
    for key, members in sorted(by_key.items()):
        # Filter out members already covered by an id-conflict pair above, per-member —
        # not all-or-nothing — so a bucket of e.g. [A, B, C] where {A, B} were already
        # paired off doesn't spuriously reclassify the whole trio (with the paired films'
        # real tmdb ids re-attached) as a second, undecided/distinct group.
        rest = [m for m in members if m.id not in paired]
        if len(rest) < 2:
            continue
        groups.append(_classify(key, tuple(m._replace(tmdb=claimed.get(m.id, m.tmdb)) for m in rest), "norm-title"))
    return groups


def format_group(g: DupGroup) -> str:
    lines = [f"[{g.verdict}] {g.key!r} ({g.source})"]
    for f in g.films:
        role = "survivor" if f.id == g.survivor else ("loser" if f.id in g.losers else "")
        pairs = (("criterion", f.criterion), ("rated", f.rated), ("owned", f.owned), ("watchlist", f.watchlisted))
        flags = " ".join(n for n, on in pairs if on)
        lines.append(f"  #{f.id:<5} {f.title!r} ({f.year}) tmdb={f.tmdb or '-'} {flags} {role}")
    return "\n".join(lines)


def repair_dupes(
    repo: Repository,
    today: date,
    *,
    apply: bool,
    confirm: Callable[[DupGroup], bool],
    log: Callable[[str], None] = _stderr,
) -> DupesReport:
    """Dry-run lists every group; --apply merges each TWIN group the confirm callback approves.

    Only twins (same TMDB id) are ever merged here; distinct groups are reported and kept,
    undecided groups need `review resolve` / a manual merge after a human look.
    """
    groups = audit_dupes(repo)
    merged = declined = 0
    for g in groups:
        log(format_group(g))
        if not apply or g.verdict != "twin" or g.survivor is None:
            continue
        if not confirm(g):
            declined += 1
            continue
        for loser in g.losers:
            report = repo.merge_film(loser, g.survivor, today, note=f"repair dupes {g.source} {g.key!r}")
            log(f"  merged #{loser} → #{g.survivor}: moved {report.moved} dropped {report.dropped}")
            merged += 1
    counts = {v: sum(1 for g in groups if g.verdict == v) for v in ("twin", "distinct", "undecided")}
    return DupesReport(len(groups), counts["twin"], counts["distinct"], counts["undecided"], merged, declined)


@dataclass(frozen=True)
class LinkSuspect:
    film_id: int
    title: str
    year: int | None
    tmdb_id: str
    tmdb_title: str
    tmdb_original: str
    tmdb_year: int | None


@dataclass(frozen=True)
class LinksReport:
    exit_code: int
    checked: int
    suspects: int
    cleared: int


def _same_title(ours: str, theirs: str) -> bool:
    return norm_title(split_annotations(ours)[0]) == norm_title(split_annotations(theirs)[0])


def audit_links(
    repo: Repository, client: TmdbClient, *, film_id: int | None = None, log: Callable[[str], None] = _stderr
) -> tuple[list[LinkSuspect], int, bool]:
    """Every TMDB link whose title, original_title AND alternative titles all disagree with ours
    (Rambo/Vahşi Kan class). With ``film_id`` the audit is that one film, and it is a suspect
    unconditionally — the human is asserting the link is wrong."""
    suspects: list[LinkSuspect] = []
    checked = consecutive = 0
    linked = repo.films_with_tmdb()
    if film_id is not None:
        linked = [row for row in linked if row[0] == film_id]
        if not linked:
            raise LookupError(f"film {film_id} holds no TMDB link (or is unknown / disposed)")
    for fid, title, year, value in linked:
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB failing repeatedly — stopping; repair links is safe to re-run.")
            return suspects, checked, True
        try:
            t = client.movie_titles(int(value))
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return suspects, checked, True
        except (requests.RequestException, ValueError) as exc:
            log(f"TMDB details failed for film {fid}: {exc}")
            consecutive += 1
            continue
        consecutive = 0
        checked += 1
        known = (t.title, t.original, *t.alternatives)
        if film_id is not None or not any(_same_title(title, k) for k in known):
            suspects.append(LinkSuspect(fid, title, year, value, t.title, t.original, t.year))
    return suspects, checked, False


def repair_links(
    repo: Repository,
    client: TmdbClient,
    today: date,
    *,
    film_id: int | None = None,
    apply: bool,
    log: Callable[[str], None] = _stderr,
) -> LinksReport:
    """Audit every link (or one film with ``film_id``); --apply clears the suspects for rematch."""
    suspects, checked, tripwired = audit_links(repo, client, film_id=film_id, log=log)
    for s in suspects:
        log(
            f"#{s.film_id:<5} {s.title!r} ({s.year}) → tmdb {s.tmdb_id} "
            f"{s.tmdb_title!r} / {s.tmdb_original!r} ({s.tmdb_year})"
        )
    cleared = 0
    if apply:
        for s in suspects:
            repo.clear_tmdb_link(s.film_id, today)
            cleared += 1
        if cleared:
            log(f"cleared {cleared} links — run `movie-brain rematch` to re-match them with the current matcher")
    return LinksReport(1 if tripwired else 0, checked, len(suspects), cleared)


@dataclass(frozen=True)
class YearsAudit:
    collisions: tuple[dict[str, object], ...]
    stale: tuple[tuple[int, str, int | None, int], ...]


@dataclass(frozen=True)
class YearsReport:
    collisions: int
    stale: int
    refresh_marked: int
    changed: bool = False
    collided_with: int | None = None


def audit_years(repo: Repository) -> YearsAudit:
    collisions = tuple(r for r in repo.list_reviews(TMDB_AUTHORITY, "year-collision"))
    return YearsAudit(collisions, tuple(repo.stale_omdb_years()))


def repair_years(
    repo: Repository,
    today: date,
    *,
    film_id: int | None = None,
    year: int | None = None,
    apply: bool,
    log: Callable[[str], None] = _stderr,
) -> YearsReport:
    """No args: list the worklist (open year-collisions + stale OMDb payloads); --apply marks the
    stale payloads for refetch. With FILM_ID YEAR: dry-run the correction; --apply writes it
    through update_film_year (collision → year-collision review, never an overwrite) and marks
    the film's OMDb row for refetch so ratings/director/runtime are re-fetched under the new year."""
    if (film_id is None) != (year is None):
        raise ValueError("give both FILM_ID and YEAR, or neither")
    audit = audit_years(repo)
    if film_id is not None and year is not None:
        view = repo.get_view(film_id)
        if view is None:
            raise LookupError(f"unknown film {film_id}")
        log(f"#{film_id} {view.title!r}: {view.year} → {year}{'' if apply else ' (dry-run)'}")
        if not apply:
            return YearsReport(len(audit.collisions), len(audit.stale), 0)
        clash = repo.update_film_year(film_id, year)
        if clash is not None:
            detail = (
                f"{view.title!r}: setting {year} over {view.year} "
                f"collides with film {clash} — merge candidate"
            )
            queue_review_once(
                repo, TMDB_AUTHORITY,
                ReviewEntry("year-collision", film_id=film_id, value=str(clash), detail=detail),
                today,
            )
            log(f"collides with film {clash} — queued year-collision, nothing written")
            return YearsReport(len(audit.collisions), len(audit.stale), 0, False, clash)
        repo.mark_omdb_refresh(film_id)
        repo.clear_revisit(film_id)
        return YearsReport(len(audit.collisions), len(audit.stale), 1, True)
    for r in audit.collisions:
        log(
            f"collision #{r['id']}: film {r['film_id']} {r['title']!r} ({r['year']}) "
            f"vs film {r['value']} — {r['detail']}"
        )
    for fid, title, fy, oy in audit.stale:
        log(f"stale omdb: #{fid} {title!r} year {fy}, payload fetched for {oy}")
    marked = 0
    if apply:
        for fid, _t, _fy, _oy in audit.stale:
            repo.mark_omdb_refresh(fid)
            marked += 1
    return YearsReport(len(audit.collisions), len(audit.stale), marked)
