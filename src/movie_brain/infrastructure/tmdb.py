from __future__ import annotations

import requests

from movie_brain.domain.matching import norm_title, split_annotations
from movie_brain.domain.models import TmdbCandidate, TmdbProviders

TMDB_API = "https://api.themoviedb.org/3"


class AuthError(Exception):
    pass


def watch_link(tmdb_id: int) -> str:
    return f"https://www.themoviedb.org/movie/{tmdb_id}/watch?locale=US"


class TmdbClient:
    def __init__(self, token: str, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {token}"}

    def _get(self, path: str, **params: str) -> requests.Response:
        resp = self.session.get(f"{TMDB_API}{path}", params=params, headers=self.headers, timeout=30)
        if resp.status_code == 401:
            raise AuthError(resp.json().get("status_message") or "invalid bearer token")
        resp.raise_for_status()
        return resp

    def search(self, title: str) -> list[TmdbCandidate]:
        results = self._get("/search/movie", query=title, include_adult="false").json().get("results", [])
        out = []
        for r in results[:10]:
            d = r.get("release_date") or ""
            year = int(d[:4]) if len(d) >= 4 and d[:4].isdigit() else None
            out.append(
                TmdbCandidate(
                    int(r["id"]), r.get("title") or "", r.get("original_title") or "",
                    year, float(r.get("popularity") or 0.0),
                )
            )
        return out

    def watch_providers(self, tmdb_id: int) -> TmdbProviders:
        resp = self._get(f"/movie/{tmdb_id}/watch/providers")
        us = resp.json().get("results", {}).get("US", {})

        def ids(kind: str) -> tuple[int, ...]:
            return tuple(int(p["provider_id"]) for p in us.get(kind, []))

        return TmdbProviders(flatrate=ids("flatrate"), rent=ids("rent"), buy=ids("buy"),
                             link=us.get("link"), payload=resp.text)

    def movie_year(self, tmdb_id: int) -> int | None:
        d = self._get(f"/movie/{tmdb_id}").json().get("release_date") or ""
        return int(d[:4]) if len(d) >= 4 and d[:4].isdigit() else None

    def movie_titles(self, tmdb_id: int) -> tuple[str, str, int | None]:
        d = self._get(f"/movie/{tmdb_id}").json()
        rd = d.get("release_date") or ""
        year = int(rd[:4]) if len(rd) >= 4 and rd[:4].isdigit() else None
        return d.get("title") or "", d.get("original_title") or "", year


class TmdbArbiter:
    """Spec principle 4: does TMDB know a same-titled film near the claimed year?

    One cached search per normalized title; ``seed()`` lets a match step donate a
    search it already performed so arbitration costs no extra API call for that
    title. Network failure answers ``None`` (arbiter unavailable) — the core then
    falls back to a year-gap review instead of guessing.
    """

    def __init__(self, client: TmdbClient) -> None:
        self._client = client
        self._cache: dict[str, list[TmdbCandidate]] = {}

    def seed(self, title: str, candidates: list[TmdbCandidate]) -> None:
        self._cache[norm_title(title)] = candidates

    def __call__(self, title: str, claimed_year: int) -> bool | None:
        key = norm_title(title)
        if key not in self._cache:
            try:
                self._cache[key] = self._client.search(title)
            except (AuthError, requests.RequestException):
                return None
        stripped = norm_title(split_annotations(title)[0])
        for c in self._cache[key]:
            if c.year is None or abs(c.year - claimed_year) > 1:
                continue
            if any(norm_title(split_annotations(t)[0]) == stripped for t in (c.title, c.original_title)):
                return True
        return False
