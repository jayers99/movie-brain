from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests

from movie_brain.domain.models import McTitle

BROWSE_URL = "https://www.metacritic.com/browse/movie/"
USER_AGENT = "movie-brain/0.1 (personal project)"
CARDS_PER_PAGE = 24
MAX_CONSECUTIVE_FAILURES = 3

_NUXT = re.compile(r'<script type="application/json"[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)
_CARD_KEYS = {"title", "slug", "premiereYear", "criticScoreSummary"}


class CrawlError(Exception):
    pass


def archive_dir(config_dir: Path) -> Path:
    return config_dir / "metacritic"


def page_path(archive: Path, page: int) -> Path:
    return archive / "pages" / f"page-{page:04d}.html"


def archived_pages(archive: Path) -> list[int]:
    pages = archive / "pages"
    if not pages.exists():
        return []
    return sorted(int(p.stem.split("-")[1]) for p in pages.glob("page-*.html"))


def parse_page(html: str, page: int) -> list[McTitle]:
    """Extract title cards from a browse page's __NUXT_DATA__ JSON island.

    The island is a flat array whose dict values hold indices into the same array;
    a card is any dict carrying all of _CARD_KEYS. Parsing reads the archive only —
    a parser fix means re-running match, never re-fetching.
    """
    m = _NUXT.search(html)
    if not m:
        return []
    data = json.loads(m.group(1))
    titles: list[McTitle] = []
    for node in data:
        if not (isinstance(node, dict) and node.keys() >= _CARD_KEYS):
            continue
        title, slug, year = data[node["title"]], data[node["slug"]], data[node["premiereYear"]]
        if not (isinstance(title, str) and isinstance(slug, str)):
            continue
        summary = data[node["criticScoreSummary"]]
        score = None
        if isinstance(summary, dict) and "score" in summary:
            raw = data[summary["score"]]
            if isinstance(raw, int):
                score = raw
        rank = (page - 1) * CARDS_PER_PAGE + len(titles) + 1
        mc_year = year if isinstance(year, int) else None
        titles.append(McTitle(slug=slug, title=title, year=mc_year, score=score, rank=rank, page=page))
    return titles


def parse_archive(archive: Path) -> list[McTitle]:
    titles: list[McTitle] = []
    for page in archived_pages(archive):
        titles.extend(parse_page(page_path(archive, page).read_text(), page))
    return titles


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class CrawlResult:
    fetched: int
    skipped: int
    failed: bool


def crawl(
    archive: Path,
    pages: int,
    session: requests.Session,
    *,
    delay_s: float = 3.0,
    log: Callable[[str], None] = _stderr,
) -> CrawlResult:
    """Politely walk browse pages 1..pages into the raw archive.

    An archived page is never re-fetched, so the archive is its own checkpoint: a
    later call with a bigger ``pages`` extends it, and a mid-walk stop loses nothing.
    Never touches the database. A page with no parseable cards (bot wall) is a
    failure — archiving it would poison the parse step.
    """
    (archive / "pages").mkdir(parents=True, exist_ok=True)
    fetched = skipped = consecutive = 0
    requested = False
    for page in range(1, pages + 1):
        target = page_path(archive, page)
        if target.exists():
            skipped += 1
            continue
        if requested:
            time.sleep(delay_s)
        requested = True
        try:
            resp = session.get(BROWSE_URL, params={"page": page}, headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
            if not parse_page(resp.text, page):
                raise CrawlError(f"page {page}: no title cards in response")
        except (requests.RequestException, CrawlError) as exc:
            consecutive += 1
            log(f"fetch failed ({consecutive}/{MAX_CONSECUTIVE_FAILURES}): {exc}")
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                log("stopping — archived pages kept; the next crawl resumes here")
                return CrawlResult(fetched, skipped, True)
            continue
        target.write_text(resp.text)
        entry = {"page": page, "url": resp.url, "fetched_at": datetime.now(UTC).isoformat(), "status": resp.status_code}
        with (archive / "fetch-log.jsonl").open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
        fetched += 1
        consecutive = 0
    return CrawlResult(fetched, skipped, False)
