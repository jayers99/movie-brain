"""Spike for backlog 23: why do the 20 known misses miss? READ-ONLY. Throwaway."""
import sqlite3, sys
from pathlib import Path
from movie_brain.infrastructure.cheapcharts import CheapChartsClient, RateLimited
from movie_brain.infrastructure.tmdb import TmdbClient
from movie_brain.infrastructure.config import load_config, load_tmdb_token
from movie_brain.application.cheapcharts import _confirm, _refusal
from movie_brain.domain.models import ItunesTarget

IDS = [123,812,876,1625,1689,2174,2915,3705,4558,4618,4647,4929,4936,4972,5019,5074,5126,5138,5140,5146]
db = Path.home() / ".config/movie-brain/movie-brain.db"
con = sqlite3.connect(db)
rows = con.execute(f"""
SELECT f.id, f.title, f.year,
       COALESCE(f.director, (SELECT group_concat(p.name, ', ') FROM film_credit fc JOIN person p ON p.id=fc.person_id
                             WHERE fc.film_id=f.id AND fc.kind='crew' AND fc.job='Director')),
       (SELECT value FROM external_ids WHERE film_id=f.id AND authority='imdb'),
       (SELECT value FROM external_ids WHERE film_id=f.id AND authority='tmdb')
FROM films f WHERE f.id IN ({','.join(map(str, IDS))}) ORDER BY f.id""").fetchall()

cc = CheapChartsClient()
tmdb = TmdbClient(load_tmdb_token(load_config()))
targets = {r[0]: ItunesTarget(r[0], r[1], r[2], r[3], r[4]) for r in rows}

print("== step 1 (rerun; see first log) ==")
by_imdb = {}
ids = [r[4] for r in rows if r[4]]
for i in range(0, len(ids), 5):
    by_imdb.update(cc.products_by_imdb(ids[i:i+5]))
for r in rows:
    p = by_imdb.get(r[4])
    print(f"  #{r[0]} {r[1]!r} ({r[2]}) {r[4]}: {'NO INDEX ENTRY' if p is None else f'{p.itunes_id} {p.title!r} ({p.year}) {p.director!r} removed={p.removed}'}")

print("\n== step 2: title search — catalog title, then TMDB title/original/alternatives (US/GB/en first, max 5) ==")
seen_calls = 0
for r in rows:
    t = targets[r[0]]
    names = [t.title]
    try:
        tt = tmdb.movie_titles(int(r[5])) if r[5] else None
    except Exception as e:
        tt = None; print(f"  (tmdb failed for #{r[0]}: {e})")
    if tt:
        for n in (tt.title, tt.original, *tt.alternatives):
            if n and n.casefold() not in {x.casefold() for x in names}:
                names.append(n)
    names = names[:6]
    print(f"\n#{t.film_id} {t.title!r} ({t.year}) dir={t.director!r} {t.imdb_id}  asking: {names}")
    for n in names:
        try:
            prods = cc.search(n)
        except RateLimited:
            print("  RATE LIMITED — stopping"); sys.exit(1)
        except Exception as e:
            print(f"  search {n!r} failed: {e}"); continue
        seen_calls += 1
        if not prods:
            print(f"  search {n!r}: nothing"); continue
        winner, verdict = _confirm(t, prods)
        summary = "; ".join(f"{p.itunes_id} {p.title!r} ({p.year}) {p.director!r}" for p in prods)
        print(f"  search {n!r}: {len(prods)} → {verdict}: {summary}")
        if winner is not None:
            try:
                why = _refusal(t, cc.filing(winner.itunes_id))
            except RateLimited:
                print("  RATE LIMITED — stopping"); sys.exit(1)
            print(f"    filing check on {winner.itunes_id}: {'CONFIRMED' if why is None else 'refused — ' + why}")
            break
print(f"\nsearch calls made: {seen_calls}")
