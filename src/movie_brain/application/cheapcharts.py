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


@dataclass(frozen=True)
class RecheckReport:
    """`cheapcharts resolve --recheck`'s audit of every STORED id. `last_film_id` is the last
    target scanned — the resume hint printed alongside `rate_limited`, None when nothing was
    scanned at all."""

    scanned: int = 0
    live: int = 0
    replaced: int = 0
    dead: int = 0
    unknown: int = 0
    held: int = 0
    failed: int = 0
    rate_limited: bool = False
    last_film_id: int | None = None


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
            if product is not None and product.removed:
                # Apple has pulled this product — a miss by IMDb id exactly like a hole in
                # CheapCharts' own index, so the search fallback runs unchanged below.
                product = None
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


def _rate_limited(
    scanned: int, live: int, replaced: int, dead: int, unknown: int, held: int, failed: int,
    last_film_id: int | None, log: Callable[[str], None],
) -> RecheckReport:
    hint = f" — resume with --after {last_film_id}" if last_film_id is not None else ""
    log(f"CheapCharts is rate-limiting — stopping{hint}.")
    return RecheckReport(
        scanned, live, replaced, dead, unknown, held, failed, rate_limited=True, last_film_id=last_film_id
    )


def recheck_itunes_ids(
    repo: Repository,
    client: CheapChartsClient,
    today: date,
    *,
    apply: bool = False,
    limit: int | None = None,
    after: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> RecheckReport:
    """Audit every STORED iTunes id: CheapCharts is re-asked by IMDb id, and a product Apple
    has removed (`Product.removed`) is re-resolved through the same search fallback the
    backfill uses. A confirmed re-listing REPLACES the dead id in place, one UPDATE, and the
    old id is only ever printed here — never retired to a flag (owner ruling 2026-09-07)."""
    targets = repo.films_holding_itunes_id(limit, after)
    scanned = live = replaced = dead = unknown = held = failed = 0
    last_film_id: int | None = None
    for batch in _batches(targets, MAX_IMDB_IDS):
        try:
            found = client.products_by_imdb([t.imdb_id for t in batch])
        except RateLimited:
            return _rate_limited(scanned, live, replaced, dead, unknown, held, failed, last_film_id, log)
        except requests.RequestException as exc:
            log(f"  CheapCharts price lookup failed for {len(batch)} films: {exc}")
            failed += len(batch)
            scanned += len(batch)
            last_film_id = batch[-1].film_id
            continue
        for target in batch:
            scanned += 1
            last_film_id = target.film_id
            assert target.itunes_id is not None  # films_holding_itunes_id always fills this
            product = found.get(target.imdb_id)
            if product is None:
                log(f"  #{target.film_id} {target.title!r}: CheapCharts no longer knows this imdb id")
                unknown += 1
                continue
            if not product.removed:
                if product.itunes_id != target.itunes_id:
                    log(
                        f"  #{target.film_id} {target.title!r}: itunes {target.itunes_id} still live "
                        f"(CheapCharts now answers {product.itunes_id} — left alone)"
                    )
                live += 1
                continue
            try:
                results = client.search(target.title)
            except RateLimited:
                return _rate_limited(scanned, live, replaced, dead, unknown, held, failed, last_film_id, log)
            except requests.RequestException as exc:
                log(f"  #{target.film_id} {target.title!r}: CheapCharts search failed: {exc}")
                failed += 1
                continue
            confirmed, verdict = _confirm(target, results)
            if confirmed is None:
                log(
                    f"  #{target.film_id} {target.title!r} ({target.year}): "
                    f"itunes {target.itunes_id} removed, {verdict}"
                )
                dead += 1
                continue
            if confirmed.itunes_id == target.itunes_id:
                log(f"  #{target.film_id} {target.title!r}: itunes {target.itunes_id} removed, no re-listing found")
                dead += 1
                continue
            holder = repo.film_id_for_external(ITUNES_AUTHORITY, confirmed.itunes_id)
            if holder == target.film_id:
                # This film already holds the confirmed id under a second `itunes` row (a
                # merge can leave a survivor with more than one) — it is live, not a
                # replacement, and there's nothing to write.
                log(f"  #{target.film_id} {target.title!r}: itunes {confirmed.itunes_id} already held by this film")
                live += 1
                continue
            if holder is not None:
                log(f"  #{target.film_id} {target.title!r}: itunes {confirmed.itunes_id} already held by #{holder}")
                held += 1
                continue
            log(
                f"  #{target.film_id} {target.title!r} ({target.year}): itunes {target.itunes_id} (removed) "
                f"→ {confirmed.itunes_id}"
            )
            if apply:
                repo.replace_external_id(target.film_id, ITUNES_AUTHORITY, target.itunes_id, confirmed.itunes_id)
            replaced += 1
    return RecheckReport(scanned, live, replaced, dead, unknown, held, failed, last_film_id=last_film_id)
