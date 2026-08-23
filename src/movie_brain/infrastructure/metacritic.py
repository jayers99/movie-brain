from __future__ import annotations

import json
import re
from pathlib import Path

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
