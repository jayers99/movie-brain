"""Embed every film's prose for semantic search — the data under stage 4 of the bar (Plan C, D21).

Dry-run by default: the worklist is counted and logged and the embedder is never touched (the
model load is the slow part, and a dry run has nothing to encode for). `--apply` encodes in
batches and writes each batch in one transaction, stamping `embedded_on`; stamped films leave
the worklist, so an interrupted run resumes at the next batch. A film re-enriched after it was
embedded returns to the worklist (`films_needing_embedding`). Never called from `sync`.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from movie_brain.domain.search import EMBED_DIM, EMBED_MODEL, embedding_text
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.embeddings import Embedder, pack

BATCH_SIZE = 128


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


@dataclass(frozen=True)
class EmbedReport:
    scanned: int = 0  # films on the worklist that hold prose
    embedded: int = 0  # written (apply) — equals scanned on a completed apply run
    skipped_no_prose: int = 0  # worklist films whose three prose fields are all empty; never embedded


def embed_films(
    repo: Repository,
    embedder: Embedder,
    today: date,
    *,
    apply: bool = False,
    limit: int | None = None,
    batch_size: int = BATCH_SIZE,
    log: Callable[[str], None] = _stderr,
) -> EmbedReport:
    scanned = embedded = skipped = 0
    batch: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal embedded
        if not batch:
            return
        vectors = embedder.encode([text for _, text in batch])
        repo.write_embeddings(
            [(film_id, pack(v)) for (film_id, _), v in zip(batch, vectors, strict=True)],
            today, model=EMBED_MODEL, dim=EMBED_DIM,
        )
        embedded += len(batch)
        log(f"  embedded {len(batch)} (through #{batch[-1][0]})")
        batch.clear()

    for target in repo.films_needing_embedding(EMBED_MODEL, limit):
        text = embedding_text(target.overview, target.plot, target.tagline)
        if text is None:
            skipped += 1
            continue
        scanned += 1
        if not apply:
            continue
        batch.append((target.film_id, text))
        if len(batch) >= batch_size:
            flush()
    flush()
    log(f"worklist: {scanned} to embed · {skipped} with no prose (never embedded)")
    return EmbedReport(scanned, embedded, skipped)
