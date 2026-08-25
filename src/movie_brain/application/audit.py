"""Data audit (spec 2026-08-24-data-audit-design.md §3): fill TMDB facts, run the pure
checks, replace the flags, report. Read-only with respect to every other table."""

from __future__ import annotations

import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import requests

from movie_brain.domain.audit import AuditFlag, run_checks, total_score
from movie_brain.infrastructure.database import Repository, TmdbFactsRow
from movie_brain.infrastructure.tmdb import AuthError, TmdbClient

TOP_N = 20


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass
class AuditReport:
    facts_fetched: int = 0
    facts_failed: int = 0
    films: int = 0
    suspects: int = 0
    by_reason: dict[str, int] = field(default_factory=dict)
    top: list[tuple[int, str, int, list[str]]] = field(default_factory=list)  # (film_id, title, score, codes)
    exit_code: int = 0


def _fill_facts(
    repo: Repository,
    tmdb: TmdbClient,
    today: date,
    delay_s: float,
    log: Callable[[str], None],
    report: AuditReport,
) -> None:
    for film_id, tmdb_id in repo.tmdb_facts_needed():
        try:
            f = tmdb.movie_facts(tmdb_id)
        except AuthError as exc:
            log(f"TMDB rejected the token: {exc} — facts fill stopped, offline checks continue")
            return
        except (requests.RequestException, ValueError) as exc:
            log(f"tmdb facts failed for film {film_id} (id {tmdb_id}): {exc}")
            report.facts_failed += 1
            continue
        repo.upsert_tmdb_facts(
            film_id,
            TmdbFactsRow(tmdb_id, f.imdb_id, f.title, f.original_title, f.alternatives, f.year, f.runtime_min),
            today,
        )
        report.facts_fetched += 1
        if delay_s:
            time.sleep(delay_s)


def run_audit(
    repo: Repository,
    today: date,
    *,
    tmdb: TmdbClient | None,
    delay_s: float = 0.25,
    log: Callable[[str], None] = _stderr,
) -> AuditReport:
    report = AuditReport()
    if tmdb is not None:
        _fill_facts(repo, tmdb, today, delay_s, log, report)
    subjects = repo.audit_subjects()
    flags: dict[int, list[AuditFlag]] = {}
    titles: dict[int, str] = {}
    for s in subjects:
        fl = run_checks(s)
        if fl:
            flags[s.film_id] = fl
            titles[s.film_id] = s.title
    repo.replace_audit_flags(flags, today)
    report.films = len(subjects)
    report.suspects = len(flags)
    report.by_reason = dict(Counter(f.code for fl in flags.values() for f in fl))
    ranked = sorted(flags.items(), key=lambda kv: (-total_score(kv[1]), kv[0]))
    report.top = [(fid, titles[fid], total_score(fl), [f.code for f in fl]) for fid, fl in ranked[:TOP_N]]
    return report
