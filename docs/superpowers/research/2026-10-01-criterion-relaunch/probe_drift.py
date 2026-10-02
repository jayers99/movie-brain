"""Offline (2026-10-01): join old-url-redirects.tsv with catalog-2026-10-01.json -> drift.tsv,
so every drift number in the spec and brief can be re-checked from saved files alone.
Columns: film_id, our title/year, status, mediaid, in_catalog, catalog title/year, drift kind."""
import csv
import json
import pathlib

HERE = pathlib.Path(__file__).parent
cat = {}
for i in json.loads((HERE / "catalog-2026-10-01.json").read_text()):
    cat.setdefault(i["mediaid"], i)
rows = list(csv.DictReader(open(HERE / "old-url-redirects.tsv"), delimiter="\t"))
out = open(HERE / "drift.tsv", "w", newline="")
w = csv.writer(out, delimiter="\t")
w.writerow(["film_id", "title", "year", "status", "mediaid", "in_catalog", "cat_title", "cat_year", "kind"])
counts = {}
for r in rows:
    m = r["mediaid"]
    it = cat.get(m) if m else None
    if not m:
        kind = "supplement" if "/supplements/" in r["location"] else "gone-404"
    elif not it:
        kind = "departed"
    else:
        t = it["title"] != r["title"]
        y = it["release_date"][:4] != r["year"]
        kind = {(False, False): "same", (True, False): "title", (False, True): "year", (True, True): "both"}[(t, y)]
    counts[kind] = counts.get(kind, 0) + 1
    w.writerow([r["film_id"], r["title"], r["year"], r["status"], m, bool(it),
                it["title"] if it else "", it["release_date"][:4] if it else "", kind])
print(counts)
films = [i for i in cat.values() if i["contentType"] == "film"]
print("series", sum(i["contentType"] == "series" for i in cat.values()),
      "junk years", [(i["title"], i["release_date"]) for i in cat.values() if i["release_date"][:2] not in ("19", "20")])
