"""Read-only: gather TMDB + OMDb candidate evidence for every eval case into a JSON cache."""
import csv, json, os, sys, time, requests
sys.path.insert(0,"src"); sys.path.insert(0,sys.argv[1]); SP=sys.argv[1]
from eval_lib import parse
from movie_brain.domain.matching import norm_title
CFG=os.path.expanduser("~/.config/movie-brain")
TOK=open(f"{CFG}/tmdb-read-token.txt").read().strip(); OK=open(f"{CFG}/omdb-api-key.txt").read().strip()
H={"Authorization":f"Bearer {TOK}"}
cf=f"{SP}/cand_cache.json"; cache=json.load(open(cf)) if os.path.exists(cf) else {}
n=0
def get(k,fn):
    global n
    if k in cache: return cache[k]
    for att in range(3):
        try: v=fn(); break
        except Exception as e:
            time.sleep(2); v={"error":str(e)}
    cache[k]=v; n+=1; time.sleep(0.04)
    if n%25==0: json.dump(cache,open(cf,"w"))
    return v
def tmdb_search(q,year=None):
    p={"query":q,"include_adult":"false"}
    if year: p["primary_release_year"]=str(year)
    return get(f"ts:{q}|{year}",lambda: requests.get("https://api.themoviedb.org/3/search/movie",params=p,headers=H,timeout=30).json().get("results",[])[:10])
def tmdb_detail(tid):
    return get(f"td:{tid}",lambda: requests.get(f"https://api.themoviedb.org/3/movie/{tid}",params={"append_to_response":"external_ids,credits,alternative_titles"},headers=H,timeout=30).json())
def omdb(**p):
    p["apikey"]=OK; k="o:"+json.dumps(p,sort_keys=True)
    return get(k,lambda: requests.get("https://www.omdbapi.com/",params=p,timeout=30).json())
rows=list(csv.DictReader(open(f"{SP}/eval_set_v1.csv")))
for i,r in enumerate(rows):
    raw=r["title_ingested"]; y=int(r["year_ingested"]) if r["year_ingested"] else None
    clean,eds,emb=parse(raw); yq=emb or y
    # current-behaviour inputs (raw title as persisted)
    tmdb_search(raw); tmdb_search(clean)
    if yq: tmdb_search(clean,yq); tmdb_search(raw,yq)
    omdb(t=raw,type="movie",**({"y":str(y)} if y else {}))       # current OmdbClient.lookup
    omdb(t=clean,type="movie",**({"y":str(yq)} if yq else {}))
    omdb(s=clean); 
    if yq: omdb(s=clean,y=str(yq))
    # details for plausible TMDB candidates (title-normalized hits, plus top 3)
    seen=set()
    for key in (f"ts:{raw}|None",f"ts:{clean}|None",f"ts:{clean}|{yq}",f"ts:{raw}|{yq}"):
        for j,cnd in enumerate(cache.get(key) or []):
            if isinstance(cnd,dict) and "id" in cnd and (j<3 or norm_title(cnd.get("title",""))==norm_title(clean) or norm_title(cnd.get("original_title",""))==norm_title(clean)) and cnd["id"] not in seen and len(seen)<6:
                seen.add(cnd["id"]); tmdb_detail(cnd["id"])
    # OMDb full records for s= candidates (top 6)
    ids=set()
    for key in (f"o:"+json.dumps({"s":clean,"apikey":OK},sort_keys=True), f"o:"+json.dumps({"s":clean,"y":str(yq),"apikey":OK},sort_keys=True)):
        for cnd in (cache.get(key) or {}).get("Search",[])[:6]: ids.add(cnd["imdbID"])
    for tid in seen:
        d=cache.get(f"td:{tid}") or {}; im=(d.get("external_ids") or {}).get("imdb_id")
        if im: ids.add(im)
    if r["expected_tt"] and r["expected_tt"]!="NONE": ids.add(r["expected_tt"])
    for im in ids: omdb(i=im)
    if i%25==0: print(i,n,file=sys.stderr); json.dump(cache,open(cf,"w"))
json.dump(cache,open(cf,"w")); print("done",n)
