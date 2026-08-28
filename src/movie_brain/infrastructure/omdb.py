from __future__ import annotations

from typing import Any

import requests

from movie_brain.domain.models import OmdbRating

OMDB_URL = "https://www.omdbapi.com/"


class QuotaExceeded(Exception):
    pass


class AuthError(Exception):
    pass


class OmdbClient:
    def __init__(self, api_key: str, session: requests.Session | None = None) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()

    def lookup_by_imdb(self, imdb_id: str) -> OmdbRating:
        """Exact lookup by IMDb id — immune to OMDb's US-release-year and title quirks."""
        return self._fetch({"i": imdb_id, "apikey": self.api_key})

    # --- thumbprint resolver: search (s=) and by-id (i=) raw payloads; never t= -----------
    def search(self, title: str, year: int | None = None) -> list[dict[str, Any]]:
        params = {"s": title, "apikey": self.api_key}
        if year is not None:
            params["y"] = str(year)
        data = self._raw(params)
        found: list[dict[str, Any]] = data.get("Search") or []
        return found

    def by_id(self, imdb_id: str) -> dict[str, Any]:
        """Full record by IMDb id; ``{}`` when OMDb has no such id."""
        data = self._raw({"i": imdb_id, "apikey": self.api_key})
        return data if data.get("Response") == "True" else {}

    def _raw(self, params: dict[str, str]) -> dict[str, Any]:
        resp = self.session.get(OMDB_URL, params=params, timeout=30)
        if resp.status_code == 401:
            error = resp.json().get("Error") or ""
            if "limit" in error.lower():
                raise QuotaExceeded(params.get("s") or params.get("i") or "")
            raise AuthError(error or "invalid API key")
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if "limit" in (data.get("Error") or "").lower():
            raise QuotaExceeded(params.get("s") or params.get("i") or "")
        return data

    def _fetch(self, params: dict[str, str]) -> OmdbRating:
        resp = self.session.get(OMDB_URL, params=params, timeout=30)
        if resp.status_code == 401:
            error = resp.json().get("Error") or ""
            if "limit" in error.lower():
                raise QuotaExceeded(params.get("t") or params.get("i") or "")
            raise AuthError(error or "invalid API key")
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if data.get("Response") != "True":
            if "limit" in (data.get("Error") or "").lower():
                raise QuotaExceeded(params.get("t") or params.get("i") or "")
            return OmdbRating(None, None, False)
        imdb = float(data["imdbRating"]) if data.get("imdbRating") and data["imdbRating"] != "N/A" else None
        rt = None
        for entry in data.get("Ratings", []):
            if entry.get("Source") == "Rotten Tomatoes":
                rt = int(entry["Value"].rstrip("%"))
        metascore = data.get("Metascore")
        metacritic = int(metascore) if isinstance(metascore, str) and metascore.isdigit() else None
        language = data.get("Language")
        if not language or language == "N/A":
            language = None
        return OmdbRating(imdb=imdb, rt=rt, metacritic=metacritic, found=True, language=language, payload=resp.text)
