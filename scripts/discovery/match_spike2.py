import json, re, time, urllib.request, urllib.parse, pathlib

UA = "movie-brain-discovery-spike/0.1 (personal project)"
TOKEN = pathlib.Path.home().joinpath(".config/movie-brain/tmdb-read-token.txt").read_text().strip()

def fetch(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    return urllib.request.urlopen(req, timeout=30).read().decode()

def page_html(page):
    p = pathlib.Path(f"mc-page{page}.html")   # cache: never re-fetch a page we already have
    if not p.exists():
        p.write_text(fetch(f"https://www.metacritic.com/browse/movie/?page={page}"))
        time.sleep(3)
    return p.read_text()

def extract_cards(raw):
    m = re.search(r'<script type="application/json"[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', raw, re.S)
    data = json.loads(m.group(1))
    out = []
    for node in data:
        if isinstance(node, dict) and {"title", "slug", "premiereYear", "criticScoreSummary"} <= node.keys():
            title, year = data[node["title"]], data[node["premiereYear"]]
            if isinstance(title, str) and isinstance(year, int):
                out.append((title, year))
    return out

# --- normalization fixes ---
PAREN = re.compile(r"\s*\((?:re-release|\d{4})\)\s*$", re.I)
def clean_title(t):  # strip "(re-release)" / "(1988)" annotations
    return PAREN.sub("", t).strip()

def norm(t):  # punctuation/case-insensitive comparison key ("Forbidden Lie$" == "Forbidden Lies")
    return re.sub(r"[^a-z0-9]", "", t.casefold().replace("$", "s"))

def year_of(r):
    d = r.get("release_date") or ""
    return int(d[:4]) if len(d) >= 4 and d[:4].isdigit() else None

def tmdb_search(title):
    q = urllib.parse.urlencode({"query": title, "include_adult": "false"})
    return json.loads(fetch(f"https://api.themoviedb.org/3/search/movie?{q}",
                            {"Authorization": f"Bearer {TOKEN}"})).get("results", [])[:10]

def match(mc_title, mc_year):
    """MC year is US (re-)release year: accept any exact-title result whose ORIGINAL year
    is <= mc_year+2 (original release never postdates the US release by much)."""
    q = clean_title(mc_title)
    rs = tmdb_search(q)
    exact = [r for r in rs
             if (norm(r.get("title", "")) == norm(q) or norm(r.get("original_title", "")) == norm(q))
             and year_of(r) is not None and year_of(r) <= mc_year + 2]
    if exact:
        return "exact", max(exact, key=lambda r: r.get("popularity", 0))
    near = [r for r in rs[:3] if year_of(r) is not None and abs(year_of(r) - mc_year) <= 1]
    if near:
        return "near", near[0]
    return "miss", None

titles = []
for page in (1, 40, 80, 120):
    titles += extract_cards(page_html(page))

matched = nearc = miss = 0
misses = []
for t, y in titles:
    kind, r = match(t, y)
    if kind == "exact": matched += 1
    elif kind == "near": nearc += 1
    else: misses.append((t, y))
    time.sleep(0.35)

n = len(titles)
ok = matched + nearc
print(f"sampled {n} | matched {ok} ({ok/n:.0%}) — exact-title {matched}, near-year fallback {nearc} | miss {len(misses)} ({len(misses)/n:.0%})")
for m in misses: print("  still missing:", m)
