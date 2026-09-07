"""Embeddings adapter for semantic search (Plan C, spec D14, D19, D20).

`Embedder` is the one port: texts in, unit vectors out. `SentenceTransformerEmbedder` is the
real adapter and imports torch LAZILY on the first `encode`, because import-plus-load measured
4.9 s and would otherwise tax every dashboard start and every test that builds the app.
`VectorIndex` is the whole search index: the catalogue's vectors as one numpy matrix, loaded on
first use and rebuilt when the table's (count, latest stamp) changes; cosine over 4,645 × 384
measured 0.08 ms per query, which is why there is no sqlite-vec here. numpy is imported inside
the class so a core install without the `semantic` extra never fails to import this module.
"""

from __future__ import annotations

import importlib.util
import logging
import struct
from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from movie_brain.domain.search import EMBED_DIM, EMBED_MODEL
from movie_brain.infrastructure.database import Repository

log = logging.getLogger(__name__)

_FORMAT = f"<{EMBED_DIM}f"  # yt-brain's `_to_blob`, byte for byte


class SemanticUnavailable(RuntimeError):
    """The optional extra is missing, or the model cannot be loaded (not cached, offline)."""


class Embedder(Protocol):
    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


def pack(vector: Sequence[float]) -> bytes:
    if len(vector) != EMBED_DIM:
        raise ValueError(f"expected {EMBED_DIM} floats, got {len(vector)}")
    return struct.pack(_FORMAT, *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(_FORMAT, blob))


class SentenceTransformerEmbedder:
    """all-MiniLM-L6-v2 through sentence-transformers; normalised output; lazy load."""

    def __init__(self, model_name: str = EMBED_MODEL) -> None:
        self.model_name = model_name
        self._model: Any = None

    @staticmethod
    def available() -> bool:
        """Cheap: is the extra importable? Never imports torch."""
        return importlib.util.find_spec("sentence_transformers") is not None

    def _load(self) -> Any:
        if self._model is None:
            if not self.available():
                raise SemanticUnavailable("semantic search is not installed — uv sync --extra semantic")
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.model_name)
            except Exception as exc:  # model not cached and offline, broken install, …
                raise SemanticUnavailable(f"could not load {self.model_name}: {exc}") from exc
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(list(texts), batch_size=128, normalize_embeddings=True, show_progress_bar=False)
        return [[float(x) for x in v] for v in vectors]


class VectorIndex:
    """Brute-force cosine over every stored vector for one model. Vectors are stored normalised,
    so distance = 1 − dot. Rebuilt lazily whenever `Repository.embedding_stamp` changes —
    `(count, max embedded_on, Σ film_id)` over the same non-disposed rows `all_embeddings` reads,
    so the sum catches a merge moving a film_id onto its survivor and a tombstone dropping a row
    out of the non-disposed set, neither of which moves `embedding_summary`'s bare (count, max)
    alone. A failed model load latches: once `embed_query` has raised `SemanticUnavailable` once,
    every later call on this instance raises immediately without asking the embedder again, for
    the life of this `VectorIndex`."""

    def __init__(self, repo: Repository, embedder: Embedder, model: str = EMBED_MODEL) -> None:
        self.repo = repo
        self.embedder = embedder
        self.model = model
        self._stamp: tuple[int, str, int] | None = None
        self._ids: list[int] = []
        self._matrix: Any = None
        self._warned = False
        self._unavailable = False

    def _ensure(self) -> None:
        stamp = self.repo.embedding_stamp(self.model)
        if stamp == self._stamp:
            return
        import numpy as np

        rows = self.repo.all_embeddings(self.model)
        self._ids = [film_id for film_id, _ in rows]
        blob = b"".join(vector for _, vector in rows)
        self._matrix = np.frombuffer(blob, dtype="<f4").reshape(len(rows), EMBED_DIM) if rows else None
        self._stamp = stamp

    def __len__(self) -> int:
        self._ensure()
        return len(self._ids)

    def embed_query(self, text: str) -> list[float]:
        if self._unavailable:
            raise SemanticUnavailable("semantic search is off for this process")
        try:
            return self.embedder.encode([text])[0]
        except SemanticUnavailable as exc:
            if not self._warned:
                log.warning("semantic search off: %s", exc)
                self._warned = True
            self._unavailable = True
            raise

    def _scores(self, vector: Sequence[float]) -> tuple[list[int], Any]:
        self._ensure()
        ids, matrix = self._ids, self._matrix  # snapshot together: _ensure may replace both
        if matrix is None:
            return ids, None
        import numpy as np

        return ids, matrix @ np.asarray(vector, dtype="<f4")

    def nearest(self, vector: Sequence[float], floor: float) -> list[tuple[int, float]]:
        ids, scores = self._scores(vector)
        if scores is None:
            return []
        hits = [(ids[i], float(1.0 - s)) for i, s in enumerate(scores) if 1.0 - s <= floor]
        hits.sort(key=lambda t: (t[1], t[0]))
        return hits

    def distances(self, vector: Sequence[float], ids: Iterable[int]) -> dict[int, float]:
        row_ids, scores = self._scores(vector)
        if scores is None:
            return {}
        pos = {film_id: i for i, film_id in enumerate(row_ids)}
        return {film_id: float(1.0 - scores[pos[film_id]]) for film_id in ids if film_id in pos}
