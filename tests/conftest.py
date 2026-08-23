from datetime import date
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MOVIE_BRAIN_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("OMDB_API_KEY", raising=False)


@pytest.fixture
def config_dir(tmp_path) -> Path:
    d = tmp_path / "cfg"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture
def today() -> date:
    return date(2026, 8, 19)


@pytest.fixture
def repo(config_dir):
    from movie_brain.infrastructure.database import Repository

    return Repository(config_dir / "movie-brain.db")


@pytest.fixture
def nuxt_page():
    """Build a browse-page HTML body in the __NUXT_DATA__ shape the parser reads.

    Nuxt serializes a flat array where dict values are indices into the same array;
    a title card is a dict holding indices for title, slug, premiereYear, and
    criticScoreSummary (itself a dict whose "score" key indexes the int score).
    Cards are (title, slug, year, score) tuples.
    """
    import json

    def build(cards):
        data = ["root"]

        def add(value):
            data.append(value)
            return len(data) - 1

        for title, slug, year, score in cards:
            summary_idx = add({"score": add(score)})
            data.append(
                {
                    "title": add(title),
                    "slug": add(slug),
                    "premiereYear": add(year),
                    "criticScoreSummary": summary_idx,
                }
            )
        payload = json.dumps(data)
        return f'<html><body><script type="application/json" id="__NUXT_DATA__">{payload}</script></body></html>'

    return build
