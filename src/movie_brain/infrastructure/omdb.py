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

    def lookup(self, title: str, year: int | None) -> OmdbRating:
        candidates = [year] if year is None else [year, year - 1, year + 1]
        rating = OmdbRating(None, None, False)
        for candidate in candidates:
            rating = self._query(title, candidate)
            if rating.found:
                return rating
        return rating

    def _query(self, title: str, year: int | None) -> OmdbRating:
        params: dict[str, str] = {"t": title, "type": "movie", "apikey": self.api_key}
        if year:
            params["y"] = str(year)
        resp = self.session.get(OMDB_URL, params=params, timeout=30)
        if resp.status_code == 401:
            error = resp.json().get("Error") or ""
            if "limit" in error.lower():
                raise QuotaExceeded(title)
            raise AuthError(error or "invalid API key")
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if data.get("Response") != "True":
            if "limit" in (data.get("Error") or "").lower():
                raise QuotaExceeded(title)
            return OmdbRating(None, None, False)
        imdb = float(data["imdbRating"]) if data.get("imdbRating") and data["imdbRating"] != "N/A" else None
        rt = None
        for entry in data.get("Ratings", []):
            if entry.get("Source") == "Rotten Tomatoes":
                rt = int(entry["Value"].rstrip("%"))
        language = data.get("Language")
        if not language or language == "N/A":
            language = None
        return OmdbRating(imdb=imdb, rt=rt, found=True, language=language, payload=resp.text)
