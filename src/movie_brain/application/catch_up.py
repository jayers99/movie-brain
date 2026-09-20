"""The catch-up chain: every film gets its FULL enrichment when it is added (owner ruling
2026-09-20 — "anytime a new film is added, a full enrichment should be run … that way our database
doesn't have to continuously be scoured for missing sparse data").

Identity, ratings and availability were always sync's own steps (keying → OMDb → TMDB providers).
The four verbs below were each built "never in sync", because each one's FIRST run was a backlog of
thousands of films; with the backlogs drained every one of them is a worklist of the films added
since, so the chain costs a call or two per new film. It runs at the tail of `sync` and after every
verb that creates films. The order is load-bearing:

  credits → vectors   (the vector is made from the prose the credits call brings)
  store id → trailers (Apple's preview is found by store id)

The store-id step is only cheap because a CheapCharts miss is remembered (`store_lookup`, migration
029). Every step is the verb's own use case run with apply, under its own tripwire: one source
failing never stops the others, and nothing here can change an exit code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from movie_brain.application.cheapcharts import ResolveReport, resolve_itunes_ids
from movie_brain.application.embed import EmbedReport, embed_films
from movie_brain.application.enrich import EnrichReport, enrich_credits
from movie_brain.application.trailers import PreviewSource, TrailerReport, enrich_trailers
from movie_brain.infrastructure.cheapcharts import CheapChartsClient
from movie_brain.infrastructure.database import Repository
from movie_brain.infrastructure.embeddings import Embedder
from movie_brain.infrastructure.tmdb import TmdbClient


@dataclass(frozen=True)
class CatchUpReport:
    """A step's report, or None when the step was skipped or failed."""

    credits: EnrichReport | None = None
    embedded: EmbedReport | None = None
    store: ResolveReport | None = None
    trailers: TrailerReport | None = None

    def line(self) -> str:
        t = self.trailers
        return " · ".join([
            f"credits: {self.credits.enriched}" if self.credits else "credits: skipped",
            f"vectors: {self.embedded.embedded}" if self.embedded else "vectors: skipped",
            f"store ids: {self.store.resolved} of {self.store.scanned}" if self.store else "store ids: skipped",
            f"trailers: {t.with_youtube + t.apple_only} of {t.scanned}" if t else "trailers: skipped",
        ])


def catch_up(
    repo: Repository,
    today: date,
    *,
    tmdb: TmdbClient | None,
    cheapcharts: CheapChartsClient | None,
    itunes: PreviewSource | None,
    embedder: Embedder | None,
    log: Callable[[str], None],
) -> CatchUpReport:
    def step[R](name: str, run: Callable[[], R]) -> R | None:
        try:
            return run()
        except Exception as exc:  # noqa: BLE001 — one source failing must never break the others
            log(f"catch-up: {name} failed: {exc}")
            return None

    credits = embedded = store = trailers = None
    if tmdb is None:
        log("catch-up: no TMDB token — skipping credits and trailers")
    else:
        credits = step("credits", lambda: enrich_credits(repo, tmdb, today, apply=True, log=log))
    if embedder is None:
        log("catch-up: semantic search is not installed — skipping vectors (uv sync --extra semantic)")
    else:
        embedded = step("vectors", lambda: embed_films(repo, embedder, today, apply=True, log=log))
    if cheapcharts is not None:
        store = step("store ids", lambda: resolve_itunes_ids(repo, cheapcharts, today, apply=True, log=log))
    if tmdb is not None and itunes is not None:
        trailers = step("trailers", lambda: enrich_trailers(repo, tmdb, itunes, today, apply=True, log=log))
    return CatchUpReport(credits, embedded, store, trailers)
