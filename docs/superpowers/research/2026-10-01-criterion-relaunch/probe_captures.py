"""Gap-check point A follow-up (2026-10-01): capture the real answers the spec leans on.

Writes into this folder: the full catalog walk (catalog-2026-10-01.json), the last catalog page,
the home page and leaving page HTML, the leaving playlist in full, and the status of the two
link forms (/films/<mediaid>/ and /search?q=). Polite: >=1 s between calls.
"""
import json
import pathlib
import re
import time

import requests

HERE = pathlib.Path(__file__).parent
UA = "movie-brain/0.1 (personal watchlist tool)"
BASE = "https://www.criterionchannel.com"
s = requests.Session()
s.headers["User-Agent"] = UA


def get(url, **kw):
    r = s.get(url, timeout=30, **kw)
    time.sleep(1)
    return r


# catalog, every page; keep the last raw page
items, key, pages, last = [], None, 0, None
while True:
    params = {"page_limit": 200}
    if key:
        params["pagination_key"] = key
    r = get(f"{BASE}/api/all-films/results", params=params)
    r.raise_for_status()
    last = r.json()
    pages += 1
    items += last["items"]
    key = (last.get("paging") or {}).get("next_pagination_key")
    if not key:
        break
(HERE / "catalog-2026-10-01.json").write_text(json.dumps(items, ensure_ascii=False, indent=0))
(HERE / "all-films-results.lastpage.json").write_text(json.dumps(last, ensure_ascii=False, indent=1))
print("catalog pages", pages, "items", len(items), "total", last.get("total"), "last paging", last.get("paging"))

home = get(f"{BASE}/")
(HERE / "home-2026-10-01.html").write_text(home.text)
leaving_links = sorted(set(re.findall(r'href="(/discover/leaving-[a-z]+-\d+)"', home.text)))
print("home", home.status_code, "leaving links", leaving_links)
for path in leaving_links:
    page = get(BASE + path)
    name = path.rsplit("/", 1)[1]
    (HERE / f"{name}.html").write_text(page.text)
    ids = sorted(set(re.findall(r'\\"playlistID\\":\\"([A-Za-z0-9]{8})\\"', page.text)))
    print(path, page.status_code, "playlist ids", ids)
    for pid in ids:
        pl = get(f"https://cdn.jwplayer.com/v2/playlists/{pid}", params={"page_limit": 500})
        (HERE / f"jw-playlist.{pid}.full.json").write_text(json.dumps(pl.json(), ensure_ascii=False, indent=1))
        print("  playlist", pid, pl.status_code, len(pl.json().get("playlist", [])))

for url in (f"{BASE}/films/gpRRkq27/", f"{BASE}/films/gpRRkq27", f"{BASE}/films/gpRRkq27/test-pattern",
            f"{BASE}/search?q=Test%20Pattern"):
    r = get(url, allow_redirects=False)
    print("link", url, r.status_code, r.headers.get("location", ""))

bad = get("https://cdn.jwplayer.com/v2/media/ZZZZZZZZ")
print("jw unknown media", bad.status_code, bad.text[:120])
