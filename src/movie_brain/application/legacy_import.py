from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from movie_brain.domain.models import Film, OmdbRating
from movie_brain.infrastructure.database import Repository

SOURCE = "criterion"


@dataclass
class ImportReport:
    films: int = 0
    omdb: int = 0
    payloads: int = 0
    ratings: int = 0
    unmatched_keys: list[str] = field(default_factory=list)


def _payload_path(legacy_dir: Path, key: str) -> Path:
    return legacy_dir / "payloads" / (key.replace("/", "_") + ".json")


def import_legacy(repo: Repository, legacy_dir: Path, today: date) -> ImportReport:
    report = ImportReport()
    catalog_path = legacy_dir / "catalog.json"
    if not catalog_path.exists():
        raise FileNotFoundError(catalog_path)
    catalog = json.loads(catalog_path.read_text())
    fetched_at = date.fromisoformat(catalog["films_fetched_at"])
    films = [Film(f["title"], f["year"], f["director"], f["url"]) for f in catalog["films"]]
    repo.record_catalog(SOURCE, films, fetched_at)
    repo.set_meta("films_fetched_at", fetched_at.isoformat())
    repo.set_leaving(SOURCE, catalog.get("leaving") or {})
    report.films = len(films)

    cache_path = legacy_dir / "cache.json"
    cache: dict[str, dict[str, object]] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    for key, entry in cache.items():
        film_id = repo.film_id_by_key(key)
        if film_id is None:
            report.unmatched_keys.append(key)
            continue
        found = bool(entry["found"])
        payload_file = _payload_path(legacy_dir, key)
        payload = payload_file.read_text(encoding="utf-8") if found and payload_file.exists() else None
        if payload is not None:
            report.payloads += 1
        imdb = entry.get("imdb")
        rt = entry.get("rt")
        language = entry.get("language")
        repo.upsert_omdb(
            film_id,
            OmdbRating(
                imdb=float(imdb) if isinstance(imdb, int | float) else None,
                rt=int(rt) if isinstance(rt, int) else None,
                found=found,
                language=str(language) if isinstance(language, str) else None,
                payload=payload,
            ),
            date.fromisoformat(str(entry["looked_up"])),
            year_fallback=bool(entry.get("year_fallback", False)),
            needs_refresh=found and "language" not in entry,
        )
        report.omdb += 1

    ann_path = legacy_dir / "annotations.json"
    annotations: dict[str, int] = json.loads(ann_path.read_text()) if ann_path.exists() else {}
    for key, score in annotations.items():
        film_id = repo.film_id_by_key(key)
        if film_id is None:
            report.unmatched_keys.append(key)
            continue
        repo.set_rating(film_id, int(score), today)
        report.ratings += 1
    return report
