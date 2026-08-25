"""Candidate pool builder for the thumbprint resolver (memo §3 "candidate pool").

One key→JSON ``CandidateCache`` serves both the offline benchmark fixture
(``scripts/eval/fixtures/cand_cache.json.gz``, read-only) and live use (an append-only cache
under the config dir). Keys are the prototype's scheme so the research fixture stays valid:
``ts:{title}|{year|None}`` ``tsy:{title}|{year}`` ``td:{tmdb_id}`` ``person:{name}``
``credits:{person_id}`` ``o:{json params, no apikey}``. OMDb ``t=`` is never used.
"""

from __future__ import annotations

import gzip
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from movie_brain.domain.matching import norm_title
from movie_brain.domain.thumbprint import Candidate, Query
from movie_brain.infrastructure.omdb import OmdbClient
from movie_brain.infrastructure.tmdb import TmdbClient


class CacheMiss(Exception):
    pass


def k_ts(t: str, y: int | None) -> str:
    return f"ts:{t}|{y}"


def k_tsy(t: str, y: int) -> str:
    return f"tsy:{t}|{y}"


def k_td(i: int) -> str:
    return f"td:{i}"


def k_person(n: str) -> str:
    return f"person:{n}"


def k_credits(i: int) -> str:
    return f"credits:{i}"


def k_o(**p: str) -> str:
    return "o:" + json.dumps(p, sort_keys=True)


class CandidateCache:
    def __init__(self, data: dict[str, Any], path: Path | None = None, read_only: bool = False) -> None:
        self.data = data
        self.path = path
        self.read_only = read_only
        self.misses = 0
        self.soft_misses = 0

    @classmethod
    def load(cls, path: Path, read_only: bool = False) -> CandidateCache:
        if not path.exists():
            return cls({}, path, read_only)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            return cls(json.load(f), path, read_only)

    def get(self, key: str, fetch: Callable[[], Any], *, soft: bool = False) -> Any:
        """``soft`` misses (a detail/by-id record the fixture never fetched) resolve to ``None``
        in read-only mode instead of raising — the prototype skipped them the same way."""
        if key in self.data:
            return self.data[key]
        if self.read_only:
            if soft:
                self.soft_misses += 1
                return None
            raise CacheMiss(key)
        value = fetch()
        self.data[key] = value
        self.misses += 1
        return value

    def save(self) -> None:
        if self.path is None or self.read_only:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        opener = gzip.open if self.path.suffix == ".gz" else open
        with opener(self.path, "wt", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False)


def _year(d: dict[str, Any]) -> int | None:
    s = str(d.get("release_date") or "")[:4]
    return int(s) if s.isdigit() else None


def _oyear(o: dict[str, Any]) -> int | None:
    m = re.match(r"\d{4}", o.get("Year") or "")
    return int(m.group()) if m else None


def _votes(o: dict[str, Any]) -> int:
    try:
        return int((o.get("imdbVotes") or "0").replace(",", ""))
    except ValueError:
        return 0


def _runtime(s: str | None) -> int | None:
    m = re.search(r"(\d+)\s*min", s or "")
    return int(m.group(1)) if m else None


def _directors(d: dict[str, Any]) -> str:
    return ", ".join(x["name"] for x in (d.get("credits") or {}).get("crew", []) if x.get("job") == "Director")


def _titles(d: dict[str, Any]) -> list[str]:
    return [d.get("title") or "", d.get("original_title") or ""] + [
        a.get("title") or "" for a in (d.get("alternative_titles") or {}).get("titles", [])
    ]


class _Acc:
    """Mutable candidate under construction (unified on tt)."""

    def __init__(self, tt: str) -> None:
        self.tt = tt
        self.tmdb_id: int | None = None
        self.titles: list[str] = []
        self.year: int | None = None
        self.directors = ""
        self.runtime: int | None = None
        self.votes = 0
        self.kind = "movie"
        self.otitle = ""
        self.in_tmdb = False
        self.in_omdb = False

    def freeze(self) -> Candidate:
        return Candidate(
            self.tt,
            self.tmdb_id,
            tuple(self.titles),
            self.year,
            self.directors,
            self.runtime,
            self.votes,
            self.kind,
            self.in_tmdb,
            self.in_omdb,
            self.otitle,
        )


class CandidateFetcher:
    def __init__(self, cache: CandidateCache, tmdb: TmdbClient | None, omdb: OmdbClient | None) -> None:
        self.cache, self.tmdb, self.omdb = cache, tmdb, omdb

    # --- raw lookups (cache-through) -----------------------------------------------------
    def _need(self, client: Any, key: str) -> Any:
        if client is None:
            raise CacheMiss(key)
        return client

    def _ts(self, t: str, y: int | None) -> list[dict[str, Any]]:
        res = self.cache.get(k_ts(t, y), lambda: self._need(self.tmdb, k_ts(t, y)).search_raw(t, y))
        return [x for x in (res or []) if isinstance(x, dict) and "id" in x]

    def _tsy(self, t: str, y: int) -> list[dict[str, Any]]:
        res = self.cache.get(
            k_tsy(t, y), lambda: self._need(self.tmdb, k_tsy(t, y)).search_raw(t, y, any_release_year=True)
        )
        return [x for x in (res or []) if isinstance(x, dict) and "id" in x]

    def _td(self, i: int) -> dict[str, Any]:
        d = self.cache.get(k_td(i), lambda: self._need(self.tmdb, k_td(i)).movie_detail(i), soft=True)
        return d if isinstance(d, dict) else {}

    def _person(self, name: str) -> list[dict[str, Any]]:
        res = self.cache.get(k_person(name), lambda: self._need(self.tmdb, k_person(name)).search_person(name))
        return [p for p in (res or []) if isinstance(p, dict) and "id" in p]

    def _credits(self, pid: int) -> list[dict[str, Any]]:
        res = self.cache.get(k_credits(pid), lambda: self._need(self.tmdb, k_credits(pid)).person_movie_credits(pid))
        return [x for x in (res or []) if isinstance(x, dict)]

    def _os(self, t: str, y: int | None) -> list[dict[str, Any]]:
        p = {"s": t} if y is None else {"s": t, "y": str(y)}
        key = k_o(**p)
        data = self.cache.get(key, lambda: {"Search": self._need(self.omdb, key).search(t, y)})
        return list((data or {}).get("Search") or [])

    def _oi(self, tt: str) -> dict[str, Any]:
        key = k_o(i=tt)
        data = self.cache.get(key, lambda: self._need(self.omdb, key).by_id(tt) or {"Response": "False"}, soft=True)
        return data if isinstance(data, dict) and data.get("imdbID") else {}

    # --- pool --------------------------------------------------------------------------
    def fetch(self, q: Query) -> list[Candidate]:
        t, yq = q.title, q.year
        nt = norm_title(t)
        seen: dict[str, _Acc] = {}

        def add_tmdb(x: dict[str, Any]) -> None:
            d = self._td(int(x["id"]))
            tt = (d.get("external_ids") or {}).get("imdb_id")
            if not tt:
                return
            c = seen.setdefault(tt, _Acc(tt))
            if not c.in_tmdb:
                c.in_tmdb = True
                c.tmdb_id = int(x["id"])
                c.titles = _titles(d) + c.titles
                c.year = _year(d)
                c.directors = _directors(d) or c.directors
                c.runtime = d.get("runtime") or c.runtime

        forms = {norm_title(f) for f in q.parsed.forms()}

        def plausible(j: int, x: dict[str, Any]) -> bool:
            # the prototype fetched details for the top 3 plus any exact-title hit (≤ 6 per query)
            return (
                j < 3 or norm_title(x.get("title") or "") in forms or norm_title(x.get("original_title") or "") in forms
            )

        picked: list[dict[str, Any]] = []
        for res in (self._ts(t, None), self._ts(t, yq)):
            for j, x in enumerate(res):
                if plausible(j, x) and x["id"] not in {p["id"] for p in picked} and len(picked) < 6:
                    picked.append(x)
        for x in picked:
            add_tmdb(x)
        # OMDb s= search (with and without the year); full record by id for the top 6 hits
        for res in (self._os(t, None), self._os(t, yq) if yq else []):
            for hit in res[:6]:
                o = self._oi(hit.get("imdbID") or "")
                if not o:
                    continue
                c = seen.setdefault(o["imdbID"], _Acc(o["imdbID"]))
                c.in_omdb = True
                c.titles.append(o.get("Title") or "")
                c.otitle = o.get("Title") or ""
                c.kind = o.get("Type") or "movie"
                c.year = c.year or _oyear(o)
                c.directors = c.directors or (o.get("Director") if o.get("Director") != "N/A" else "") or ""
                c.runtime = c.runtime or _runtime(o.get("Runtime"))
                c.votes = _votes(o)
        # ALG3 extras: any-release-year search + director credit search
        extra: list[dict[str, Any]] = [x for j, x in enumerate(self._tsy(t, yq)) if plausible(j, x)] if yq else []
        if q.director:
            names = [s.strip() for s in q.director.replace(" and ", ",").split(",") if s.strip()][:2]
            for name in names:
                for per in self._person(name):
                    for x in self._credits(int(per["id"])):
                        if x.get("job") != "Director":
                            continue
                        xt, xo = x.get("title") or "", x.get("original_title") or ""
                        ry = str(x.get("release_date") or "")[:4]
                        near = yq is not None and ry.isdigit() and abs(int(ry) - yq) <= 2
                        if norm_title(xt) == nt or norm_title(xo) == nt or (near and nt in norm_title(xt + xo)):
                            extra.append(x)
        for x in extra:
            if "id" in x:
                add_tmdb(x)
        # OMDb full record for every candidate (votes / type / director fallback)
        for c in seen.values():
            o = self._oi(c.tt)
            if o:
                c.in_omdb = c.in_omdb or False
                c.votes = _votes(o)
                c.otitle = o.get("Title") or ""
                c.kind = o.get("Type") or "movie"
                c.directors = c.directors or (o.get("Director") if o.get("Director") != "N/A" else "") or ""
                c.runtime = c.runtime or _runtime(o.get("Runtime"))
        return [c.freeze() for c in seen.values()]
