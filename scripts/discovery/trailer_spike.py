"""Discovery spike (2026-09-20, throwaway): which trailer source is most reliable?

Read-only on the live DB. Samples N films holding a TMDB id, asks TMDB for typed videos, checks each
picked YouTube key against YouTube's oEmbed (200 = exists and may be embedded), and asks the iTunes
lookup API (150 ids a call) for Apple's store preview. Findings: docs/superpowers/briefs/2026-09-20-trailer-link/.

    uv run python scripts/discovery/trailer_spike.py [N] [OUT.json]
"""
import json
import random
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from movie_brain.infrastructure.config import load_config, load_tmdb_token

OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("trailer_spike.json")
cfg = load_config()
token = load_tmdb_token(cfg)
db = sqlite3.connect(f"file:{cfg.db_path}?mode=ro", uri=True)
rows = db.execute(
    """
    SELECT f.id, f.title, f.year,
           (SELECT MIN(value) FROM external_ids WHERE film_id = f.id AND authority = 'tmdb'),
           (SELECT MIN(value) FROM external_ids WHERE film_id = f.id AND authority = 'itunes')
    FROM films f
    WHERE f.id NOT IN (SELECT film_id FROM film_disposition)
    """
).fetchall()
random.seed(20260920)
with_tmdb = [r for r in rows if r[3]]
sample = random.sample(with_tmdb, int(sys.argv[1]) if len(sys.argv) > 1 else 400)

s = requests.Session()
s.headers["Authorization"] = f"Bearer {token}"


def tmdb_videos(tmdb_id):
    for _ in range(3):
        r = s.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}/videos", params={"language": "en-US"}, timeout=20)
        if r.status_code == 429:
            time.sleep(2)
            continue
        if r.status_code != 200:
            return []
        return r.json().get("results", [])
    return []


def embeddable(key):
    """YouTube oEmbed: 200 = public + embeddable, 401 = embedding disabled, 404/400 = gone/private."""
    r = requests.get(
        "https://www.youtube.com/oembed",
        params={"url": f"https://www.youtube.com/watch?v={key}", "format": "json"},
        timeout=20,
    )
    if r.status_code == 200:
        j = r.json()
        return {"status": 200, "yt_title": j.get("title"), "channel": j.get("author_name")}
    return {"status": r.status_code}


def pick(videos):
    """The obvious pick rule: YouTube Trailers, official first, then newest-published last? keep simple."""
    yt = [v for v in videos if v.get("site") == "YouTube"]
    for typ in ("Trailer", "Teaser"):
        c = [v for v in yt if v.get("type") == typ]
        c.sort(key=lambda v: (not v.get("official"), -(v.get("size") or 0)))
        if c:
            return c[0], [v["key"] for v in c]
    return None, []


def one(row):
    fid, title, year, tmdb_id, itunes_id = row
    vids = tmdb_videos(tmdb_id)
    best, keys = pick(vids)
    rec = {
        "film_id": fid, "title": title, "year": year, "tmdb": tmdb_id, "itunes": itunes_id,
        "n_videos": len(vids), "types": sorted({v.get("type") for v in vids}),
        "pick": None, "pick_checks": [],
    }
    if best:
        rec["pick"] = {k: best.get(k) for k in ("key", "name", "type", "official", "size", "published_at")}
        for k in keys[:3]:  # does a fallback save a dead first pick?
            chk = embeddable(k)
            rec["pick_checks"].append({"key": k, **chk})
            if chk["status"] == 200:
                break
    return rec


with ThreadPoolExecutor(8) as ex:
    recs = list(ex.map(one, sample))

# iTunes lookup, batched (one call per 150 ids)
ids = [r["itunes"] for r in recs if r["itunes"]]
previews = {}
for i in range(0, len(ids), 150):
    chunk = ids[i : i + 150]
    r = requests.get("https://itunes.apple.com/lookup", params={"id": ",".join(chunk), "country": "us"}, timeout=30)
    for item in r.json().get("results", []):
        previews[str(item.get("trackId"))] = {
            "previewUrl": item.get("previewUrl"), "trackName": item.get("trackName"),
        }
    time.sleep(3)
for r in recs:
    r["itunes_lookup"] = previews.get(r["itunes"]) if r["itunes"] else None

OUT.write_text(json.dumps(recs, indent=1))

n = len(recs)
has_pick = [r for r in recs if r["pick"]]
first_ok = [r for r in has_pick if r["pick_checks"] and r["pick_checks"][0]["status"] == 200]
any_ok = [r for r in has_pick if any(c["status"] == 200 for c in r["pick_checks"])]
with_it = [r for r in recs if r["itunes"]]
it_found = [r for r in with_it if r["itunes_lookup"]]
it_prev = [r for r in it_found if r["itunes_lookup"]["previewUrl"]]
print(f"sample {n}")
print(f"TMDB: any video {sum(1 for r in recs if r['n_videos'])}, trailer/teaser pick {len(has_pick)}, "
      f"first pick plays embedded {len(first_ok)}, some pick (≤3) plays {len(any_ok)}")
print(f"  official flag on pick: {sum(1 for r in has_pick if r['pick']['official'])}")
statuses = {}
for r in has_pick:
    st = r["pick_checks"][0]["status"]
    statuses[st] = statuses.get(st, 0) + 1
print(f"  first-pick oEmbed statuses: {statuses}")
print(f"iTunes: films with store id {len(with_it)}, lookup answered {len(it_found)}, previewUrl {len(it_prev)}")
def yt_ok(r):
    return any(c["status"] == 200 for c in r["pick_checks"])


def apple_ok(r):
    return bool((r["itunes_lookup"] or {}).get("previewUrl"))


either = [r for r in recs if yt_ok(r) or apple_ok(r)]
only_it = [r for r in recs if not yt_ok(r) and apple_ok(r)]
print(f"either source {len(either)}; iTunes rescues {len(only_it)} TMDB misses")
by_decade = {}
for r in recs:
    d = (r["year"] or 0) // 10 * 10
    a = by_decade.setdefault(d, [0, 0])
    a[0] += 1
    a[1] += any(c["status"] == 200 for c in r["pick_checks"])
print("TMDB playable by decade:", {d: f"{v[1]}/{v[0]}" for d, v in sorted(by_decade.items())})
