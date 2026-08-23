import json, time, urllib.request, urllib.parse, pathlib

TOKEN = pathlib.Path.home().joinpath(".config/movie-brain/tmdb-read-token.txt").read_text().strip()
def get(path, **params):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"https://api.themoviedb.org/3{path}?{q}",
                                 headers={"Authorization": f"Bearer {TOKEN}"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

WANT = ["criterion", "apple tv", "itunes", "max", "peacock", "prime", "mubi", "bfi"]

# 1) provider registry, US then GB
for region in ("US", "GB"):
    provs = get("/watch/providers/movie", watch_region=region)["results"]
    hits = [f"{p['provider_name']} (id {p['provider_id']})"
            for p in provs if any(w in p["provider_name"].lower() for w in WANT)]
    print(f"--- {region} providers matching our services ({len(provs)} total) ---")
    for h in sorted(hits): print("  ", h)

# 2) per-film availability
FILMS = ["Tokyo Story", "Seven Samurai", "Boyhood", "Oppenheimer", "Manchester by the Sea",
         "CODA", "Decision to Leave", "Aftersun", "In the Mood for Love", "The Conformist"]
print("\n--- per-film US availability ---")
for name in FILMS:
    rs = get("/search/movie", query=name).get("results", [])
    if not rs: print(f"{name}: SEARCH MISS"); continue
    m = rs[0]
    prov = get(f"/movie/{m['id']}/watch/providers")["results"]
    us = prov.get("US", {})
    def names(kind): return [p["provider_name"] for p in us.get(kind, [])][:6]
    print(f"{m['title']} ({(m.get('release_date') or '????')[:4]}):")
    print(f"    stream: {names('flatrate') or '—'}")
    print(f"    rent/buy: {sorted(set(names('rent') + names('buy'))) or '—'}")
    if "GB" in prov and name in ("Aftersun", "In the Mood for Love"):
        print(f"    GB stream: {[p['provider_name'] for p in prov['GB'].get('flatrate', [])][:6]}")
    time.sleep(0.3)
