import json,sqlite3,collections,sys,os
from movie_brain.domain.models import film_key
S=sys.argv[1]
items=json.load(open(f"{S}/catalog.json"))
print("contentType", collections.Counter(i.get("contentType") for i in items))
dup=[m for m,c in collections.Counter(i['mediaid'] for i in items).items() if c>1]; print("dup mediaid",dup,[i['title'] for i in items if i['mediaid'] in dup])
print("release_date Jan-01 share", sum(i['release_date'].endswith('-01-01') for i in items if i.get('release_date')), "missing", sum(not i.get('release_date') for i in items))
films=[i for i in items if i.get("contentType")=="film"]
db=sqlite3.connect(os.path.expanduser("~/.config/movie-brain/movie-brain.db"))
rows=db.execute("select f.id,f.title,f.year,f.director,l.last_seen,l.url from films f join listings l on l.film_id=f.id and l.source='criterion'").fetchall()
cur=[r for r in rows if r[4]=='2026-09-20']
bykey=collections.defaultdict(list)
for r in rows: bykey[film_key(r[1],r[2])].append(r)
# also stored criterion external ids: titles via criterion claim? use film key
hit=[];miss=[];multi=[]
for i in films:
    y=int(i['release_date'][:4]) if i['release_date'][:2] in ('19','20') else None
    k=film_key(i['title'],y); m=bykey.get(k,[])
    (hit if len(m)==1 else multi if m else miss).append((i,m))
print("films",len(films),"key-hit",len(hit),"multi",len(multi),"miss",len(miss))
hitids={m[0][0] for _,m in hit}
gone=[r for r in cur if r[0] not in hitids]
print("db current (09-20)",len(cur),"not hit by new catalog",len(gone))
json.dump({"miss":[(i['title'],i['release_date'],i['mediaid']) for i,_ in miss],"gone":[(r[0],r[1],r[2],r[5]) for r in gone]},open(f"{S}/match.json","w"),indent=0)
for i,_ in miss[:25]: print("  MISS",i['title'],i['release_date'],i['mediaid'])
for r in gone[:25]: print("  GONE",r[0],r[1],r[2],r[5])
