from __future__ import annotations

import re
import time
from typing import Any

import requests

from movie_brain.domain.models import Film, film_key

BROWSE_URL = "https://www.criterionchannel.com/browse"
API_URL = "https://api.vhx.tv/collections"
PRODUCT = "https://api.vhx.tv/products/39621"
USER_AGENT = "movie-brain/0.1 (personal watchlist tool)"
_TOKEN_RE = re.compile(r'window\.TOKEN = "([^"]+)"')
_LEAVING_RE = re.compile(r"^Leaving\s+(.+)$")


class CatalogError(Exception):
    pass


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}


def fetch_token(session: requests.Session) -> str:
    resp = session.get(BROWSE_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    match = _TOKEN_RE.search(resp.text)
    if not match:
        raise CatalogError("no window.TOKEN on browse page — site markup changed?")
    return match.group(1)


def _to_film(item: dict[str, Any]) -> Film:
    meta = item.get("metadata") or {}
    return Film(
        title=item["name"],
        year=meta.get("year_released"),
        director=meta.get("director"),
        url=item.get("_links", {}).get("collection_page", {}).get("href") or "",
    )


def _has_next(payload: dict[str, Any]) -> bool:
    return bool((payload.get("_links", {}).get("next") or {}).get("href"))


def fetch_films(session: requests.Session, token: str, delay_s: float = 0.25) -> list[Film]:
    films: list[Film] = []
    page = 1
    while True:
        params: dict[str, str | int] = {"product": PRODUCT, "type[]": "movie", "per_page": 100, "page": page}
        resp = session.get(API_URL, params=params, headers=_headers(token), timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        batch = payload.get("_embedded", {}).get("collections", [])
        if not batch:
            break
        films.extend(_to_film(item) for item in batch)
        if not _has_next(payload):
            break
        page += 1
        time.sleep(delay_s)
    if not films:
        raise CatalogError("catalog returned zero films — API shape changed?")
    return films


def fetch_leaving(session: requests.Session, token: str, delay_s: float = 0.25) -> dict[str, str]:
    categories: list[dict[str, Any]] = []
    page = 1
    while True:
        params: dict[str, str | int] = {"product": PRODUCT, "type[]": "category", "per_page": 100, "page": page}
        resp = session.get(API_URL, params=params, headers=_headers(token), timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        categories += payload.get("_embedded", {}).get("collections", [])
        if not _has_next(payload):
            break
        page += 1
        time.sleep(delay_s)

    leaving: dict[str, str] = {}
    for cat in categories:
        match = _LEAVING_RE.match(cat.get("name") or "")
        if not match:
            continue
        label = match.group(1)
        page = 1
        while True:
            item_params: dict[str, str | int] = {
                "product": PRODUCT,
                "include_embedded": "true",
                "per_page": 100,
                "page": page,
            }
            resp = session.get(f"{API_URL}/{cat['id']}/items", params=item_params, headers=_headers(token), timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            for item in payload.get("_embedded", {}).get("items", []):
                meta = item.get("metadata") or {}
                if name := item.get("name"):
                    leaving[film_key(name, meta.get("year_released"))] = label
            if not _has_next(payload):
                break
            page += 1
            time.sleep(delay_s)
    return leaving


def page_one_matches(session: requests.Session, token: str, known: list[Film]) -> bool:
    params: dict[str, str | int] = {"product": PRODUCT, "type[]": "movie", "per_page": 100, "page": 1}
    resp = session.get(API_URL, params=params, headers=_headers(token), timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("total") != len(known):
        return False
    collections = payload.get("_embedded", {}).get("collections", [])
    if not collections:
        return False
    keys = {f.key for f in known}
    for item in collections:
        meta = item.get("metadata") or {}
        if film_key(item.get("name") or "", meta.get("year_released")) not in keys:
            return False
    return True
