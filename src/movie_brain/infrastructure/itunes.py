"""Apple's iTunes lookup API: the store's own preview file for a store id (trailer-link brief).

`lookup?id=` takes many ids in one call and needs no key and no account. It is the LOOKUP endpoint,
by ids movie-brain already holds — not the title search of backlog 23. A product Apple has removed
is simply absent from the answer, and so has no preview."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from urllib.parse import urlsplit

import requests

from movie_brain.infrastructure.cheapcharts import Pacer

LOOKUP_URL = "https://itunes.apple.com/lookup"
BATCH = 150   # ids per call
DELAY_S = 3.0  # Apple throttles the public API at roughly twenty calls a minute


def _is_apple_file(url: object) -> bool:
    """The URL becomes a <video src> in the drawer: only an https file on Apple's own hosts is believed."""
    if not isinstance(url, str):
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and (parts.hostname or "").endswith(".apple.com")


class ItunesLookup:
    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        delay_s: float = DELAY_S,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session or requests.Session()
        self._pacer = Pacer(delay_s, sleep, clock)

    def previews(self, itunes_ids: Sequence[str]) -> dict[str, str]:
        """Store id → preview URL, for the ids that have one. Raises `requests.RequestException`."""
        out: dict[str, str] = {}
        for start in range(0, len(itunes_ids), BATCH):
            self._pacer.wait()
            resp = self.session.get(
                LOOKUP_URL, params={"id": ",".join(itunes_ids[start : start + BATCH]), "country": "us"}, timeout=30
            )
            resp.raise_for_status()
            for item in resp.json().get("results") or []:
                url = item.get("previewUrl")
                if item.get("trackId") is not None and _is_apple_file(url):
                    out[str(item["trackId"])] = url
        return out
