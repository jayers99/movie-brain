import csv, json, os, sys, time, requests, sqlite3
sys.path.insert(0,"src"); sys.path.insert(0,sys.argv[1]); SP=sys.argv[1]
from eval_lib import parse, fold
from movie_brain.domain.matching import norm_title
CFG=os.path.expanduser("~/.config/movie-brain"); TOK=open(f"{CFG}/tmdb-read-token.txt").read().strip(); OK=open(f"{CFG}/omdb-api-key.txt").read().strip(); H={"Authorization":f"Bearer {TOK}"}
cf=f"{SP}/cand_cache.json"; cache=json.load(open(cf)); n=0
def get(k,fn):
    global n
    if k in cache: return cache[k]
    try: v=fn()
    except Exception as e: v={"error":str(e)}
    cache[k]=v; n+=1; time.sleep(0.04)
    if n%50==0: json.dump(cache,open(cf,"w"))
    return v
def detail(tid): return get(f"td:{tid}",lambda: requests.get(f"https://api.themoviedb.org/3/movie/{tid}",params={"append_to_response":"external_ids,credits,alternative_titles"},headers=H,timeout=30).json())
db=sqlite3.connect(f"file:{CFG}/movie-brain.db?mode=ro",uri=True)
rows=list(csv.DictReader(open(f"{SP}/eval_set_v1.csv")))
for i,r in enumerate(rows):
    raw=r["title_ingested"]; y=int(r["year_ingested"]) if r["year_ingested"] else None; t,eds,emb=parse(raw); yq=emb or y
    # (f) any-release-year search
    if yq:
        res=get(f"tsy:{t}|{yq}",lambda: requests.get("https://api.themoviedb.org/3/search/movie",params={"query":t,"year":str(yq),"include_adult":"false"},headers=H,timeout=30).json().get("results",[])[:10])
        for j,x in enumerate(res):
            if isinstance(x,dict) and "id" in x and (j<3 or norm_title(x.get("title",""))==norm_title(t) or norm_title(x.get("original_title",""))==norm_title(t)): detail(x["id"])
    # (e) director-credit search
    d=db.execute("select director from films where id=?",(r["film_id"],)).fetchone()[0] if r["film_id"] else None
    if d:
        for name in [s.strip() for s in d.replace(" and ",",").split(",") if s.strip()][:2]:
            ppl=get(f"person:{name}",lambda: requests.get("https://api.themoviedb.org/3/search/person",params={"query":name},headers=H,timeout=30).json().get("results",[])[:2])
            for p in ppl:
                if not isinstance(p,dict) or "id" not in p: continue
                cr=get(f"credits:{p['id']}",lambda: requests.get(f"https://api.themoviedb.org/3/person/{p['id']}/movie_credits",headers=H,timeout=30).json().get("crew",[]))
                for x in cr:
                    if x.get("job")=="Director" and (norm_title(x.get("title",""))==norm_title(t) or norm_title(x.get("original_title",""))==norm_title(t) or (yq and x.get("release_date","")[:4].isdigit() and abs(int(x["release_date"][:4])-yq)<=2 and norm_title(t) in norm_title(x.get("title","")+x.get("original_title","")))): detail(x["id"])
    # OMDb full records for any new tt
    for k,v in list(cache.items()):
        pass
    if i%50==0: print(i,n,file=sys.stderr)
# OMDb by id for every detail's imdb id not yet fetched
for k,v in list(cache.items()):
    if k.startswith("td:") and isinstance(v,dict):
        im=(v.get("external_ids") or {}).get("imdb_id")
        if im: get("o:"+json.dumps({"i":im,"apikey":OK},sort_keys=True),lambda: requests.get("https://www.omdbapi.com/",params={"i":im,"apikey":OK},timeout=30).json())
json.dump(cache,open(cf,"w")); print("done",n)
