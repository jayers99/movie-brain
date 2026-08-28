"""Key-repair verbs (thumbprint T3/T4): films whose identity keys disagree or are missing.

`repair disagreements` (T3) and `repair nomatch` (T4) share one shape: an audit pass that
computes a verdict per film with holder checks BEFORE any write, an --apply loop acting per
verdict, `--limit` slicing the ACTIONABLE verdicts only, and a report that counts every verdict.
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from movie_brain.application.availability import (
    NO_MATCH_REVIEWED,
    TMDB_AUTHORITY,
    queue_review_once,
    rebuild_no_match_queue,
    record_tmdb_match,
)
from movie_brain.application.thumbprint import film_query, review_detail
from movie_brain.domain.models import ReviewEntry
from movie_brain.domain.thumbprint import Query, Verdict, make_query, resolve
from movie_brain.infrastructure.database import DisagreementFilm, NomatchFilm, Repository
from movie_brain.infrastructure.thumbprint_fetch import CacheMiss, CandidateFetcher
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


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
    verdict: str  # "refetch" | "relink" | "adopt" | "review" | "conflict" | "pending" | "review-open"
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
    pending: int
    review_open: int
    applied: int
    declined: int


# Verdicts that are listed and never acted on: a `--limit` batch spends none of its budget here.
NON_ACTIONABLE = ("conflict", "pending", "review-open")


def audit_disagreements(repo: Repository, contract: dict[int, DisagreementContract]) -> list[DisagreementGroup]:
    """Live disagreements ∩ group D → one verdict each. Holders are read once, before any write,
    over EVERY film (disposed included — the UNIQUE guard is blind to dispositions too).

    A film whose repair already landed is NOT actionable again: `--apply` cannot clear the
    disagreement itself (the OMDb payload only changes on the next `sync`), so the already-done
    work is recognised up front — `pending` (keyed + OMDb refetch queued) and `review-open` (its
    durable `key-disagreement` review is open, or already RESOLVED — a standing decision the
    human has made) are checked before any actionable verdict."""
    tt_holders = repo.external_id_holders("imdb")
    tmdb_holders = repo.external_id_holders("tmdb")
    reviewed = {
        int(str(r["film_id"])) for r in repo.open_reviews(TMDB_AUTHORITY) if r["reason"] == KEY_DISAGREEMENT
    }
    # A RESOLVED row is a standing decision, not a closed ticket: the film keeps disagreeing
    # (its OMDb payload is untouched) but `queue_review_once` will never re-queue it, so it is
    # not work either — without this it would sit at the head of every `--limit` batch.
    decided = {
        fid
        for reason, fid, _ in repo.resolved_review_keys(TMDB_AUTHORITY)
        if reason == KEY_DISAGREEMENT and fid is not None
    } - reviewed
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
        if f.id in reviewed:
            groups.append(mk("review-open", f"{KEY_DISAGREEMENT} review already open"))
            continue
        if f.id in decided:
            groups.append(mk("review-open", f"{KEY_DISAGREEMENT} review resolved — standing decision"))
            continue
        if (
            c.status == "verified"
            and c.expected_tt not in ("", "NONE")
            and f.imdb_ext == c.expected_tt
            and repo.omdb_needs_refresh(f.id)
        ):
            groups.append(mk("pending", "keyed; OMDb refetch queued — resolves on the next sync"))
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
    disagreement count drops after `sync`, not after `--apply`; on the runs in between it is
    listed as `pending`. `review` rows are queued on --apply only and are durable + idempotent
    (`queue_review_once`); once open, the film is listed as `review-open`.

    `--limit N` is a batch size over the ACTIONABLE groups only: the non-actionable ones
    (`conflict`, `pending`, `review-open`) are cheap and informational, so they are always
    listed in full and spend none of the budget. Repeated batches therefore advance through the
    worklist instead of re-hitting its head."""
    audited = audit_disagreements(repo, contract)
    groups = [g for g in audited if g.verdict in NON_ACTIONABLE]
    actionable = [g for g in audited if g.verdict not in NON_ACTIONABLE]
    groups += actionable if limit is None else actionable[:limit]
    applied = declined = 0
    for g in groups:
        log(format_disagreement(g))
        if not apply or g.verdict in NON_ACTIONABLE:
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
        v: sum(1 for g in groups if g.verdict == v)
        for v in ("refetch", "relink", "adopt", "review", "conflict", "pending", "review-open")
    }
    return DisagreementsReport(
        len(groups), counts["refetch"], counts["relink"], counts["adopt"], counts["review"], counts["conflict"],
        counts["pending"], counts["review-open"], applied, declined,
    )


# --- repair nomatch (T4, memo step 4) ------------------------------------------------------

NOMATCH_ACTIONABLE = ("keyed", "match", "review")
NOMATCH_SUCCESS = ("matched", "adopted", "collision")  # record_tmdb_match results that are complete, not [partial]


@dataclass(frozen=True)
class NomatchGroup:
    review_id: int
    film_id: int
    title: str
    year: int | None
    verdict: str  # "keyed" | "unlinked" | "linked" | "match" | "review" | "review-open" | "conflict"
    reason: str
    tt: str | None
    tmdb_id: int | None
    query: Query | None
    verdict_obj: Verdict | None
    detail: str


def audit_nomatch(
    repo: Repository, fetcher: CandidateFetcher | None, tmdb: TmdbClient | None
) -> list[NomatchGroup]:
    """One verdict per open no-match film, every holder check done here, nothing written."""
    imdb_holders = repo.external_id_holders("imdb")
    tmdb_holders = repo.external_id_holders(TMDB_AUTHORITY)
    reviewed_open = {
        int(str(r["film_id"])) for r in repo.open_reviews(TMDB_AUTHORITY) if r["reason"] == NO_MATCH_REVIEWED
    }
    out: list[NomatchGroup] = []
    for f in repo.nomatch_worklist():

        def mk(
            verdict: str,
            reason: str,
            detail: str = "",
            tt: str | None = None,
            tid: int | None = None,
            q: Query | None = None,
            v: Verdict | None = None,
            f: NomatchFilm = f,
        ) -> NomatchGroup:
            return NomatchGroup(
                f.review_id, f.film_id, f.title, f.year, verdict, reason, tt, tid, q, v, detail
            )

        if f.film_id in reviewed_open:
            out.append(mk("review-open", "already promoted"))
            continue
        own_ids = repo.external_ids_for(f.film_id)
        own_tt = own_ids.get("imdb")
        if own_tt is not None and own_ids.get("tmdb") is not None and repo.tmdb_found(f.film_id):
            out.append(mk("linked", "already keyed and found", tt=own_tt, tid=int(own_ids["tmdb"])))
            continue
        if own_tt is not None:
            if tmdb is None:
                out.append(mk("conflict", "no client", "holds imdb but no TMDB client to look it up", tt=own_tt))
                continue
            try:
                tid = tmdb.find_by_imdb(own_tt)
            except (requests.RequestException, AuthError) as exc:
                out.append(mk("conflict", "TMDB error", str(exc), tt=own_tt))
                continue
            if tid is None:
                out.append(mk("unlinked", "no TMDB record", f"imdb {own_tt} has no TMDB movie", tt=own_tt))
            elif tmdb_holders.get(str(tid), f.film_id) != f.film_id:
                out.append(
                    mk("conflict", "tmdb held", f"tmdb {tid} held by #{tmdb_holders[str(tid)]}", tt=own_tt, tid=tid)
                )
            else:
                out.append(mk("keyed", "imdb already keyed", tt=own_tt, tid=tid))
            continue
        q = film_query(repo, f.film_id, f.title, f.year, f.director)
        if fetcher is None:
            out.append(mk("conflict", "no client", "no TMDB/OMDb clients", q=q))
            continue
        try:
            v = resolve(q, fetcher.fetch(q))
        except (CacheMiss, requests.RequestException, AuthError) as exc:
            out.append(mk("conflict", "TMDB error", str(exc), q=q))
            continue
        if v.kind != "match" or v.tt is None:
            out.append(mk("review", v.reason, review_detail(v, q), q=q, v=v))
            continue
        holder = imdb_holders.get(v.tt)
        if holder is not None and holder != f.film_id:
            out.append(mk("conflict", "imdb held", f"{v.tt} held by #{holder}", tt=v.tt, q=q, v=v))
            continue
        winner = next((s.candidate for s in v.ranked if s.candidate.tt == v.tt), None)
        tid = winner.tmdb_id if winner is not None else None
        if tid is None and tmdb is not None:
            try:
                tid = tmdb.find_by_imdb(v.tt)
            except (requests.RequestException, AuthError) as exc:
                out.append(mk("conflict", "TMDB error", str(exc), tt=v.tt, q=q, v=v))
                continue
        if tid is not None and tmdb_holders.get(str(tid), f.film_id) != f.film_id:
            out.append(
                mk(
                    "conflict", "tmdb held", f"tmdb {tid} held by #{tmdb_holders[str(tid)]}",
                    tt=v.tt, tid=tid, q=q, v=v,
                )
            )
            continue
        out.append(mk("match", v.reason, tt=v.tt, tid=tid, q=q, v=v))
    return out


def format_nomatch(g: NomatchGroup) -> str:
    src = f" src={g.query.source} dir={g.query.director or '-'}" if g.query else ""
    head = (
        f"[{g.verdict}] #{g.film_id} {g.title!r} ({g.year or '-'}){src} → "
        f"{g.tt or '-'} ({g.tmdb_id or '-'}): {g.reason}"
    )
    if g.verdict == "review" and g.verdict_obj is not None:
        cands = " / ".join(
            f"{letter} {s.candidate.tt} {s.candidate.titles[0] if s.candidate.titles else ''!r} "
            f"{s.candidate.year or '-'} {s.candidate.directors or '-'}"
            for letter, s in zip("ABC", g.verdict_obj.ranked, strict=False)
        )
        return f"{head} [{cands}]"
    return f"{head} {g.detail}".rstrip()


@dataclass(frozen=True)
class NomatchReport:
    groups: int
    keyed: int
    unlinked: int
    linked: int  # non-actionable, like unlinked: already holds imdb+tmdb with tmdb.found=1
    match: int
    review: int
    review_open: int
    conflict: int
    applied: int
    declined: int
    skipped: int  # actionable groups NOT written on --apply for a runtime reason (held id, TMDB error)


def repair_nomatch(
    repo: Repository,
    today: date,
    *,
    apply: bool,
    confirm: Callable[[NomatchGroup], bool],
    tmdb: TmdbClient | None,
    fetcher: CandidateFetcher | None,
    limit: int | None = None,
    log: Callable[[str], None] = _stderr,
) -> NomatchReport:
    """Rerun the open no-match films through the resolver (spec §4). `match`/`keyed` key the
    film through the sync's own write path; `review` promotes the existing row in place to the
    durable `no-match-reviewed` reason; nothing else is written. `--limit N` slices the
    ACTIONABLE verdicts only. On --apply the run ends with the sync's own no-match rebuild, so
    matched films' rows drop now rather than at the next sync — and NO no-match row is ever
    resolved by this verb (a resolved no-match row would block a later manual relink)."""
    audited = audit_nomatch(repo, fetcher, tmdb)
    groups = [g for g in audited if g.verdict not in NOMATCH_ACTIONABLE]
    actionable = [g for g in audited if g.verdict in NOMATCH_ACTIONABLE]
    groups += actionable if limit is None else actionable[:limit]
    applied = declined = skipped = 0
    for g in groups:
        log(format_nomatch(g))
        if not apply or g.verdict not in NOMATCH_ACTIONABLE:
            continue
        if not confirm(g):
            declined += 1
            continue
        if g.verdict == "review":
            repo.promote_review(g.review_id, reason=NO_MATCH_REVIEWED, detail=g.detail, value=None)
            log(f"  promoted review {g.review_id} → {NO_MATCH_REVIEWED}")
            applied += 1
            continue
        assert g.tt is not None
        if tmdb is None:
            log("  no TMDB client — skipped")
            skipped += 1
            continue
        # Live pre-write checks: the audit's holder maps predate this batch's own writes.
        holder = repo.film_id_for_external("imdb", g.tt)
        if holder is not None and holder != g.film_id:
            log(f"  {g.tt} already held by #{holder} — skipped")
            skipped += 1
            continue
        tid = g.tmdb_id
        winner_year: int | None = None
        try:
            if tid is not None:
                th = repo.film_id_for_external(TMDB_AUTHORITY, str(tid))
                if th is not None and th != g.film_id:
                    log(f"  tmdb {tid} already held by #{th} — skipped")
                    skipped += 1
                    continue
                winner_year = tmdb.movie_year(tid)
        except (requests.RequestException, AuthError) as exc:
            log(f"  TMDB error: {exc} — skipped")
            skipped += 1
            continue
        try:
            repo.set_external_id(g.film_id, "imdb", g.tt, today)
        except sqlite3.IntegrityError:
            log(f"  {g.tt} already held — skipped")
            skipped += 1
            continue
        if tid is not None:
            target = repo.tmdb_target(g.film_id)
            if target is None:
                raise RuntimeError(f"[partial] #{g.film_id} vanished after its imdb id was written")
            res = record_tmdb_match(repo, target, tid, winner_year, today, log)
            if res not in NOMATCH_SUCCESS:
                partial = f"[partial] #{g.film_id} PARTIAL: imdb {g.tt} written but tmdb {tid} {res}"
                log(partial)
                raise RuntimeError(partial)
            if res == "collision":
                log(f"  keyed imdb {g.tt} tmdb {tid} (collision → year-collision review queued)")
            else:
                log(f"  keyed imdb {g.tt} tmdb {tid} ({res})")
        else:
            log(f"  keyed imdb {g.tt} (no TMDB record)")
        if repo.omdb_imdb_id(g.film_id) != g.tt:
            repo.mark_omdb_refresh(g.film_id)
            log(f"  omdb refresh queued (by id {g.tt})")
        applied += 1
    if apply:
        rebuild_no_match_queue(repo, today)
    counts = {
        v: sum(1 for g in groups if g.verdict == v)
        for v in ("keyed", "unlinked", "linked", "match", "review", "review-open", "conflict")
    }
    return NomatchReport(
        len(groups), counts["keyed"], counts["unlinked"], counts["linked"], counts["match"], counts["review"],
        counts["review-open"], counts["conflict"], applied, declined, skipped,
    )
