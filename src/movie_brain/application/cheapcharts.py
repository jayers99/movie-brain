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

import re
import sys
import unicodedata
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
    ProductFiling,
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
    dropped: int = 0  # removed ids taken off films that also hold a live product


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


_NAME_SPLIT = re.compile(r"\s*(?:,|&|\band\b)\s*")


def _name_key(name: str) -> frozenset[str] | None:
    """One person's name as a bag of accent-folded, case-folded words, so `François Truffaut`
    is `Francois Truffaut` and `Yeo Siew Hua` is `Siew Hua Yeo`. None for a name that says
    nothing comparable — Apple's literal `Unknown`, or a credit in another script (`박찬욱`)."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    words = frozenset(re.findall(r"[a-z]+", folded))
    return words if words and words != {"unknown"} else None


def _names(text: str) -> set[frozenset[str]]:
    keys = (_name_key(n) for n in _NAME_SPLIT.split(text))
    return {k for k in keys if k is not None}


def _refusal(target: ItunesTarget, filing: ProductFiling | None) -> str | None:
    """Why a title-search answer is NOT this film, or None when it is. A search result carries
    no director, and two films of one title and year are common (The Stranger 2022, twice; Hope
    2013 against an undated Hope) — so the product's own filing decides: the same IMDb id is
    proof, another one is a refusal, and with no IMDb filing only an agreeing director will do.
    Unverifiable is refused: a miss costs nothing, a wrong link is silent."""
    if filing is None:
        return "product unknown to CheapCharts"
    if filing.imdb_id is not None:
        return None if filing.imdb_id == target.imdb_id else f"filed under {filing.imdb_id}, not {target.imdb_id}"
    mine = _names(target.director or "")
    theirs = {k for k in (_name_key(d) for d in filing.directors) if k is not None}
    if not mine or not theirs:
        return "no imdb filing and no director to compare"
    return None if mine & theirs else f"directed by {', '.join(filing.directors)}"


def resolve_itunes_ids(
    repo: Repository,
    client: CheapChartsClient,
    today: date,
    *,
    apply: bool = False,
    limit: int | None = None,
    retry_misses: bool = False,
    log: Callable[[str], None] = _stderr,
) -> ResolveReport:
    targets = repo.films_needing_itunes_id(limit, retry_misses=retry_misses)
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
            held_id: str | None = None  # the IMDb answer's product, when another film holds it
            if product is not None:
                holder = repo.film_id_for_external(ITUNES_AUTHORITY, product.itunes_id)
                if holder is not None and holder != target.film_id:
                    # CheapCharts' IMDb index answers a film's id with its SIBLING's product often
                    # enough to matter (Final Reckoning's tt → Dead Reckoning's page, 2026-09-20),
                    # and the title search finds the right one — so a held answer is a miss by
                    # IMDb id, not the end of the lookup. Nothing is ever taken from the holder.
                    log(f"  #{target.film_id} {target.title!r}: itunes {product.itunes_id} already held by #{holder}")
                    held_id, product = product.itunes_id, None
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
                if product is not None:
                    try:
                        why = _refusal(target, client.filing(product.itunes_id))
                    except RateLimited:
                        log("CheapCharts is rate-limiting — stopping; the next run resumes where this one stopped.")
                        return ResolveReport(
                            scanned, resolved, by_imdb, by_search, unmatched, ambiguous, held, failed, rate_limited=True
                        )
                    except requests.RequestException as exc:
                        log(f"  #{target.film_id} {target.title!r}: CheapCharts product lookup failed: {exc}")
                        failed += 1
                        continue
                    if why is not None:
                        log(f"  #{target.film_id} {target.title!r}: search answer {product.itunes_id} refused — {why}")
                        product, verdict = None, "unmatched"
                if product is None:
                    log(f"  #{target.film_id} {target.title!r} ({target.year}): {verdict}")
                    # A held IMDb answer the search could not better stays `held`: that is the
                    # fact a human needs, and it outranks the search's own shrug.
                    held += held_id is not None
                    unmatched += held_id is None and verdict == "unmatched"
                    ambiguous += held_id is None and verdict == "ambiguous"
                    # An ANSWER with nothing in it is remembered; a failed call (above) is not.
                    if apply:
                        repo.mark_store_asked(target.film_id, today)
                    continue
                source = "search"
            holder = repo.film_id_for_external(ITUNES_AUTHORITY, product.itunes_id)
            if holder is not None and holder != target.film_id:
                if product.itunes_id != held_id:  # the same product was already logged above
                    log(f"  #{target.film_id} {target.title!r}: itunes {product.itunes_id} already held by #{holder}")
                held += 1
                if apply:
                    repo.mark_store_asked(target.film_id, today)
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
    scanned = live = replaced = dead = unknown = held = failed = dropped = 0
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
            stored = [v for a, v in repo.external_ids_all(target.film_id) if a == ITUNES_AUTHORITY]
            if len(stored) > 1:
                # Several store ids (a merge, or `wishlist --resolve`): the by-IMDb answer speaks
                # for ONE product, so each is asked about by its own id. A removed one beside a
                # live one is dropped — otherwise MIN(value) can link the drawer to the dead
                # product (Dial M for Murder, The Petrified Forest, The General, 2026-09-20).
                try:
                    state = {v: client.is_removed(v) for v in stored}
                except RateLimited:
                    return _rate_limited(scanned, live, replaced, dead, unknown, held, failed, last_film_id, log)
                except requests.RequestException as exc:
                    log(f"  #{target.film_id} {target.title!r}: CheapCharts product lookup failed: {exc}")
                    failed += 1
                    continue
                alive = [v for v in stored if state[v] is False]
                gone = [v for v in stored if state[v] is True]
                if alive:
                    for value in gone:
                        log(
                            f"  #{target.film_id} {target.title!r}: itunes {value} (removed) dropped — "
                            f"the film also holds live {', '.join(alive)}"
                        )
                        if apply:
                            repo.drop_external_claim(target.film_id, ITUNES_AUTHORITY, value)
                        dropped += 1
                    live += 1
                    continue
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
            try:
                why = _refusal(target, client.filing(confirmed.itunes_id))
            except RateLimited:
                return _rate_limited(scanned, live, replaced, dead, unknown, held, failed, last_film_id, log)
            except requests.RequestException as exc:
                log(f"  #{target.film_id} {target.title!r}: CheapCharts product lookup failed: {exc}")
                failed += 1
                continue
            if why is not None:
                log(
                    f"  #{target.film_id} {target.title!r}: itunes {target.itunes_id} removed, "
                    f"re-listing {confirmed.itunes_id} refused — {why}"
                )
                dead += 1
                continue
            holder = repo.film_id_for_external(ITUNES_AUTHORITY, confirmed.itunes_id)
            if holder == target.film_id:
                # This film already holds the confirmed re-listing under a second `itunes` row (a
                # merge, or `wishlist --resolve`, leaves a film with more than one). The removed id
                # is then a replacement that has already happened: drop it, or MIN(value) keeps
                # linking the drawer to a product Apple has pulled (Dial M for Murder, 2026-09-20).
                log(
                    f"  #{target.film_id} {target.title!r}: itunes {target.itunes_id} (removed) dropped — "
                    f"the film already holds its re-listing {confirmed.itunes_id}"
                )
                if apply:
                    repo.drop_external_claim(target.film_id, ITUNES_AUTHORITY, target.itunes_id)
                replaced += 1
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
    return RecheckReport(
        scanned, live, replaced, dead, unknown, held, failed, last_film_id=last_film_id, dropped=dropped
    )


@dataclass(frozen=True)
class AuditReport:
    """`cheapcharts audit`: every STORED id put to the check a new search answer has to pass.
    Read-only. `suspects` are for a human: CheapCharts' own filing can be the thing that is wrong
    (it answers Final Reckoning's IMDb id with Dead Reckoning's page), so nothing is ever removed
    on its say-so."""

    scanned: int = 0
    agree: int = 0
    suspects: int = 0
    unverified: int = 0
    unknown: int = 0
    removed: int = 0
    failed: int = 0
    rate_limited: bool = False
    last_film_id: int | None = None
    misfiled: int = 0  # another IMDb id but the film's own director: most likely CheapCharts' slip


def audit_itunes_ids(
    repo: Repository,
    client: CheapChartsClient,
    *,
    limit: int | None = None,
    after: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> AuditReport:
    """Ask CheapCharts what each stored product is filed under and name the ones that are not
    this film (`_refusal`, the rule a search answer passes since 2026-09-20 — ids stored before
    it never met it, and September's Grandma's Boy mix-up was exactly this). One paced call per
    stored id; writes nothing; `after` resumes a rate-limited run."""
    scanned = agree = suspects = unverified = unknown = removed = failed = misfiled = 0
    last_film_id: int | None = None  # the last film whose EVERY id was asked — safe to resume after
    current: int | None = None
    for target in repo.stored_itunes_ids(limit, after):
        assert target.itunes_id is not None
        if target.film_id != current:
            last_film_id, current = current, target.film_id
        try:
            filing = client.filing(target.itunes_id)
        except RateLimited:
            hint = f" — resume with --after {last_film_id}" if last_film_id is not None else ""
            log(f"CheapCharts is rate-limiting — stopping{hint}.")
            return AuditReport(
                scanned, agree, suspects, unverified, unknown, removed, failed, rate_limited=True,
                last_film_id=last_film_id, misfiled=misfiled,
            )
        except requests.RequestException as exc:
            log(f"  #{target.film_id} {target.title!r}: CheapCharts product lookup failed: {exc}")
            failed += 1
            scanned += 1
            continue
        scanned += 1
        who = f"#{target.film_id} {target.title!r} ({target.year or '-'}) [{target.director or '-'}]"
        if filing is None:
            log(f"  {who}: itunes {target.itunes_id} — CheapCharts does not know this product")
            unknown += 1
        else:
            removed += filing.removed
            why = _refusal(target, filing)
            if why is None:
                agree += 1
            elif filing.imdb_id is None and "no director" in why:
                unverified += 1
            else:
                by = ", ".join(filing.directors) or "-"
                gone = " (removed)" if filing.removed else ""
                # Another IMDb id, yet credited to this film's own director: far more often
                # CheapCharts' filing slip (it files Dead Reckoning under Final Reckoning's id) than
                # a wrong product. Still printed, under a quieter label.
                same_director = bool(
                    _names(target.director or "") & {k for k in map(_name_key, filing.directors) if k is not None}
                )
                label = "misfiled?" if filing.imdb_id is not None and same_director else "SUSPECT"
                log(f"  {label} {who}: itunes {target.itunes_id}{gone} is {filing.title!r} by {by} — {why}")
                misfiled += label == "misfiled?"
                suspects += label == "SUSPECT"
    return AuditReport(
        scanned, agree, suspects, unverified, unknown, removed, failed, last_film_id=current, misfiled=misfiled
    )

