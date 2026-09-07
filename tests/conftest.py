import math
import re
import zlib
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

from movie_brain.domain.search import EMBED_DIM


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


# Concept groups for the fake: words in one group share a dimension, so "gumshoe" is near
# "private eye" the way the real model makes them near — see the plan's fixture table.
_CONCEPTS = {
    "private": 0, "eye": 0, "detective": 0, "gumshoe": 0, "sleuth": 0, "investigator": 0,
    "nurse": 1, "ward": 1, "caregiver": 1, "medic": 1,
    "alpha": 2,
    "sternwood": 3,
}
_STOPWORDS = {"a", "an", "the", "in", "of", "on", "and", "at", "to"}
_FIRST_FREE_DIM = 8


class FakeEmbedder:
    """Deterministic bag-of-concepts vectors, L2-normalised to EMBED_DIM. Records every text it is asked to encode."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            self.asked.append(text)
            v = [0.0] * EMBED_DIM
            for word in re.findall(r"[a-z0-9$]+", text.lower()):
                if word in _STOPWORDS:
                    continue
                dim = _CONCEPTS.get(word)
                if dim is None:
                    dim = _FIRST_FREE_DIM + zlib.crc32(word.encode()) % (EMBED_DIM - _FIRST_FREE_DIM)
                v[dim] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()
