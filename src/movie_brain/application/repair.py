from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from movie_brain.application.availability import MAX_CONSECUTIVE_FAILURES, TMDB_AUTHORITY, queue_review_once
from movie_brain.domain.matching import norm_title, split_annotations
from movie_brain.domain.models import ReviewEntry
from movie_brain.domain.thumbprint import parse_title, title_norm
from movie_brain.infrastructure.database import RepairFilm, Repository, TwinFilm
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
            detail = f"{view.title!r}: setting {year} over {view.year} collides with film {clash} — merge candidate"
            queue_review_once(
                repo,
                TMDB_AUTHORITY,
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


# --- twins: raw `Title (YYYY)` films → their same-year clean twin (thumbprint step 1) ---------


@dataclass(frozen=True)
class TwinGroup:
    raw_id: int
    raw_title: str
    embedded_year: int
    verdict: str  # "twin" | "no-twin" | "conflict" | "csv-mismatch"
    twin_id: int | None
    detail: str
    year_fix: int | None  # embedded year when films.year disagrees (Rear Window 2013 → 1954)
    imdb_id: str | None  # the raw row's OMDb imdbID (no-twin keys with it)


@dataclass(frozen=True)
class TwinsReport:
    groups: int
    twins: int
    no_twin: int
    conflict: int
    csv_mismatch: int
    applied: int
    declined: int


def load_expected_twins(csv_path: Path) -> dict[int, int]:
    """{raw film_id: twin film_id} from the eval contract's group-B `twin NNNN` notes."""
    out: dict[int, int] = {}
    if not csv_path.exists():
        return out
    with csv_path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m = re.fullmatch(r"twin (\d+)", (r.get("note") or "").strip())
            if m and r.get("film_id", "").isdigit():
                out[int(r["film_id"])] = int(m.group(1))
    return out


def audit_twins(repo: Repository, expected: dict[int, int]) -> list[TwinGroup]:
    films = repo.films_for_twins()
    by_norm_year: dict[tuple[str, int | None], list[TwinFilm]] = defaultdict(list)
    for f in films:
        by_norm_year[(title_norm(f.title), f.year)].append(f)
    groups: list[TwinGroup] = []
    for f in films:
        p = parse_title(f.title)
        if p.embedded_year is None:
            continue
        year_fix = p.embedded_year if f.year != p.embedded_year else None
        twins = [t for t in by_norm_year[(norm_title(p.base), p.embedded_year)] if t.id != f.id]
        if not twins and f.omdb_imdb:
            # ±1 year (TMDB original year vs Apple's embedded year) only with IMDb key agreement
            twins = [
                t
                for dy in (-1, 1)
                for t in by_norm_year[(norm_title(p.base), p.embedded_year + dy)]
                if t.id != f.id and t.tmdb_imdb == f.omdb_imdb
            ]
        if not twins:
            verdict, twin, detail = "no-twin", None, f"no undisposed film {p.base!r} ({p.embedded_year})"
            if not f.omdb_imdb:
                verdict, detail = "conflict", "no twin and no OMDb imdbID to key with"
        elif len(twins) > 1:
            verdict, twin, detail = "conflict", None, f"several twins {[t.id for t in twins]}"
        else:
            t = twins[0]
            if f.omdb_imdb and t.tmdb_imdb and f.omdb_imdb != t.tmdb_imdb:
                verdict, twin, detail = (
                    "conflict",
                    None,
                    f"keys disagree: raw OMDb {f.omdb_imdb} vs twin #{t.id} {t.tmdb_imdb}",
                )
            else:
                verdict, twin, detail = (
                    "twin",
                    t.id,
                    f"twin #{t.id} {t.title!r} ({t.year}) keys {f.omdb_imdb or '-'}/{t.tmdb_imdb or '-'}",
                )
        if f.id in expected and expected[f.id] != twin:
            verdict, detail = "csv-mismatch", f"contract expects twin #{expected[f.id]}, computed {twin} — {detail}"
        groups.append(TwinGroup(f.id, f.title, p.embedded_year, verdict, twin, detail, year_fix, f.omdb_imdb))
    return groups


def format_twin(g: TwinGroup) -> str:
    fix = f" year {g.year_fix} (was wrong)" if g.year_fix else ""
    return f"[{g.verdict}] #{g.raw_id} {g.raw_title!r}{fix}: {g.detail}"


def repair_twins(
    repo: Repository,
    today: date,
    *,
    apply: bool,
    confirm: Callable[[TwinGroup], bool],
    expected: dict[int, int],
    on_applied: Callable[[TwinGroup], None] = lambda g: None,
    limit: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> TwinsReport:
    """Dry-run lists every group; --apply merges each confirmed `twin` group into its twin
    and keys each confirmed `no-twin` directly. `conflict` / `csv-mismatch` are never touched."""
    groups = audit_twins(repo, expected)
    if limit is not None:
        groups = groups[:limit]
    applied = declined = 0
    for g in groups:
        log(format_twin(g))
        if not apply or g.verdict not in ("twin", "no-twin"):
            continue
        if not confirm(g):
            declined += 1
            continue
        if g.year_fix is not None:
            clash = repo.update_film_year(g.raw_id, g.year_fix)
            if clash is not None and clash != g.twin_id:
                log(f"  year fix blocked: key held by #{clash}; skipped")
                continue
        if g.verdict == "twin" and g.twin_id is not None:
            report = repo.merge_film(g.raw_id, g.twin_id, today, note=f"repair twins {g.raw_title!r}")
            log(
                f"  merged #{g.raw_id} → #{g.twin_id}: moved {report.moved} dropped {report.dropped} "
                f"reviews {report.reviews_resolved}"
            )
        else:
            base = parse_title(g.raw_title).base
            if not repo.key_film_directly(g.raw_id, new_title=base, imdb_id=g.imdb_id or "", today=today):
                log("  direct key blocked (key/imdb held elsewhere); skipped")
                continue
            log(f"  keyed #{g.raw_id} as {base!r} imdb {g.imdb_id}")
        on_applied(g)
        applied += 1
    counts = {v: sum(1 for g in groups if g.verdict == v) for v in ("twin", "no-twin", "conflict", "csv-mismatch")}
    return TwinsReport(
        len(groups), counts["twin"], counts["no-twin"], counts["conflict"], counts["csv-mismatch"], applied, declined
    )
