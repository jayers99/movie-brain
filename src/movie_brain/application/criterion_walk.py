"""The nightly Criterion walk after the 2026-10 relaunch (spec 2026-10-01 D2, D4–D7, D10).

Identity is the mediaid: a catalog item whose mediaid a film holds IS that film, whatever title
or year Criterion prints for it now — our title and year stay, Criterion's go in the claim (D4).
Only a mediaid NO film holds is asked about: its JW Player record, the thumbprint resolver, then
the gate ladder `films add` runs (D5). Every network call happens before anything is written;
the write is ONE transaction (`Repository.record_criterion_walk`, D6), so a failure anywhere
leaves Criterion exactly as it was. The films it created are keyed afterwards, and a keying
failure never undoes a creation — the next sync's keying step retries.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import requests

from movie_brain.application.films import CORPUS_VETO, KEY_COLLISION, gate_ladder
from movie_brain.application.lists import _catalog, _key_new_film, corpus_veto
from movie_brain.application.thumbprint import review_detail
from movie_brain.domain.matching import Candidate as CorpusCandidate
from movie_brain.domain.matching import CandidateIndex, build_candidate_index
from movie_brain.domain.models import CriterionWalk, NewFilm, ReviewEntry, WalkListing
from movie_brain.domain.thumbprint import Query, Verdict, make_query, resolve
from movie_brain.infrastructure.criterion_site import CatalogItem, CriterionError, JwMedia, Leaving
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.omdb import QuotaExceeded
from movie_brain.infrastructure.thumbprint_fetch import CacheMiss, CandidateFetcher
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

AUTHORITY = "criterion"
NO_MATCH = "no-match"
NO_RECORD = "no-record"
# The resolver's and TMDB's weather: never a verdict, so never a review row (D5).
WEATHER = (CacheMiss, requests.RequestException, AuthError, QuotaExceeded)


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


class CriterionSite(Protocol):
    def catalog(self) -> list[CatalogItem]: ...

    def media(self, mediaid: str) -> JwMedia | None: ...

    def leaving(self) -> Leaving: ...


@dataclass(frozen=True)
class WalkReport:
    arrived: int = 0
    departed: int = 0
    reviews: int = 0
    created: int = 0
    skipped: int = 0  # unknown items not asked about tonight: no resolver, or its lookups failed
    waiting: int = 0  # unknown items a review row already covers (open, or a standing decision)


def criterion_detail(
    item: CatalogItem,
    media: JwMedia | None,
    *,
    reason: str,
    verdict: Verdict | None = None,
    query: Query | None = None,
    tt: str | None = None,
    refused: str | None = None,
) -> str:
    """D5: the resolver's own review envelope (`review_detail` — reason, A/B/C, query) EXTENDED
    with what Criterion showed. It is what the owner reads to choose `--film X`, and what
    `review resolve --create` mints from (never a refetch: a `no-record` id would 404 again)."""
    body: dict[str, Any] = (
        json.loads(review_detail(verdict, query)) if verdict is not None else {"reason": reason, "candidates": []}
    )
    crit: dict[str, Any] = {
        "mediaid": item.mediaid, "title": item.title, "year": item.year, "duration_s": item.duration_s,
    }
    if media is not None:
        crit.update(
            director=list(media.directors), title_original=media.title_original, criterion_id=media.criterion_id
        )
    if tt is not None:
        crit["tt"] = tt
    if refused is not None:
        crit["refused"] = refused
    body["criterion"] = crit
    return json.dumps(body, ensure_ascii=False)


def parse_criterion_detail(detail: str | None) -> dict[str, Any] | None:
    """The `criterion` block of a row's detail, or None. `review resolve` appends ` [note]`
    after the JSON, so the body is read up to its last brace (as `parse_review_detail` does)."""
    if not detail or not detail.lstrip().startswith("{"):
        return None
    try:
        obj = json.loads(detail[: detail.rfind("}") + 1])
    except ValueError:
        return None
    crit = obj.get("criterion") if isinstance(obj, dict) else None
    return crit if isinstance(crit, dict) else None


def _director(media: JwMedia) -> str | None:
    return ", ".join(media.directors) or None


def _forms(item: CatalogItem, media: JwMedia) -> list[str]:
    """Criterion's own names for the work, which widen gate 3 (ledger L3)."""
    return list(dict.fromkeys(t for t in (item.title, media.title_original or "") if t))


def _review(reason: str, item: CatalogItem, media: JwMedia | None, **kw: Any) -> ReviewEntry:
    return ReviewEntry(reason, None, item.mediaid, criterion_detail(item, media, reason=reason, **kw))


def _leaving(site: CriterionSite, log: Callable[[str], None]) -> dict[str, str] | None:
    try:
        leaving = site.leaving()
    except Exception as exc:  # noqa: BLE001 — D7: a leaving failure keeps last-known labels, never aborts
        log(f"criterion: leaving pages unreadable, keeping last-known labels: {exc}")
        return None
    for line in leaving.mismatches:
        log(f"criterion: leaving date cross-check: {line}")
    return dict(leaving.labels)


def walk_criterion(
    repo: Repository,
    site: CriterionSite,
    fetcher: CandidateFetcher | None,
    tmdb: TmdbClient | None,
    today: date,
    *,
    log: Callable[[str], None] = _stderr,
) -> WalkReport:
    """One walk: stage everything (network only), write it in one transaction, key what it made.

    Raises on any failure before or inside the write; the caller (sync) catches it and carries
    on with the rest of the night. Per catalog item, in catalog order:
    1. a mediaid some film holds → that film (whatever review rows mention the mediaid);
    2. a mediaid any criterion review row names (open or resolved) → left to the human, no JW call;
    3. no resolver tonight (no TMDB token or no OMDb key) → skipped, asked again next walk;
    4. JW's record: 404 → a `no-record` review row; a failure → the walk fails (D6);
    5. the resolver: weather → skipped; no match → a `no-match` row carrying the A/B/C envelope;
    6. a match on a tt this walk is already creating → joins that staged film (The Beast 2023);
    7. the gate ladder: a holder → joins it; a refusal → a review row named by the gate;
       weather → skipped; clear → staged for creation unless it resembles (gate 3 over this
       walk's own staged titles) or keys like a film this walk is already creating → review.

    Any exception other than resolver/TMDB weather (a bug, an unexpected answer) fails the whole
    walk with nothing written — deliberately conservative; the night's other steps still run.
    """
    holders = repo.criterion_mediaid_holders()
    if not holders and repo.current_films(AUTHORITY):
        raise CriterionError(
            "films are listed on Criterion but none holds a Criterion id yet — "
            "run `movie-brain criterion bridge --apply` before the first walk"
        )
    items = site.catalog()
    covered = repo.criterion_review_values()
    film_rows = repo.films_for_matching()
    index = build_candidate_index(film_rows)
    catalog = _catalog(repo, film_rows)

    listings: list[WalkListing] = []
    created: list[NewFilm] = []
    reviews: list[ReviewEntry] = []
    reserved: dict[str, int] = {}  # tt → index into `created`
    staged_keys: set[str] = set()
    staged = CandidateIndex()  # gate 3 over the films this walk is about to create
    skipped = waiting = 0
    for item in items:
        holder = holders.get(item.mediaid)
        if holder is not None:
            listings.append(WalkListing(item.mediaid, item.title, item.year, film_id=holder))
            continue
        if item.mediaid in covered:
            waiting += 1
            continue
        if fetcher is None or tmdb is None:
            skipped += 1
            continue
        media = site.media(item.mediaid)
        if media is None:
            reviews.append(_review(NO_RECORD, item, None))
            continue
        q = make_query(
            item.title, item.year, "criterion", director=_director(media), runtime_min=item.duration_s // 60 or None
        )
        try:
            verdict = resolve(q, fetcher.fetch(q))
        except WEATHER as exc:
            log(f"criterion: resolver lookup failed for {item.title!r} ({item.mediaid}), asked again next walk: {exc}")
            skipped += 1
            continue
        if verdict.kind != "match" or verdict.tt is None:
            reviews.append(_review(NO_MATCH, item, media, verdict=verdict, query=q))
            continue
        if verdict.tt in reserved:
            listings.append(WalkListing(item.mediaid, item.title, item.year, new=reserved[verdict.tt], bind=True))
            continue
        forms = _forms(item, media)
        lad = gate_ladder(repo, tmdb, verdict, index=index, catalog=catalog, extra_forms=forms, log=log)
        if lad.kind == "weather":
            log(f"criterion: {lad.detail} for {item.title!r} ({item.mediaid}), asked again next walk")
            skipped += 1
            continue
        if lad.kind == "held":
            listings.append(WalkListing(item.mediaid, item.title, item.year, film_id=lad.holder, bind=True))
            continue
        if lad.kind == "blocked":
            reviews.append(
                _review(lad.reason, item, media, verdict=verdict, query=q, tt=verdict.tt, refused=lad.detail)
            )
            continue
        new = NewFilm(lad.title, lad.year, _director(media), verdict.tt, lad.tmdb_id)
        clash = corpus_veto(staged, [lad.title, *forms])
        if clash or new.key in staged_keys:
            refused = f"this walk is already creating a film like {lad.title!r} ({lad.year or '-'})"
            reason = CORPUS_VETO if clash else KEY_COLLISION
            reviews.append(_review(reason, item, media, verdict=verdict, query=q, tt=verdict.tt, refused=refused))
            continue
        reserved[verdict.tt] = len(created)
        staged_keys.add(new.key)
        for title in dict.fromkeys((lad.title, *forms)):
            staged.add(CorpusCandidate(id=-(len(created) + 1), title=title, year=lad.year))
        listings.append(WalkListing(item.mediaid, item.title, item.year, new=len(created), bind=True))
        created.append(new)

    leaving = _leaving(site, log)
    wrote = repo.record_criterion_walk(
        CriterionWalk(tuple(listings), tuple(created), tuple(reviews), leaving), today
    )
    for film_id, new in wrote.created:
        _key_new_film(repo, tmdb, film_id, new.tt, new.tmdb_id, today, log)
    return WalkReport(wrote.arrived, wrote.departed, len(reviews), len(created), skipped, waiting)
