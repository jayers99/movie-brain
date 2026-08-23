from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from movie_brain.infrastructure import metacritic as mc

AUTHORITY = "metacritic"


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class CrawlReport:
    exit_code: int
    fetched: int
    skipped: int
    archived: int  # pages now in the archive


def crawl_archive(
    config_dir: Path,
    pages: int,
    *,
    session: requests.Session | None = None,
    delay_s: float = 3.0,
    log: Callable[[str], None] = _stderr,
) -> CrawlReport:
    archive = mc.archive_dir(config_dir)
    result = mc.crawl(archive, pages, session or requests.Session(), delay_s=delay_s, log=log)
    return CrawlReport(1 if result.failed else 0, result.fetched, result.skipped, len(mc.archived_pages(archive)))
