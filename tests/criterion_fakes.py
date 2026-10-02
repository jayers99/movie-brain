"""Injected fakes for the Criterion walk tests (spec 2026-10-01 §5).

`FakeSite` stands where `HttpCriterionSite` stands in `sync()`. Its JW records are the real
captured answer (`tests/fixtures/criterion/jw-media.L5Z3RaiC.json`) with named fields changed,
parsed by the real `parse_media` — no record shape is invented here. Catalog items are the
adapter's own `CatalogItem`, the shape `fetch_catalog` returns."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from movie_brain.domain.models import Film
from movie_brain.infrastructure.criterion_site import CatalogItem, CriterionError, JwMedia, Leaving, parse_media

FIX = Path(__file__).parent / "fixtures" / "criterion"
_CAPTURE = json.loads((FIX / "jw-media.L5Z3RaiC.json").read_text())


def captured_media() -> JwMedia:
    """The 2 or 3 Things I Know About Her record exactly as JW answered on 2026-10-01."""
    return parse_media(copy.deepcopy(_CAPTURE), "L5Z3RaiC")


def captured(mediaid: str) -> JwMedia:
    """A JW record exactly as JW answered (`tests/fixtures/criterion/jw-media.<mediaid>.json`):
    `3ehCWylD` and `5pVD2vhU` were asked on 2026-10-02 for the directors step (spec D8)."""
    return parse_media(json.loads((FIX / f"jw-media.{mediaid}.json").read_text()), mediaid)


def media_like(mediaid: str, title: str, directors: Iterable[str] = (), title_original: str | None = None) -> JwMedia:
    body = copy.deepcopy(_CAPTURE)
    body["playlist"][0].update(
        {
            "mediaid": mediaid,
            "title": title,
            "title_original": title_original or title,
            "director": json.dumps(list(directors)),  # JW stores the list as a JSON string
        }
    )
    return parse_media(body, mediaid)


def mediaid_for(title: str) -> str:
    """A stable 8-character mediaid for a test film the spec does not name."""
    return hashlib.sha1(title.encode()).hexdigest()[:8]


def seed_known(repo, films: Iterable[Film], seen: date) -> list[CatalogItem]:
    """Films as `criterion bridge --apply` leaves them — each holding its mediaid — and the
    catalog items that list them, so a walk treats every one as KNOWN."""
    items = []
    for f in films:
        fid = repo.upsert_film(f)
        m = mediaid_for(f.title)
        repo.set_external_id(fid, "criterion", m, seen)
        items.append(CatalogItem(m, f.title, f.year, 5400))
    return items


class FakeSite:
    def __init__(self) -> None:
        self.items: list[CatalogItem] = []
        self.media_by_id: dict[str, JwMedia] = {}  # a mediaid not here answers like JW's 404
        self.media_fails: set[str] = set()
        self.leaving_labels: dict[str, str] | None = {}  # None: the leaving pages cannot be read
        self.catalog_fails = False
        self.calls: list[str] = []

    def catalog(self) -> list[CatalogItem]:
        self.calls.append("catalog")
        if self.catalog_fails:
            raise CriterionError("catalog: HTTP 500")
        return list(self.items)

    def media(self, mediaid: str) -> JwMedia | None:
        self.calls.append(f"media:{mediaid}")
        if mediaid in self.media_fails:
            raise CriterionError(f"jw media {mediaid}: HTTP 503")
        return self.media_by_id.get(mediaid)

    def leaving(self) -> Leaving:
        self.calls.append("leaving")
        if self.leaving_labels is None:
            raise CriterionError("home page: HTTP 500")
        return Leaving(dict(self.leaving_labels), ())

    @property
    def media_calls(self) -> list[str]:
        return [c.removeprefix("media:") for c in self.calls if c.startswith("media:")]
