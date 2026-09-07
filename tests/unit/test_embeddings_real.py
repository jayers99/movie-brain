"""The one test that loads the real model. Skipped unless `uv sync --extra semantic` has run."""

from __future__ import annotations

import pytest

pytest.importorskip("sentence_transformers")

from movie_brain.domain.search import EMBED_DIM  # noqa: E402
from movie_brain.infrastructure.embeddings import SentenceTransformerEmbedder  # noqa: E402


@pytest.mark.semantic
def test_real_model_puts_two_detective_sentences_closer_than_a_third():
    e = SentenceTransformerEmbedder()
    a, b, c = e.encode([
        "A private detective takes on a case in San Francisco.",
        "A hard-boiled private investigator is hired by a wealthy general.",
        "A nurse works the night shift in a hospital ward.",
    ])
    assert len(a) == EMBED_DIM
    dot = lambda x, y: sum(p * q for p, q in zip(x, y, strict=True))  # noqa: E731
    assert dot(a, b) > dot(a, c) and dot(a, b) > dot(b, c)
