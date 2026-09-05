"""Resolve each film's CheapCharts product page once, and store the iTunes id it needs.

The drawer used to offer a CheapCharts title *search*, which lands the owner on a list they
then have to read. The direct page is keyed by iTunes track id, which the catalogue does not
hold — so the id is resolved here, stored under the `itunes` authority, and the read model
builds the link from what is stored. Nothing calls CheapCharts at render time.

Two paths, in order. `products_by_imdb` is the accurate one: CheapCharts is asked by IMDb id
and answers with the product page, no title comparison anywhere (37 of 40 sampled canon films
come back). Its index has holes — Amour has a product page and no IMDb mapping — so a title
search is the fallback, and a search answer is believed only when the shared matcher confirms
it. The confirmation runs through `match_owned` because a CheapCharts result IS an Apple store
title: same titling conventions, same remaster-prone year, so the COMMERCE band's
trailing-drift-is-neutral treatment is exactly the policy it needs. No matching logic lives
here (matching contract).

`itunes` is deliberately NOT a key authority. It names a storefront product, not the work —
the same film reissued gets a new track id — so it is a claim, and the identity machinery
(`key_work`'s refusal checks, the thumbprint resolver) stays blind to it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import requests

from movie_brain.domain.matching import Candidate, CandidateIndex, match_owned
from movie_brain.domain.models import ItunesTarget
from movie_brain.infrastructure.cheapcharts import (
    MAX_IMDB_IDS,
    CheapChartsClient,
    Product,
    RateLimited,
)
from movie_brain.infrastructure.database import Repository

ITUNES_AUTHORITY = "itunes"


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class ResolveReport:
    scanned: int = 0
    resolved: int = 0
    by_imdb: int = 0
    by_search: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    held: int = 0
    failed: int = 0
    rate_limited: bool = False  # the run stopped early; the next one resumes where it left off


def _batches(targets: Sequence[ItunesTarget], size: int) -> list[Sequence[ItunesTarget]]:
    return [targets[i : i + size] for i in range(0, len(targets), size)]


def _confirm(target: ItunesTarget, products: list[Product]) -> tuple[Product | None, str]:
    """The search fallback's gate: the film this entry names, or a refusal with a reason.

    Every product is put to the shared matcher as an Apple store title against an index
    holding this one film. A product that does not name this film simply loses; two products
    naming it under different track ids are ambiguous and are refused, because picking the
    first would be guessing which edition the owner meant.
    """
    index = CandidateIndex(
        [Candidate(id=target.film_id, title=target.title, year=target.year, director=target.director)]
    )
    winners = [
        p for p in products if match_owned(p.title, p.year, index, director=p.director).winner == target.film_id
    ]
    ids = {p.itunes_id for p in winners}
    if not ids:
        return None, "unmatched"
    if len(ids) > 1:
        return None, "ambiguous"
    return winners[0], "match"


def resolve_itunes_ids(
    repo: Repository,
    client: CheapChartsClient,
    today: date,
    *,
    apply: bool = False,
    limit: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> ResolveReport:
    targets = repo.films_needing_itunes_id(limit)
    scanned = resolved = by_imdb = by_search = unmatched = ambiguous = held = failed = 0
    for batch in _batches(targets, MAX_IMDB_IDS):
        try:
            found = client.products_by_imdb([t.imdb_id for t in batch])
        except RateLimited:
            log("CheapCharts is rate-limiting — stopping; the next run resumes where this one stopped.")
            return ResolveReport(
                scanned, resolved, by_imdb, by_search, unmatched, ambiguous, held, failed, rate_limited=True
            )
        except requests.RequestException as exc:
            log(f"  CheapCharts price lookup failed for {len(batch)} films: {exc}")
            failed += len(batch)
            scanned += len(batch)
            continue
        for target in batch:
            scanned += 1
            product = found.get(target.imdb_id)
            source = "imdb"
            if product is None:
                try:
                    results = client.search(target.title)
                except RateLimited:
                    log("CheapCharts is rate-limiting — stopping; the next run resumes where this one stopped.")
                    return ResolveReport(
                        scanned, resolved, by_imdb, by_search, unmatched, ambiguous, held, failed, rate_limited=True
                    )
                except requests.RequestException as exc:
                    log(f"  #{target.film_id} {target.title!r}: CheapCharts search failed: {exc}")
                    failed += 1
                    continue
                product, verdict = _confirm(target, results)
                if product is None:
                    log(f"  #{target.film_id} {target.title!r} ({target.year}): {verdict}")
                    unmatched += verdict == "unmatched"
                    ambiguous += verdict == "ambiguous"
                    continue
                source = "search"
            holder = repo.film_id_for_external(ITUNES_AUTHORITY, product.itunes_id)
            if holder is not None and holder != target.film_id:
                log(f"  #{target.film_id} {target.title!r}: itunes {product.itunes_id} already held by #{holder}")
                held += 1
                continue
            log(f"  #{target.film_id} {target.title!r} ({target.year}) → itunes {product.itunes_id} (by {source})")
            if apply:
                repo.set_external_id(target.film_id, ITUNES_AUTHORITY, product.itunes_id, today)
            resolved += 1
            by_imdb += source == "imdb"
            by_search += source == "search"
    return ResolveReport(scanned, resolved, by_imdb, by_search, unmatched, ambiguous, held, failed)
