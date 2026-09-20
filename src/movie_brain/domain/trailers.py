"""Which video is the film's trailer (brief docs/superpowers/briefs/2026-09-20-trailer-link/brief.md).

TMDB files every video under a `type`; the wrong "trailers" elsewhere (clips, featurettes, a critic's
review) are what ignoring that label looks like — CheapCharts shows TMDB's first five videos of any
type. Measured on 400 live films, 2026-09-20: 30 of 30 picks read by title were trailers, and 243 of
244 still existed and allowed embedding.

Order: Trailer before Teaser; English (or no language) before the film's own language — a video in a
third language is a dub and never this film's trailer; TMDB's `official` first; then the sharper one.
Only YouTube is played. Apple's store preview (`APPLE`) is the stand-in, appended by the use case.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

YOUTUBE = "youtube"
APPLE = "apple"
APPLE_NAME = "Apple's store preview"
MAX_YOUTUBE = 3  # the pick and two in reserve: a dead first pick falls through without a new lookup
_TYPES = ("Trailer", "Teaser")
_NO_LANGUAGE = (None, "", "xx")
_YOUTUBE_KEY = re.compile(r"^[A-Za-z0-9_-]{6,20}$")  # the key is put inside a player URL


@dataclass(frozen=True)
class Trailer:
    source: str  # YOUTUBE: `ref` is the video key · APPLE: `ref` is the preview file's URL
    ref: str
    name: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "ref": self.ref, "name": self.name}


def pick_youtube(videos: Sequence[Mapping[str, Any]], original_language: str | None) -> list[Trailer]:
    def language_rank(video: Mapping[str, Any]) -> int | None:
        lang = video.get("iso_639_1")
        if lang == "en" or lang in _NO_LANGUAGE:
            return 0
        return 1 if lang == original_language else None

    ranked = [
        (_TYPES.index(v["type"]), rank, not v.get("official"), -int(v.get("size") or 0), i, v)
        for i, v in enumerate(videos)
        if v.get("site") == "YouTube"
        and v.get("type") in _TYPES
        and _YOUTUBE_KEY.match(str(v.get("key") or ""))
        and (rank := language_rank(v)) is not None
    ]
    ranked.sort(key=lambda r: r[:5])
    return [Trailer(YOUTUBE, str(r[5]["key"]), str(r[5].get("name") or "Trailer")) for r in ranked[:MAX_YOUTUBE]]
