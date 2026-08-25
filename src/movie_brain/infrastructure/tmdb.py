from __future__ import annotations

from typing import Any, NamedTuple

import requests

from movie_brain.domain.matching import norm_title, split_annotations
from movie_brain.domain.models import TmdbCandidate, TmdbProviders

TMDB_API = "https://api.themoviedb.org/3"


class AuthError(Exception):
    pass


class TmdbTitles(NamedTuple):
    title: str
    original: str
    year: int | None
    alternatives: tuple[str, ...]


class TmdbFacts(NamedTuple):
    imdb_id: str | None
    title: str
    original_title: str
    alternatives: tuple[str, ...]
    year: int | None
    runtime_min: int | None


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

    def search(self, title: str, year: int | None = None) -> list[TmdbCandidate]:
        """Top-10 title search. With a trusted ``year`` (an original release year, never a
        commerce/re-release year), retry with ``primary_release_year`` when nothing on the
        title page lands within ±1 of it — TMDB ranks by popularity, so an old feature can sit
        behind a page of later same-titled films (Intolerance 1916). One extra call, only then."""
        out = self._search_page(query=title, include_adult="false")
        if year is not None and not any(c.year is not None and abs(c.year - year) <= 1 for c in out):
            seen = {c.tmdb_id for c in out}
            out += [
                c
                for c in self._search_page(query=title, include_adult="false", primary_release_year=str(year))
                if c.tmdb_id not in seen
            ]
        return out

    def _search_page(self, **params: str) -> list[TmdbCandidate]:
        results = self._get("/search/movie", **params).json().get("results", [])
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

    # --- thumbprint resolver (raw payloads; the resolver unifies on IMDb id) ---------------
    def search_raw(
        self, title: str, year: int | None = None, *, any_release_year: bool = False
    ) -> list[dict[str, Any]]:
        """Top-10 raw search results. ``year`` filters by ``primary_release_year``; with
        ``any_release_year`` it uses TMDB's ``year`` (any release date) instead."""
        params: dict[str, str] = {"query": title, "include_adult": "false"}
        if year is not None:
            params["year" if any_release_year else "primary_release_year"] = str(year)
        results: list[dict[str, Any]] = self._get("/search/movie", **params).json().get("results", [])
        return results[:10]

    def search_person(self, name: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = self._get("/search/person", query=name).json().get("results", [])
        return results[:2]

    def person_movie_credits(self, person_id: int) -> list[dict[str, Any]]:
        crew: list[dict[str, Any]] = self._get(f"/person/{person_id}/movie_credits").json().get("crew", [])
        return crew

    def movie_detail(self, tmdb_id: int) -> dict[str, Any]:
        detail: dict[str, Any] = self._get(
            f"/movie/{tmdb_id}", append_to_response="external_ids,credits,alternative_titles"
        ).json()
        return detail

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

    def imdb_id(self, tmdb_id: int) -> str | None:
        """IMDb id for a TMDB movie (one call) — the exact key OMDb answers to."""
        v = self._get(f"/movie/{tmdb_id}/external_ids").json().get("imdb_id")
        return str(v) if v else None

    def movie_titles(self, tmdb_id: int) -> TmdbTitles:
        """Title, original title, year, and every alternative title — one API call."""
        d = self._get(f"/movie/{tmdb_id}", append_to_response="alternative_titles").json()
        rd = d.get("release_date") or ""
        year = int(rd[:4]) if len(rd) >= 4 and rd[:4].isdigit() else None
        alts = tuple(
            str(t["title"]) for t in (d.get("alternative_titles") or {}).get("titles") or [] if t.get("title")
        )
        return TmdbTitles(d.get("title") or "", d.get("original_title") or "", year, alts)

    def movie_facts(self, tmdb_id: int) -> TmdbFacts:
        """Everything the audit compares against, in ONE call (alt titles + external ids appended)."""
        d = self._get(f"/movie/{tmdb_id}", append_to_response="alternative_titles,external_ids").json()
        rd = d.get("release_date") or ""
        year = int(rd[:4]) if len(rd) >= 4 and rd[:4].isdigit() else None
        alts = tuple(
            str(t["title"]) for t in (d.get("alternative_titles") or {}).get("titles") or [] if t.get("title")
        )
        runtime = d.get("runtime")
        imdb = (d.get("external_ids") or {}).get("imdb_id")
        return TmdbFacts(
            imdb_id=str(imdb) if imdb else None,
            title=d.get("title") or "",
            original_title=d.get("original_title") or "",
            alternatives=alts,
            year=year,
            runtime_min=int(runtime) if isinstance(runtime, int) and runtime > 0 else None,
        )


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
