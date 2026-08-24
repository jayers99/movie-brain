from __future__ import annotations

import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.application.availability import MAX_CONSECUTIVE_FAILURES, TMDB_AUTHORITY
from movie_brain.domain.matching import norm_title, split_annotations
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
    repo: Repository, client: TmdbClient, *, log: Callable[[str], None] = _stderr
) -> tuple[list[LinkSuspect], int, bool]:
    """Every TMDB link whose title AND original_title both disagree with ours (Rambo/Vahşi Kan class)."""
    suspects: list[LinkSuspect] = []
    checked = consecutive = 0
    for film_id, title, year, value in repo.films_with_tmdb():
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            log("TMDB failing repeatedly — stopping; repair links is safe to re-run.")
            return suspects, checked, True
        try:
            t_title, t_orig, t_year = client.movie_titles(int(value))
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc}")
            return suspects, checked, True
        except (requests.RequestException, ValueError) as exc:
            log(f"TMDB details failed for film {film_id}: {exc}")
            consecutive += 1
            continue
        consecutive = 0
        checked += 1
        if not (_same_title(title, t_title) or _same_title(title, t_orig)):
            suspects.append(LinkSuspect(film_id, title, year, value, t_title, t_orig, t_year))
    return suspects, checked, False


def repair_links(
    repo: Repository, client: TmdbClient, today: date, *, apply: bool, log: Callable[[str], None] = _stderr
) -> LinksReport:
    suspects, checked, tripwired = audit_links(repo, client, log=log)
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
