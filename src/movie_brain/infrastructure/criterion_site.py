"""The Criterion Channel after its 2026-10-01 relaunch (Next.js + JW Player).

Real answers seen on 2026-10-01 live in docs/superpowers/research/2026-10-01-criterion-relaunch/;
the spec is docs/superpowers/specs/2026-10-01-criterion-relaunch-design.md (D1, D3, D7)."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from movie_brain.infrastructure.cheapcharts import Pacer

BASE = "https://www.criterionchannel.com"
CATALOG_URL = f"{BASE}/api/all-films/results"
USER_AGENT = "movie-brain/0.1 (personal watchlist tool)"
PAGE_LIMIT = 200
CATALOG_DELAY_S = 1.0
BACKOFF_S = (2, 4, 8)
JW_MEDIA_URL = "https://cdn.jwplayer.com/v2/media/{}"
JW_DELAY_S = 0.25
JW_PLAYLIST_URL = "https://cdn.jwplayer.com/v2/playlists/{}"
BRIDGE_DELAY_S = 0.4

_DATED = re.compile(r'href="(/discover/(leaving-[a-z]+-\d{1,2}))"')
_PLAYLIST_ID = re.compile(r'\\"playlistID\\":\\"([A-Za-z0-9]{8})\\"')
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_EST = timezone(timedelta(hours=-5))  # Criterion sets some expiries at EST midnight all year
_FILM_PATH = re.compile(r"^/films/([A-Za-z0-9]{8})(?:/|$)")


class CriterionError(Exception):
    """The site did not answer usably: the walk must write nothing."""


@dataclass(frozen=True)
class CatalogItem:
    mediaid: str
    title: str
    year: int | None
    duration_s: int


@dataclass(frozen=True)
class JwMedia:
    mediaid: str
    title: str
    title_original: str | None
    release_date: str | None
    directors: tuple[str, ...]
    criterion_id: str | None
    license_start: str | None
    license_end: str | None
    content_type: str


@dataclass(frozen=True)
class Leaving:
    labels: dict[str, str]
    mismatches: tuple[str, ...]


@dataclass(frozen=True)
class Forward:
    status: int | None
    location: str | None
    mediaid: str | None
    kind: str  # film | supplement | gone | retry


def _year(release_date: str | None) -> int | None:
    """`release_date` is always `YYYY-01-01` in the list; `0-01-01` and `2915-01-01` were seen."""
    try:
        y = int(str(release_date or "").split("-")[0])
    except ValueError:
        return None
    return y if 1880 <= y <= date.today().year + 2 else None


def _json_list(raw: object) -> tuple[str, ...]:
    """JW stores `director`, `country`, `language`, `starring` as JSON-encoded STRINGS."""
    if not isinstance(raw, str) or not raw:
        return ()
    try:
        value = json.loads(raw)
    except ValueError:
        return ()
    return tuple(str(v) for v in value) if isinstance(value, list) else ()


def _blank(raw: object) -> str | None:
    return str(raw) if raw not in (None, "") else None


def _get(
    session: requests.Session,
    url: str,
    pacer: Pacer,
    sleep: Callable[[float], None],
    params: dict[str, Any] | None = None,
    allow_redirects: bool = True,
) -> requests.Response:
    """One paced GET with the 429 back-off. Network errors and 5xx raise CriterionError."""
    for attempt in range(len(BACKOFF_S) + 1):
        pacer.wait()
        try:
            resp = session.get(
                url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30, allow_redirects=allow_redirects
            )
        except requests.RequestException as exc:
            raise CriterionError(f"{url}: {exc}") from exc
        if resp.status_code != 429:
            if resp.status_code >= 500:
                raise CriterionError(f"{url}: HTTP {resp.status_code}")
            return resp
        if attempt < len(BACKOFF_S):
            sleep(BACKOFF_S[attempt])
    raise CriterionError(f"{url}: still 429 after {len(BACKOFF_S)} back-offs")


def fetch_catalog(
    session: requests.Session, pacer: Pacer | None = None, sleep: Callable[[float], None] = time.sleep
) -> list[CatalogItem]:
    """Every FILM in the catalog (D1). Series are counted against `total` but never returned;
    a repeated mediaid keeps its first item (Bad Timing is listed twice under one id)."""
    pacer = pacer or Pacer(CATALOG_DELAY_S, sleep=sleep)
    raw: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    key: str | None = None
    total: int | None = None
    while True:
        params: dict[str, Any] = {"page_limit": PAGE_LIMIT}
        if key is not None:
            params["pagination_key"] = key
        resp = _get(session, CATALOG_URL, pacer, sleep, params=params)
        if resp.status_code != 200:
            raise CriterionError(f"catalog: HTTP {resp.status_code}")
        try:
            body = resp.json()
        except (ValueError, requests.exceptions.JSONDecodeError) as exc:
            raise CriterionError(f"catalog: malformed JSON — {exc}") from exc
        items = body.get("items") or []
        if not items:
            raise CriterionError("catalog: empty page — site changed?")
        raw.extend(items)
        total = body.get("total")
        key = (body.get("paging") or {}).get("next_pagination_key")
        if not key:
            break
        if key in seen_keys:
            raise CriterionError(f"catalog: repeated cursor {key!r}")
        seen_keys.add(key)
    if total != len(raw):
        raise CriterionError(f"catalog: walked {len(raw)} items, site says total {total}")
    films: list[CatalogItem] = []
    taken: set[str] = set()
    for it in raw:
        if it.get("contentType") != "film" or it.get("mediaid") in taken:
            continue
        try:
            mediaid = it["mediaid"]
            title = it["title"]
            duration = int(it.get("duration") or 0)
        except (KeyError, ValueError, TypeError) as exc:
            raise CriterionError(f"catalog: malformed film item — {exc}") from exc
        taken.add(mediaid)
        films.append(CatalogItem(
            mediaid,
            title,
            _year(it.get("release_date")),
            duration,
        ))
    return films


def fetch_media(
    session: requests.Session, mediaid: str, pacer: Pacer | None = None, sleep: Callable[[float], None] = time.sleep
) -> JwMedia | None:
    """One film's JW record. None = JW answered 404 (no such id) — an answer, not weather."""
    pacer = pacer or Pacer(JW_DELAY_S, sleep=sleep)
    resp = _get(session, JW_MEDIA_URL.format(mediaid), pacer, sleep)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise CriterionError(f"jw media {mediaid}: HTTP {resp.status_code}")
    try:
        body = resp.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise CriterionError(f"jw media {mediaid}: malformed JSON — {exc}") from exc
    playlist = body.get("playlist") or []
    if not playlist:
        raise CriterionError(f"jw media {mediaid}: empty playlist")
    item = playlist[0]
    return JwMedia(
        mediaid=str(item.get("mediaid") or mediaid),
        title=str(item.get("title") or ""),
        title_original=_blank(item.get("title_original")),
        release_date=_blank(item.get("release_date")),
        directors=_json_list(item.get("director")),
        criterion_id=_blank(item.get("criterion_id")),
        license_start=_blank(item.get("license_start_date_time")),
        license_end=_blank(item.get("license_end_date_time")),
        content_type=str(item.get("contentType") or ""),
    )


def label_from_slug(slug: str) -> str | None:
    m = re.fullmatch(r"leaving-([a-z]+)-(\d{1,2})", slug)
    if not m or m.group(1) not in _MONTHS:
        return None
    return f"{m.group(1).capitalize()} {int(m.group(2))}"


def _expiry_label(license_end: str | None) -> str | None:
    if not license_end:
        return None
    try:
        moment = datetime.fromisoformat(license_end.replace("Z", "+00:00")).astimezone(_EST)
    except ValueError:
        return None
    return f"{moment.strftime('%B')} {moment.day}"


def fetch_leaving(
    session: requests.Session, pacer: Pacer | None = None, sleep: Callable[[float], None] = time.sleep
) -> Leaving:
    """Labels from every DATED leaving page the home page links (D7). The label is the page's
    own slug; each film's `license_end_date_time` is only a cross-check, reported on mismatch."""
    pacer = pacer or Pacer(JW_DELAY_S, sleep=sleep)
    home = _get(session, BASE + "/", pacer, sleep)
    if home.status_code != 200:
        raise CriterionError(f"home page: HTTP {home.status_code}")
    pages = sorted({(path, slug) for path, slug in _DATED.findall(home.text) if label_from_slug(slug)})
    labels: dict[str, str] = {}
    mismatches: list[str] = []
    for path, slug in pages:
        label = label_from_slug(slug)
        assert label is not None
        page = _get(session, BASE + path, pacer, sleep)
        if page.status_code != 200:
            raise CriterionError(f"{path}: HTTP {page.status_code}")
        pids = list(dict.fromkeys(_PLAYLIST_ID.findall(page.text)))
        if not pids:
            raise CriterionError(f"{path}: no playlistID found")
        for pid in pids:
            pl = _get(session, JW_PLAYLIST_URL.format(pid), pacer, sleep, params={"page_limit": 500})
            if pl.status_code != 200:
                raise CriterionError(f"playlist {pid}: HTTP {pl.status_code}")
            try:
                body = pl.json()
            except (ValueError, requests.exceptions.JSONDecodeError) as exc:
                raise CriterionError(f"playlist {pid}: malformed JSON — {exc}") from exc
            for item in body.get("playlist") or []:
                mediaid = item.get("mediaid")
                if not mediaid:
                    continue
                labels[mediaid] = label
                expiry = _expiry_label(item.get("license_end_date_time"))
                if expiry is not None and expiry != label:
                    mismatches.append(f"{mediaid} {item.get('title')!r}: page says {label}, expiry says {expiry}")
    return Leaving(labels, tuple(mismatches))


def classify_forward(status: int | None, location: str | None) -> Forward:
    path = urlparse(location).path if location else ""
    if status in (301, 302, 307, 308):
        m = _FILM_PATH.match(path)
        if m:
            return Forward(status, location, m.group(1), "film")
        if path.startswith("/supplements/"):
            return Forward(status, location, None, "supplement")
    if status == 404:
        return Forward(status, location, None, "gone")
    return Forward(status, location, None, "retry")


def head_old_url(session: requests.Session, url: str, pacer: Pacer) -> Forward:
    """Where an old `criterionchannel.com/<slug>` link forwards now (D3). Never follows, never raises."""
    pacer.wait()
    try:
        resp = session.head(url, headers={"User-Agent": USER_AGENT}, timeout=30, allow_redirects=False)
    except requests.RequestException:
        return Forward(None, None, None, "retry")
    return classify_forward(resp.status_code, resp.headers.get("Location"))
