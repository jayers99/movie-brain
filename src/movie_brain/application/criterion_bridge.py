"""`criterion bridge`: give every stored Criterion film its new id (spec D3).

Each stored old link (`criterionchannel.com/<slug>`) still forwards to `/films/<mediaid>/<slug>`.
The dry run asks every link and keeps the answers in `<config_dir>/criterion-bridge.jsonl`
(the OBSERVATION file — nothing in the database); `--apply` replays answers younger than 24
hours, writes the database in ONE transaction, and only then marks the lines `applied`."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from movie_brain.infrastructure.criterion_site import Forward, classify_forward

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
                url=str(raw["url"]), film_id=int(raw["film_id"]), status=raw["status"],
                location=raw["location"], asked_at=str(raw["asked_at"]), applied=bool(raw.get("applied", False)),
            )
        except (ValueError, KeyError, TypeError):
            continue  # a half-written line from an interrupted run: that URL is asked again
        out[obs.url] = obs
    return out


def append_observation(path: Path, obs: Observation) -> None:
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
