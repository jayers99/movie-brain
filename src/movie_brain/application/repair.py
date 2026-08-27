from __future__ import annotations

import csv
import re
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from movie_brain.application.availability import (
    MAX_CONSECUTIVE_FAILURES,
    TMDB_AUTHORITY,
    queue_review_once,
    record_tmdb_match,
)
from movie_brain.application.thumbprint import review_detail
from movie_brain.domain.matching import norm_title, split_annotations
from movie_brain.domain.models import ReviewEntry, film_key
from movie_brain.domain.thumbprint import Verdict, make_query, parse_title, resolve, title_norm
from movie_brain.infrastructure.database import (
    ClaimRow,
    DisagreementFilm,
    EditionFilm,
    RepairFilm,
    Repository,
    TwinFilm,
)
from movie_brain.infrastructure.thumbprint_fetch import CacheMiss, CandidateFetcher
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


# --- editions: edition-year films → their work (thumbprint step 2) --------------------------

_WORK_NOTE = re.compile(r"work='(?P<title>.+?)' (?P<year>\d{4})")


@dataclass(frozen=True)
class EditionContract:
    film_id: int
    work_title_note: str  # the CSV's TMDB title: casing/punctuation only, never a retitle to another work
    work_year: int
    tt: str
    tmdb_id: str | None


@dataclass(frozen=True)
class EditionGroup:
    film_id: int
    title: str
    old_year: int | None
    work_title: str
    work_year: int
    tt: str
    tmdb_id: str | None
    verdict: str  # "twin" | "no-twin" | "conflict" | "csv-mismatch"
    twin_id: int | None
    edition_year: int | None
    detail: str
    twin_title: str | None = None  # the survivor's title, so the apply step never re-reads films


@dataclass(frozen=True)
class EditionsReport:
    groups: int
    twins: int
    no_twin: int
    conflict: int
    csv_mismatch: int
    applied: int
    declined: int


def load_edition_contract(csv_path: Path) -> dict[int, EditionContract]:
    """Verified group-C rows with an expected tt, keyed by film id; the note's `work='…' YYYY`
    is the work year. `F-human` rows (written by `eval_log.ratify` when a human resolved a
    review) join the contract on the same terms — the `work='…' YYYY` note IS the ratification
    that this row is an edition of that work, so an F-human row without one is not a contract."""
    out: dict[int, EditionContract] = {}
    if not csv_path.exists():
        return out
    with csv_path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m = _WORK_NOTE.search(r.get("note") or "")
            if r["group"] not in ("C-edition", "F-human") or r["status"] != "verified":
                continue
            if not r["expected_tt"] or not m:
                continue
            if not r["film_id"].isdigit():
                continue
            out[int(r["film_id"])] = EditionContract(
                int(r["film_id"]),
                m["title"],
                int(m["year"]),
                r["expected_tt"],
                r.get("expected_tmdb") or None,
            )
    return out


def _work_title(base: str, note: str) -> str:
    """The work's display title: the film's own parsed base, upgraded to the contract note's
    CASING when the two are the same string (Criterion's shouty "SCENES FROM A MARRIAGE" →
    "Scenes from a Marriage", "Goodfellas" → "GoodFellas"). Case is the only difference allowed:
    `film_key` lowercases, so a casefold-equal swap cannot move `films.key`, while a
    punctuation/accent-insensitive one could. A note naming a DIFFERENT title (TMDB's English
    "Jenny Lamour" for "Quai des Orfèvres") is informational only and never retitles the film."""
    return note if base.casefold() == note.casefold() else base


def _edition_blockers(
    repo: Repository,
    c: EditionContract,
    work_title: str,
    *,
    allowed: set[int],
    tt_holders: dict[str, int],
    tmdb_holders: dict[str, int],
    rekey_id: int | None,
    twin: EditionFilm | None = None,
) -> list[str]:
    """Identities already holding what the write needs — `key_work`'s refusals and the
    `external_ids` UNIQUE guard, computed BEFORE anything is written. `allowed` are the ids the
    write may legitimately land on: the film itself, plus (twin path) the survivor it merges into.
    `rekey_id` is the film whose `films.key` the fold would rewrite, or None when nothing
    re-keys (a clean survivor keeps its own key)."""
    blockers: list[str] = []
    if rekey_id is not None:
        key = film_key(work_title, c.work_year)
        holder = repo.film_id_by_key(key)
        if holder is not None and holder not in allowed and repo.canonical_film_id(holder) not in allowed:
            blockers.append(f"key {key!r} held by #{holder}")
        if repo.has_listing(rekey_id, "criterion"):
            # `record_catalog` upserts ON CONFLICT(films.key): re-keying a film Criterion still
            # lists makes the next walk mint a fresh film under the old key and strand this one.
            # Deferred to the ingester switch, where the resolver — not the key — owns identity.
            blockers.append("criterion listing — re-key deferred to the ingester switch")
    if twin is not None and twin.imdb_id and twin.imdb_id != c.tt:
        # The twin merge writes the contract tt onto the survivor; a survivor already keyed to a
        # DIFFERENT work is not this work's twin, and silently keeping its id hides the mismatch.
        blockers.append(f"holds imdb {twin.imdb_id}, contract says {c.tt}")
    tt_holder = tt_holders.get(c.tt)
    if tt_holder is not None and tt_holder not in allowed:
        blockers.append(f"{c.tt} held by #{tt_holder}")
    tmdb_holder = tmdb_holders.get(c.tmdb_id) if c.tmdb_id else None
    if tmdb_holder is not None and tmdb_holder not in allowed:
        blockers.append(f"tmdb {c.tmdb_id} held by #{tmdb_holder}")
    return blockers


def _edition_claim(repo: Repository, film_id: int) -> ClaimRow | None:
    """The claim that named the edition: one carrying an `edition_label` wins, else the
    metacritic → apple-tv → criterion order. One read."""
    claims = repo.claims_for_film(film_id)
    labelled = [c for c in claims if c.edition_label]
    if labelled:
        return labelled[0]
    order = {"metacritic": 0, "apple-tv": 1, "criterion": 2}
    ranked = sorted((c for c in claims if c.authority in order), key=lambda c: (order[c.authority], c.id))
    return ranked[0] if ranked else None


def audit_editions(repo: Repository, contract: dict[int, EditionContract]) -> list[EditionGroup]:
    films = {f.id: f for f in repo.films_for_editions()}
    by_norm_year: dict[tuple[str, int | None], list[EditionFilm]] = defaultdict(list)
    for row in films.values():
        by_norm_year[(row.title_norm or title_norm(row.title), row.year)].append(row)
    # Holders come from EVERY film, disposed included: `films_for_editions` is the candidate
    # scan (live films only), but the UNIQUE(authority, value) guard `key_work` runs into is
    # blind to dispositions.
    tt_holders = repo.external_id_holders("imdb")
    tmdb_holders = repo.external_id_holders("tmdb")
    groups: list[EditionGroup] = []
    for fid, c in sorted(contract.items()):
        f = films.get(fid)
        if f is None:
            continue  # disposed: a previous run folded it away
        p = parse_title(f.title)
        if f.year == c.work_year and not p.editions:
            # Idempotence: sitting at the work year is not enough — the row must also have
            # stopped looking like an edition. A SAME-YEAR edition ("Apocalypse Now (Final Cut)"
            # 1979 beside the work at 1979) still needs folding; once folded it is either
            # disposed (twin) or retitled to a marker-free base (no-twin), so both paths land
            # here on the next run.
            continue
        work_title = _work_title(p.base, c.work_title_note)
        # `>` not `>=`: an edition released the SAME year as the work carries no edition year —
        # only a later re-release/restoration year is one (and an earlier year never is).
        edition_year = f.year if f.year is not None and f.year > c.work_year else None
        base = (fid, f.title, f.year, work_title, c.work_year, c.tt, c.tmdb_id)
        if not p.editions and title_norm(f.title) != title_norm(c.work_title_note):
            # The row no longer looks like an edition of anything: nothing to fold.
            groups.append(
                EditionGroup(
                    *base,
                    "csv-mismatch",
                    None,
                    edition_year,
                    f"no edition marker and title parses to {p.base!r}, contract names {c.work_title_note!r}",
                )
            )
            continue
        cands = [t for t in by_norm_year[(title_norm(work_title), c.work_year)] if t.id != fid]
        # The tmdb id is the strong agreement; the fellow-contract fallback exists only for the
        # case where NO candidate holds the id at all (Donnie Darko: two editions, neither
        # keyed). Once a candidate holds it, an unkeyed fellow edition beside the real work is
        # not a rival reading — counting it turned "Apocalypse Now Redux" beside #3190 (tmdb 28)
        # and the unkeyed "(Final Cut)" into `several agreeing twins`, a conflict that only
        # cleared on a SECOND pass once the Final Cut had merged away.
        by_id = [t for t in cands if t.tmdb_id is not None and t.tmdb_id == c.tmdb_id]
        agreeing = by_id or [
            t for t in cands if t.tmdb_id is None and t.id in contract and contract[t.id].tt == c.tt
        ]
        if len(agreeing) == 1:
            t = agreeing[0]
            # The survivor is re-keyed only when its own title still parses with editions; the
            # imdb id is written to it either way, so tt/tmdb holders always block.
            blockers = _edition_blockers(
                repo,
                c,
                work_title,
                allowed={fid, t.id},
                tt_holders=tt_holders,
                tmdb_holders=tmdb_holders,
                rekey_id=t.id if parse_title(t.title).editions else None,
                twin=t,
            )
            if blockers:
                detail = f"twin #{t.id} but " + "; ".join(blockers)
                groups.append(EditionGroup(*base, "conflict", None, edition_year, detail, t.title))
            else:
                groups.append(
                    EditionGroup(
                        *base,
                        "twin",
                        t.id,
                        edition_year,
                        f"twin #{t.id} {t.title!r} ({t.year}) tmdb {t.tmdb_id or '-'}",
                        t.title,
                    )
                )
        elif agreeing:
            detail = f"several agreeing twins {[t.id for t in agreeing]}"
            groups.append(EditionGroup(*base, "conflict", None, edition_year, detail))
        else:
            blockers = _edition_blockers(
                repo,
                c,
                work_title,
                allowed={fid},
                tt_holders=tt_holders,
                tmdb_holders=tmdb_holders,
                rekey_id=fid,
            )
            if blockers:
                groups.append(EditionGroup(*base, "conflict", None, edition_year, "; ".join(blockers)))
            else:
                groups.append(
                    EditionGroup(
                        *base,
                        "no-twin",
                        None,
                        edition_year,
                        f"becomes {work_title!r} ({c.work_year}) {c.tt}/{c.tmdb_id or '-'}",
                    )
                )
    return _dedup_survivor_groups(groups)


def _dedup_survivor_groups(groups: list[EditionGroup]) -> list[EditionGroup]:
    """Two passes over the raw verdicts, both about a survivor that is ITSELF a contract row.

    1. MUTUAL twins. Two same-year editions of one work, neither holding the tmdb id, are each
       other's fellow-contract twin — two `twin` groups pointing at each other. Applying both
       merges A into B and then asks `merge_film` to merge B into the now-dispositioned A, which
       raises AFTER the first merge has committed. The pair is broken deterministically toward
       the LOWER id: the higher id's group survives and merges into the lower, whose own group is
       dropped. The lower one is re-keyed as the work by the twin path (its title still parses
       with editions, or it would not have been a group at all).
    2. The survivor's NON-twin groups (`no-twin`, `conflict`, `csv-mismatch`). A twin always sits
       AT the work year, so after the same-year rule the survivor's own group exists only when its
       title still parses with editions — exactly the re-key the twin path already performs.
       Listing it again would double-count one fold and, once the loser's ids move onto it, report
       them as `conflict` blockers against it. Dropped only when the twin group really will do
       that work: same `(work_title, work_year, tt)`, and a survivor title that parses with
       editions. Anything else is a DIFFERENT fold and stays listed.
    """
    twins = {g.film_id: g for g in groups if g.verdict == "twin"}
    dropped: set[int] = set()
    for g in twins.values():
        other = twins.get(g.twin_id) if g.twin_id is not None else None
        if other is not None and other.twin_id == g.film_id and g.film_id < other.film_id:
            dropped.add(g.film_id)
    for g in groups:
        if g.verdict == "twin" or g.film_id in dropped:
            continue
        folder = next(
            (
                t
                for t in twins.values()
                if t.film_id not in dropped
                and t.twin_id == g.film_id
                and (t.work_title, t.work_year, t.tt) == (g.work_title, g.work_year, g.tt)
                and t.twin_title is not None
                and parse_title(t.twin_title).editions
            ),
            None,
        )
        if folder is not None:
            dropped.add(g.film_id)
    return [g for g in groups if g.film_id not in dropped]


def format_edition(g: EditionGroup) -> str:
    ey = f" edition_year {g.edition_year}" if g.edition_year else " edition_year NULL"
    return f"[{g.verdict}] #{g.film_id} {g.title!r} ({g.old_year}) → {g.work_title!r} ({g.work_year}){ey}: {g.detail}"


def _key_as_work(repo: Repository, fid: int, g: EditionGroup, today: date, log: Callable[[str], None]) -> bool:
    if not repo.key_work(fid, title=g.work_title, year=g.work_year, tt=g.tt, tmdb_id=g.tmdb_id, today=today):
        log("  key blocked (key/tt/tmdb held elsewhere); skipped")
        return False
    for r in repo.open_reviews("tmdb"):
        if r["film_id"] == fid and r["reason"] == "no-match":
            repo.resolve_review(int(str(r["id"])), f"repair editions keyed tmdb {g.tmdb_id or '-'} {today.isoformat()}")
    repo.mark_omdb_refresh(fid)  # the OMDb stub was fetched under the edition's year
    repo.clear_revisit(fid)
    return True


def repair_editions(
    repo: Repository,
    today: date,
    *,
    apply: bool,
    confirm: Callable[[EditionGroup], bool],
    contract: dict[int, EditionContract],
    limit: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> EditionsReport:
    """Dry-run lists every group; --apply merges each confirmed `twin` into its work and keys
    each confirmed `no-twin` as the work. `conflict` / `csv-mismatch` are never touched."""
    groups = audit_editions(repo, contract)
    if limit is not None:
        groups = groups[:limit]
    applied = declined = 0
    for g in groups:
        log(format_edition(g))
        if not apply or g.verdict not in ("twin", "no-twin"):
            continue
        if not confirm(g):
            declined += 1
            continue
        claim = _edition_claim(repo, g.film_id)
        if g.verdict == "twin" and g.twin_id is not None:
            report = repo.merge_film(g.film_id, g.twin_id, today, note=f"repair editions {g.title!r}")
            log(f"  merged #{g.film_id} → #{g.twin_id}: moved {report.moved} dropped {report.dropped}")
            if claim is not None and g.edition_year is not None:
                repo.set_claim_edition_year(claim.id, g.edition_year)
            ids = repo.external_ids_for(g.twin_id)
            if "imdb" not in ids:
                repo.set_external_id(g.twin_id, "imdb", g.tt, today)
            if g.twin_title and parse_title(g.twin_title).editions and not _key_as_work(repo, g.twin_id, g, today, log):
                # audit_editions pre-checks every holder, so this is unreachable barring a
                # concurrent writer — and the merge is already committed. Stop the batch loudly
                # rather than let a summary read "applied 0" over a half-done fold.
                partial = f"[partial] #{g.film_id} PARTIAL: merged into #{g.twin_id} but survivor keying refused"
                log(partial)
                raise RuntimeError(partial)
        else:
            if not _key_as_work(repo, g.film_id, g, today, log):
                continue
            if claim is not None and g.edition_year is not None:
                repo.set_claim_edition_year(claim.id, g.edition_year)
            log(f"  keyed #{g.film_id} as {g.work_title!r} ({g.work_year}) {g.tt}/{g.tmdb_id or '-'}")
        applied += 1
    counts = {v: sum(1 for g in groups if g.verdict == v) for v in ("twin", "no-twin", "conflict", "csv-mismatch")}
    return EditionsReport(
        len(groups), counts["twin"], counts["no-twin"], counts["conflict"], counts["csv-mismatch"], applied, declined
    )


@dataclass(frozen=True)
class DisagreementContract:
    film_id: int
    status: str
    expected_tt: str
    expected_tmdb: str | None
    title_ingested: str
    year_ingested: int | None
    source: str
    director: str | None


def load_disagreement_contract(csv_path: Path) -> dict[int, DisagreementContract]:
    """Every group-D row keyed by film id — `verified` rows are the contract, `proposed`
    rows are rendered as reviews and never applied."""
    out: dict[int, DisagreementContract] = {}
    if not csv_path.exists():
        return out
    with csv_path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["group"] != "D-disagree" or not r["film_id"].isdigit():
                continue
            fid = int(r["film_id"])
            out[fid] = DisagreementContract(
                fid,
                r["status"],
                r["expected_tt"],
                r.get("expected_tmdb") or None,
                r["title_ingested"],
                int(r["year_ingested"]) if r["year_ingested"] else None,
                r["source"],
                r.get("director") or None,
            )
    return out


@dataclass(frozen=True)
class DisagreementGroup:
    film_id: int
    title: str
    year: int | None
    omdb_tt: str
    tmdb_tt: str
    tmdb_id: str | None
    verdict: str  # "refetch" | "relink" | "adopt" | "review" | "conflict"
    expected_tt: str
    expected_tmdb: str | None
    detail: str
    contract: DisagreementContract | None


@dataclass(frozen=True)
class DisagreementsReport:
    groups: int
    refetch: int
    relink: int
    adopt: int
    review: int
    conflict: int
    applied: int
    declined: int


def audit_disagreements(repo: Repository, contract: dict[int, DisagreementContract]) -> list[DisagreementGroup]:
    """Live disagreements ∩ group D → one verdict each. Holders are read once, before any write,
    over EVERY film (disposed included — the UNIQUE guard is blind to dispositions too)."""
    tt_holders = repo.external_id_holders("imdb")
    tmdb_holders = repo.external_id_holders("tmdb")
    groups: list[DisagreementGroup] = []
    for f in repo.key_disagreements():
        c = contract.get(f.id)

        def mk(
            verdict: str, detail: str, f: DisagreementFilm = f, c: DisagreementContract | None = c
        ) -> DisagreementGroup:
            return DisagreementGroup(
                f.id, f.title, f.year, f.omdb_tt, f.tmdb_tt, f.tmdb_id, verdict,
                c.expected_tt if c else "", c.expected_tmdb if c else None, detail, c,
            )

        if c is None:
            groups.append(mk("conflict", "no D-disagree row"))
            continue
        if c.status != "verified":
            groups.append(mk("review", f"{c.status} {c.expected_tt or '?'} — A/B/C review"))
            continue
        if c.expected_tt == "NONE":
            groups.append(mk("review", "verified NONE — human decides"))
            continue
        if not c.expected_tt:
            # A verified row with a blank tt decides nothing; without this guard an
            # expected_tmdb would carry it into `adopt` and write "" as an IMDb id.
            groups.append(mk("conflict", "no expected_tt"))
            continue
        holder = tt_holders.get(c.expected_tt)
        if holder is not None and holder != f.id:
            groups.append(mk("conflict", f"{c.expected_tt} held by #{holder}"))
            continue
        th = tmdb_holders.get(c.expected_tmdb) if c.expected_tmdb else None
        if th is not None and th != f.id:
            groups.append(mk("conflict", f"tmdb {c.expected_tmdb} held by #{th}"))
            continue
        if c.expected_tt == f.tmdb_tt:
            groups.append(mk("refetch", "OMDb stub is the wrong work — refetch by id"))
        elif c.expected_tt == f.omdb_tt:
            groups.append(mk("relink", "TMDB link is the wrong work — relink via find_by_imdb"))
        elif c.expected_tmdb:
            groups.append(mk("adopt", f"neither side — adopt {c.expected_tt}/{c.expected_tmdb}"))
        else:
            groups.append(mk("conflict", "adopt needs expected_tmdb"))
    return groups


def format_disagreement(g: DisagreementGroup) -> str:
    exp = f"{g.expected_tt or '?'}/{g.expected_tmdb or '-'}"
    return (
        f"[{g.verdict}] #{g.film_id} {g.title!r} ({g.year}) omdb {g.omdb_tt} / tmdb {g.tmdb_tt}"
        f"({g.tmdb_id or '-'}) → {exp}: {g.detail}"
    )


KEY_DISAGREEMENT = "key-disagreement"  # durable tmdb review reason


def _disagreement_review(g: DisagreementGroup, fetcher: CandidateFetcher | None) -> ReviewEntry:
    """The durable review row for a group the contract does not decide: the LIVE resolver's
    ranking is the evidence (the CSV's own `A=…|B=…` note is never copied), the CSV's proposed
    tt — if it has one — is the row's `value`."""
    c = g.contract
    assert c is not None
    q = make_query(
        c.title_ingested or g.title,
        c.year_ingested if c.year_ingested else g.year,
        c.source,
        director=c.director,
    )
    if fetcher is None:
        v = Verdict("review", None, "no candidates", ())
    else:
        try:
            v = resolve(q, fetcher.fetch(q))
        except (CacheMiss, requests.RequestException, AuthError) as exc:
            # No clients for a miss, or the network/token failed: the review row is still
            # worth writing — a human reads it — so degrade to an evidence-free verdict.
            v = Verdict("review", None, f"no candidates ({exc})", ())
    value: str | None
    if c.status != "verified":  # noqa: SIM108 - spelled out: the ternary form hides an `or` precedence trap
        value = c.expected_tt or None  # proposed: the CSV's tt, or nothing to propose
    else:
        value = "NONE"  # verified NONE — the human's own "no such work" decision
    return ReviewEntry(KEY_DISAGREEMENT, film_id=g.film_id, value=value, detail=review_detail(v, q))


def repair_disagreements(
    repo: Repository,
    today: date,
    *,
    apply: bool,
    confirm: Callable[[DisagreementGroup], bool],
    contract: dict[int, DisagreementContract],
    tmdb: TmdbClient | None,
    fetcher: CandidateFetcher | None,
    limit: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> DisagreementsReport:
    """Dry run lists every group; --apply acts per verdict (spec §3). A `refetch` film stays in
    the worklist until the next sync refetches its OMDb record by the id written here — the
    disagreement count drops after `sync`, not after `--apply`. `review` rows are queued on
    --apply only and are durable + idempotent (`queue_review_once`)."""
    groups = audit_disagreements(repo, contract)
    if limit is not None:
        groups = groups[:limit]
    applied = declined = 0
    for g in groups:
        log(format_disagreement(g))
        if not apply or g.verdict == "conflict":
            continue
        if not confirm(g):
            declined += 1
            continue
        if g.verdict == "review":
            if queue_review_once(repo, TMDB_AUTHORITY, _disagreement_review(g, fetcher), today):
                log(f"  queued {KEY_DISAGREEMENT} review for #{g.film_id}")
                applied += 1
            else:
                log("  review already open")
            continue
        if g.verdict in ("relink", "adopt") and tmdb is None:
            log("  no TMDB client — skipped (needs the TMDB token)")
            continue
        # Every remote call and every holder check happens BEFORE the first write: a film is
        # either fully repaired or completely untouched (the half-state below is the only
        # exception, and it raises).
        tid: int | None
        winner_year: int | None = None
        try:
            if g.verdict == "refetch":
                tid = None
            elif g.verdict == "relink":
                assert tmdb is not None
                tid = tmdb.find_by_imdb(g.expected_tt)
            else:
                tid = int(str(g.expected_tmdb))
            if tid is not None:
                assert tmdb is not None
                # `adopt`'s id was holder-checked by the audit, but `relink`'s comes from
                # find_by_imdb just now — an id another film holds would make record_tmdb_match
                # return id-conflict AFTER the imdb write, leaving the wrong TMDB link on a film
                # that no longer looks like a disagreement. Check first, write nothing.
                holder = repo.film_id_for_external(TMDB_AUTHORITY, str(tid))
                if holder is not None and holder != g.film_id:
                    log(f"  tmdb {tid} held by #{holder} — skipped (conflict)")
                    continue
                winner_year = tmdb.movie_year(tid)
        except (requests.RequestException, AuthError) as exc:
            log(f"  TMDB error: {exc} — skipped")
            continue
        try:
            repo.set_external_id(g.film_id, "imdb", g.expected_tt, today)
        except sqlite3.IntegrityError:
            # Another film in this very batch just claimed it — the audit's holder map predates
            # the batch's own writes.
            log(f"  {g.expected_tt} already held — skipped (conflict)")
            continue
        if g.verdict == "relink" and tid is None:
            repo.clear_tmdb_link(g.film_id, today)
            log(f"  unlinked tmdb (no TMDB record for {g.expected_tt}); imdb {g.expected_tt} keyed")
        elif tid is not None:
            target = repo.tmdb_target(g.film_id)
            if target is None:
                raise RuntimeError(f"[partial] #{g.film_id} vanished after its imdb id was written")
            res = record_tmdb_match(repo, target, tid, winner_year, today, log)
            if res not in ("matched", "adopted"):
                partial = f"[partial] #{g.film_id} PARTIAL: imdb {g.expected_tt} written but tmdb {tid} {res}"
                log(partial)
                raise RuntimeError(partial)
            log(f"  relinked tmdb {tid} ({res})")
        if repo.omdb_imdb_id(g.film_id) != g.expected_tt:
            repo.mark_omdb_refresh(g.film_id)
            log(f"  omdb refresh queued (by id {g.expected_tt})")
        applied += 1
    counts = {
        v: sum(1 for g in groups if g.verdict == v) for v in ("refetch", "relink", "adopt", "review", "conflict")
    }
    return DisagreementsReport(
        len(groups), counts["refetch"], counts["relink"], counts["adopt"], counts["review"], counts["conflict"],
        applied, declined,
    )
