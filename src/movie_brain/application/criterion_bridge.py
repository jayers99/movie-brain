"""`criterion bridge`: give every stored Criterion film its new id (spec D3).

Each stored old link (`criterionchannel.com/<slug>`) still forwards to `/films/<mediaid>/<slug>`.
The dry run asks every link and keeps the answers in `<config_dir>/criterion-bridge.jsonl`
(the OBSERVATION file — nothing in the database); `--apply` replays answers younger than 24
hours, writes the database in ONE transaction, and only then marks the lines `applied`."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from movie_brain.domain.models import ReviewEntry
from movie_brain.infrastructure.criterion_site import BASE, CatalogItem, Forward, classify_forward
from movie_brain.infrastructure.database import Repository

BRIDGE_FILE = "criterion-bridge.jsonl"
FRESH_FOR = timedelta(hours=24)


@dataclass
class Observation:
    url: str
    film_id: int
    status: int | None
    location: str | None
    asked_at: str
    applied: bool = False

    @property
    def forward(self) -> Forward:
        return classify_forward(self.status, self.location)


def load_observations(path: Path) -> dict[str, Observation]:
    out: dict[str, Observation] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        try:
            raw = json.loads(line)
            obs = Observation(
                url=str(raw["url"]),
                film_id=int(raw["film_id"]),
                status=raw["status"],
                location=raw["location"],
                asked_at=str(raw["asked_at"]),
                applied=bool(raw.get("applied", False)),
            )
        except (ValueError, KeyError, TypeError):
            continue  # a half-written line from an interrupted run: that URL is asked again
        out[obs.url] = obs
    return out


def append_observation(path: Path, obs: Observation) -> None:
    # If file exists, is non-empty, and does not end in "\n", prepend a newline
    # to recover from a killed run that left no trailing newline
    if path.exists() and path.stat().st_size > 0:
        content = path.read_text()
        if not content.endswith("\n"):
            with path.open("a") as fh:
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())

    with path.open("a") as fh:
        fh.write(json.dumps(asdict(obs)) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def rewrite_observations(path: Path, observations: Iterable[Observation]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as fh:
        for obs in observations:
            fh.write(json.dumps(asdict(obs)) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def is_fresh(obs: Observation, now: datetime) -> bool:
    try:
        asked = datetime.fromisoformat(obs.asked_at)
    except ValueError:
        return False
    return now - asked < FRESH_FOR


@dataclass(frozen=True)
class DriftLine:
    film_id: int
    title: str
    year: int | None
    cat_title: str
    cat_year: int | None
    kind: str  # title | year | both


@dataclass
class BridgeReport:
    counts: dict[str, int]
    drift: list[DriftLine]
    reviews: int
    applied: bool
    reopened: int
    multi: int = 0  # films that bound more than one distinct mediaid in this run


def run_bridge(
    repo: Repository,
    config_dir: Path,
    catalog: list[CatalogItem],
    ask: Callable[[str], Forward],
    now: datetime,
    apply: bool,
    retry: bool,
) -> BridgeReport:
    path = config_dir / BRIDGE_FILE
    obs = load_observations(path)

    reopened = 0
    settled: set[str] = set()
    for o in obs.values():
        if not o.applied:
            continue
        mid = o.forward.mediaid
        if mid and ("criterion", mid) in repo.external_ids_all(repo.canonical_film_id(o.film_id)):
            settled.add(o.url)
        else:
            o.applied = False
            reopened += 1

    targets = repo.criterion_old_urls()
    for t in targets:
        existing: Observation | None = obs.get(t.url)
        if existing is not None and t.url in settled:
            reuse = True
        else:
            reuse = (
                existing is not None
                and (not apply or is_fresh(existing, now))
                and not (retry and existing.forward.kind == "retry")
            )
        if reuse:
            assert existing is not None
            existing.film_id = t.film_id
            continue
        f = ask(t.url)
        o = Observation(t.url, t.film_id, f.status, f.location, now.isoformat())
        append_observation(path, o)
        obs[t.url] = o

    holders = {
        v: repo.canonical_film_id(fid)
        for v, fid in repo.external_id_holders("criterion").items()
        if not v.startswith("http")
    }
    open_keys = {(str(r["reason"]), r["film_id"], r["value"]) for r in repo.open_reviews("criterion")}
    decided = repo.resolved_review_keys("criterion")
    by_mediaid = {c.mediaid: c for c in catalog}
    titles = {t.film_id: (t.title, t.year) for t in targets}

    counts: dict[str, int] = {}
    bindings: list[tuple[int, str, str]] = []
    bound_urls: list[str] = []
    reviews: list[ReviewEntry] = []
    drift: list[DriftLine] = []
    for t in targets:
        o = obs[t.url]
        f = o.forward
        kind = f.kind
        if kind == "film":
            assert f.mediaid is not None
            assert f.location is not None
            holder = holders.get(f.mediaid)
            if holder is None:
                holders[f.mediaid] = t.film_id
                bindings.append((t.film_id, f.mediaid, BASE + urlparse(f.location).path))
                bound_urls.append(t.url)
            elif holder == t.film_id:
                kind = "same-film"
                bound_urls.append(t.url)
            else:
                kind = "held"
                key = ("id-conflict", t.film_id, f.mediaid)
                if key not in open_keys and key not in decided:
                    open_keys.add(key)
                    reviews.append(
                        ReviewEntry("id-conflict", t.film_id, f.mediaid, json.dumps({"holder": holder, "url": t.url}))
                    )
            if kind in ("film", "same-film") and f.mediaid in by_mediaid:
                cat = by_mediaid[f.mediaid]
                title, year = titles[t.film_id]
                diff_t, diff_y = cat.title != title, cat.year != year
                if diff_t or diff_y:
                    dk = "both" if diff_t and diff_y else ("title" if diff_t else "year")
                    if not any(d.film_id == t.film_id for d in drift):
                        drift.append(DriftLine(t.film_id, title, year, cat.title, cat.year, dk))
        counts[kind] = counts.get(kind, 0) + 1

    if apply:
        repo.record_bridge(bindings, reviews, now.date())
        for url in bound_urls:
            obs[url].applied = True
        rewrite_observations(path, obs.values())
    bound_ids: dict[int, set[str]] = {}
    for film_id, mediaid, _url in bindings:
        bound_ids.setdefault(film_id, set()).add(mediaid)
    multi = sum(1 for ids in bound_ids.values() if len(ids) > 1)
    return BridgeReport(counts, drift, len(reviews), apply, reopened, multi)
