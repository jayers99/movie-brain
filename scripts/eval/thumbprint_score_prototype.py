import csv, json, os, sys, re, difflib
sys.path.insert(0,"src"); sys.path.insert(0,sys.argv[1]); SP=sys.argv[1]
from eval_lib import parse, surnames, fold
from movie_brain.domain.matching import norm_title, parse_apple_title, clean_title, pick_tmdb_match
from movie_brain.domain.models import TmdbCandidate
CFG=os.path.expanduser("~/.config/movie-brain"); OK=open(f"{CFG}/omdb-api-key.txt").read().strip()
C=json.load(open(f"{SP}/cand_cache.json"))
def ts(q,y=None): return [x for x in (C.get(f"ts:{q}|{y}") or []) if isinstance(x,dict) and "id" in x]
def td(i): return C.get(f"td:{i}") or {}
def ok(**p): p["apikey"]=OK; return C.get("o:"+json.dumps(p,sort_keys=True)) or {}
def yr(d): 
    try: return int((d.get("release_date") or "")[:4])
    except: return None
def oyear(o):
    m=re.match(r"\d{4}",o.get("Year") or ""); return int(m.group()) if m else None
def votes(o):
    try: return int((o.get("imdbVotes") or "0").replace(",",""))
    except: return 0
def rt(s):
    m=re.search(r"(\d+)\s*min",s or ""); return int(m.group(1)) if m else None
JUNK=re.compile(r"\bmaking\b|bande-annonce|trailer|q&a|\bpanel\b|behind the scenes|a look at|featurette|sing-along|timelapse|\bw/\b|on pov|\breviews?\b|the journey to|podcast",re.I)
def directors_tmdb(d): return ", ".join(x["name"] for x in (d.get("credits") or {}).get("crew",[]) if x.get("job")=="Director")
def titles_tmdb(d): return [d.get("title",""),d.get("original_title","")]+[a["title"] for a in (d.get("alternative_titles") or {}).get("titles",[])]
def sim(a,b): return difflib.SequenceMatcher(None,norm_title(a),norm_title(b)).ratio()
# ---------- ALG0: current pipeline ----------
def alg0(r):
    raw=r["title_ingested"]; y=int(r["year_ingested"]) if r["year_ingested"] else None; src=r["source"]
    if src=="apple": t,emb=parse_apple_title(raw); yq=emb or y; commerce=emb is None
    elif src=="metacritic": t=clean_title(raw); yq=y; commerce=True
    else: t=raw; yq=y; commerce=False
    page=ts(t) if commerce else ts(t)+[x for x in ts(t,yq) if x["id"] not in {p["id"] for p in ts(t)}] if (yq and not any(yr(x) and abs(yr(x)-yq)<=1 for x in ts(t))) else ts(t)
    cands=[TmdbCandidate(tmdb_id=x["id"],title=x.get("title",""),original_title=x.get("original_title",""),year=yr(x),popularity=x.get("popularity",0.0)) for x in page]
    def arbiter(title,claimed): return any(c.year and abs(c.year-claimed)<=1 for c in cands)
    w=pick_tmdb_match(t,yq,cands,commerce_year=commerce,arbiter=arbiter if commerce else None)
    if w: return ("match",(td(w).get("external_ids") or {}).get("imdb_id") or f"tmdb:{w}","tmdb")
    o=ok(t=t,type="movie",**({"y":str(yq)} if yq else {})) if t in (raw,) or src!="apple" else ok(t=raw,type="movie",**({"y":str(y)} if y else {}))
    if o.get("Response")=="True": return ("match",o["imdbID"],"omdb t=")
    return ("review",None,"no-match")
# ---------- shared candidate pool ----------
def pool(r):
    raw=r["title_ingested"]; y=int(r["year_ingested"]) if r["year_ingested"] else None; src=r["source"]
    t,eds,emb=parse(raw); yq=emb or y
    year_kind="database" if (src in("criterion","benchmark") or emb) else ("mc" if src=="metacritic" else "apple-field")
    seen={}; 
    for x in ts(t)+ts(t,yq):
        d=td(x["id"]); tt=(d.get("external_ids") or {}).get("imdb_id")
        if not tt: continue
        c=seen.setdefault(tt,dict(tt=tt,tmdb=x["id"],titles=[],year=None,director="",runtime=None,votes=0,in_tmdb=False,in_omdb=False,otype="movie",otitle=""))
        c["in_tmdb"]=True; c["titles"]+=titles_tmdb(d); c["year"]=yr(d); c["director"]=directors_tmdb(d); c["runtime"]=d.get("runtime")
    for key in (dict(s=t),dict(s=t,y=str(yq)) if yq else None):
        if not key: continue
        for x in ok(**key).get("Search",[]):
            o=ok(i=x["imdbID"])
            if not o.get("imdbID"): continue
            c=seen.setdefault(o["imdbID"],dict(tt=o["imdbID"],tmdb=None,titles=[],year=None,director="",runtime=None,votes=0,in_tmdb=False,in_omdb=False,otype="movie",otitle=""))
            c["in_omdb"]=True; c["titles"].append(o.get("Title","")); c["otitle"]=o.get("Title",""); c["otype"]=o.get("Type","movie")
            c["year"]=c["year"] or oyear(o); c["director"]=c["director"] or (o.get("Director") if o.get("Director")!="N/A" else ""); c["runtime"]=c["runtime"] or rt(o.get("Runtime")); c["votes"]=votes(o)
    for c in seen.values():
        o=ok(i=c["tt"]); 
        if o.get("imdbID"): c["votes"]=votes(o); c["otitle"]=o.get("Title",""); c["otype"]=o.get("Type","movie"); c["director"]=c["director"] or (o.get("Director") if o.get("Director")!="N/A" else ""); c["runtime"]=c["runtime"] or rt(o.get("Runtime"))
    return dict(t=t,eds=eds,yq=yq,year_kind=year_kind,src=src,cands=list(seen.values()),crit_director=r.get("_director") or "")
# ---------- ALG1: seed evidence order ----------
def title_level(t,c):
    nt=norm_title(t)
    if any(norm_title(x)==nt for x in c["titles"] if x): return 3
    if any(norm_title(x).startswith(nt) and len(nt)>=8 for x in c["titles"] if x): return 2   # official longer title
    return 1 if max((sim(t,x) for x in c["titles"] if x),default=0)>=0.85 else 0
def year_ok(p,c):
    y=p["yq"]; cy=c["year"]
    if y is None or cy is None: return True, 0
    if abs(cy-y)<=1: return True, 2
    if abs(cy-y)<=2: return True, 1
    if p["year_kind"]=="commerce" and cy<y: return (True,0) if p["eds"] else (False,0)
    return False,0
def alg1(r,strict=False):
    p=pool(r); surv=[]
    for c in p["cands"]:
        lvl=title_level(p["t"],c)
        if lvl==0: continue
        if JUNK.search(c["otitle"] or "") and not JUNK.search(p["t"]): continue
        if c["otype"] not in ("movie",""): continue
        okk,yp=year_ok(p,c)
        if not okk: continue
        s=lvl+yp+(1 if c["in_tmdb"] and c["in_omdb"] else 0)
        surv.append((s,c,lvl,yp))
    if not surv: return ("review",None,"no candidates")
    surv.sort(key=lambda x:-x[0]); top=surv[0]; rest=[s for s in surv[1:] if s[2]>=2]
    # completeness/votes as the between-candidate comparison for near-ties
    if rest and rest[0][0]>=top[0]-1:
        vt=[s for s in surv if s[2]>=2 and s[3]>=1]
        if len(vt)==1: return ("match",vt[0][1]["tt"],"only exact-year survivor")
        best=max(surv,key=lambda s:s[1]["votes"]); second=sorted(surv,key=lambda s:-s[1]["votes"])[1]
        if best[1]["votes"]>=1000 and best[1]["votes"]>=20*max(1,second[1]["votes"]) and best[2]>=2: return ("match",best[1]["tt"],"votes dominate")
        return ("review",None,"ambiguous")
    if top[2]==3 and (top[3]>=1 or (top[1]["in_tmdb"] and top[1]["in_omdb"])): return ("match",top[1]["tt"],"exact title + year/agreement")
    if top[2]==2 and top[3]>=1 and top[1]["in_tmdb"] and top[1]["in_omdb"]: return ("match",top[1]["tt"],"longer official title + year + agreement")
    return ("review",None,"weak")
# ---------- ALG2: + director/runtime corroboration, generic-title hazard ----------
def alg2(r):
    p=pool(r); cd=surnames(p["crit_director"]); surv=[]; conflicts=0
    for c in p["cands"]:
        lvl=title_level(p["t"],c)
        if lvl==0: continue
        if JUNK.search(c["otitle"] or "") and not JUNK.search(p["t"]): continue
        if c["otype"] not in ("movie",""): continue
        okk,yp=year_ok(p,c)
        if not okk: continue
        dm=0
        if cd and c["director"]:
            if cd&surnames(c["director"]): dm=3
            else: conflicts+=1; continue
        s=lvl+yp+dm+(1 if c["in_tmdb"] and c["in_omdb"] else 0)
        surv.append((s,c,lvl,yp,dm))
    if not surv: return ("review",None,"no candidates" if not conflicts else "director conflicts only")
    surv.sort(key=lambda x:-x[0]); top=surv[0]; rest=[s for s in surv[1:] if s[2]>=2]
    if top[4]==3 and top[2]>=2 and not any(s[4]==3 for s in rest): return ("match",top[1]["tt"],"director corroborated")
    generic=len(p["t"].split())<=2 and not cd
    # rerelease-ambiguous (Metropolis / Boston Strangler): a COMMERCE year sits exactly on one exact-title film while an OLDER exact-title film also survives -> never guess
    if p["year_kind"] in("commerce","mc","apple-field") and top[2]==3 and top[3]==2 and any(s[2]==3 and s[1]["year"] and s[1]["year"]<p["yq"]-2 for s in surv[1:]) and top[4]!=3:
        return ("review",None,"rerelease-ambiguous")
    if rest and rest[0][0]>=top[0]-1:
        vt=[s for s in surv if s[2]>=2 and s[3]>=1]
        if len(vt)==1 and not generic: return ("match",vt[0][1]["tt"],"only exact-year survivor")
        best=max(surv,key=lambda s:s[1]["votes"]); second=sorted(surv,key=lambda s:-s[1]["votes"])[1]
        if best[1]["votes"]>=1000 and best[1]["votes"]>=20*max(1,second[1]["votes"]) and best[2]>=2 and best[3]>=1: return ("match",best[1]["tt"],"votes dominate")
        return ("review",None,"ambiguous")
    if top[2]==3 and top[3]>=1 and (top[1]["in_tmdb"] and top[1]["in_omdb"] or top[1]["votes"]>=1000 or not generic): return ("match",top[1]["tt"],"exact title + year (+agreement)")
    if top[2]==3 and top[1]["in_tmdb"] and top[1]["in_omdb"] and p["yq"] is None: return ("match",top[1]["tt"],"dateless: exact + agreement")
    if top[2]==2 and top[3]>=1 and top[1]["in_tmdb"] and top[1]["in_omdb"]: return ("match",top[1]["tt"],"longer official title")
    return ("review",None,"weak")
APPLE_RT={}
for fn in ("owned-2026-08-23.txt","owned-2026-08-24.txt"):
    for line in open(f"{CFG}/appletv/{fn}"):
        p=line.rstrip("\n").split("\t")
        if len(p)>=3:
            try: APPLE_RT[p[0]]=round(float(p[2])/60)
            except: pass
# ---------- ALG3: ALG2 + name-token directors, exact-beats-prefix, commerce-gap policy, credit search, year= search ----------
def name_tokens(s):
    return {t for n in re.split(r",| and |&",fold(s or "").replace("n/a","")) for t in re.split(r"[\s.\-']+",n) if len(t)>=3}
def dir_match(a,b):
    ta,tb=name_tokens(a),name_tokens(b)
    if not ta or not tb: return None
    common=ta&tb
    return len(common)>=2 or (len(common)==1 and (len(ta)<=2 or len(tb)<=2))
def pool3(r):
    p=pool(r); t=p["t"]; yq=p["yq"]; seen={c["tt"]:c for c in p["cands"]}
    extra=list(C.get(f"tsy:{t}|{yq}") or [])
    d=p["crit_director"]
    if d:
        for name in [s.strip() for s in d.replace(" and ",",").split(",") if s.strip()][:2]:
            for per in (C.get(f"person:{name}") or []):
                if isinstance(per,dict) and "id" in per:
                    extra+=[x for x in (C.get(f"credits:{per['id']}") or []) if x.get("job")=="Director"]
    for x in extra:
        if not isinstance(x,dict) or "id" not in x: continue
        dd=td(x["id"]); tt=(dd.get("external_ids") or {}).get("imdb_id")
        if not tt or tt in seen: continue
        c=dict(tt=tt,tmdb=x["id"],titles=titles_tmdb(dd),year=yr(dd),director=directors_tmdb(dd),runtime=dd.get("runtime"),votes=0,in_tmdb=True,in_omdb=False,otype="movie",otitle="")
        o=ok(i=tt)
        if o.get("imdbID"): c["votes"]=votes(o); c["otitle"]=o.get("Title",""); c["otype"]=o.get("Type","movie")
        seen[tt]=c
    p["cands"]=list(seen.values()); return p
def alg3(r,use_runtime=False):
    p=pool3(r); cd=p["crit_director"]; surv=[]; conflicts=0
    qrt=APPLE_RT.get(r["title_ingested"]) if (use_runtime and r["source"]=="apple") else None
    for c in p["cands"]:
        lvl=title_level(p["t"],c)
        if lvl==0: continue
        if JUNK.search(c["otitle"] or "") and not JUNK.search(p["t"]): continue
        dm=0
        if cd and c["director"]:
            m=dir_match(cd,c["director"])
            if m: dm=3
            elif m is False: conflicts+=1; continue
        if c["otype"] not in ("movie","") and dm!=3: continue
        y=p["yq"]; cy=c["year"]; yp=0; older=False
        if y is not None and cy is not None:
            if abs(cy-y)<=1: yp=2
            elif abs(cy-y)<=2: yp=1
            elif dm==3: yp=0                                          # director match: year is not the decider
            elif p["year_kind"] in("mc","apple-field") and cy<y: older=True     # commerce/edition year trails the original: neutral, not evidence
            else: continue
        agree=c["in_tmdb"] and c["in_omdb"]
        rm=0
        if qrt and c["runtime"]:
            d_rt=abs(qrt-c["runtime"])
            if d_rt<=max(3,0.05*c["runtime"]): rm=2
            elif d_rt>0.15*c["runtime"]: continue          # runtime conflict disqualifies
        surv.append(dict(s=lvl+yp+dm+rm+(1 if agree else 0),c=c,lvl=lvl,yp=yp,dm=dm,rm=rm,older=older,agree=agree))
    if not surv: return ("review",None,"no candidates" if not conflicts else "director conflicts only")
    exact=[s for s in surv if s["lvl"]==3]
    if exact: surv=exact                                   # exact title beats longer-official-title candidates outright
    surv.sort(key=lambda s:-s["s"]); top=surv[0]
    dirhits=[s for s in surv if s["dm"]==3]
    if len(dirhits)==1 and dirhits[0]["lvl"]>=2: return ("match",dirhits[0]["c"]["tt"],"director corroborated")
    if len(dirhits)>1:
        strong=[s for s in dirhits if s["agree"] or s["c"]["votes"]>=100]
        if len(strong)==1 and strong[0]["lvl"]>=2: return ("match",strong[0]["c"]["tt"],"director corroborated (one keyed/voted entry among duplicates)")
        return ("review",None,"ambiguous (several director hits)")
    generic=len(p["t"].split())<=2 and not cd
    def dominant(cands):
        vs=sorted(cands,key=lambda s:-s["c"]["votes"])
        return vs[0] if vs[0]["c"]["votes"]>=1000 and (len(vs)==1 or vs[0]["c"]["votes"]>=20*max(1,vs[1]["c"]["votes"])) else None
    near=[s for s in surv if s["yp"]>=1]; old=[s for s in surv if s["older"]]
    rthits=[s for s in surv if s["rm"]==2 and s["lvl"]==3]
    if qrt and len(rthits)==1 and len([s for s in surv if s["lvl"]==3])==1 and (rthits[0]["yp"]>=1 or rthits[0]["older"] or rthits[0]["agree"]):
        return ("match",rthits[0]["c"]["tt"],"runtime corroborated (rivals runtime-disqualified)")
    # an OMDb-only, vote-less entry duplicating a TMDB-keyed candidate at the same title+year is an IMDb duplicate, not a rival
    keyed_years={s["c"]["year"] for s in surv if s["c"]["in_tmdb"]}
    surv=[s for s in surv if not (not s["c"]["in_tmdb"] and s["c"]["votes"]<10 and s["c"]["year"] in keyed_years)]
    near=[s for s in surv if s["yp"]>=1]; old=[s for s in surv if s["older"]]
    near1=[s for s in near if s["yp"]==2]
    if old and ((p["year_kind"]=="apple-field" and near) or (p["year_kind"]=="mc" and near and not near1) or (p["eds"] and near)):
        # an EXACT-title film sits near the claimed year AND an older exact-title film exists. Apple field years are remaster-prone and
        # edition years are edition years -> never guess (Boston Strangler / Metropolis). An MC year is the page's own film unless it only lands at +-2.
        return ("review",None,"rerelease-ambiguous")
    if near:
        if len(near)==1 and (near[0]["agree"] or near[0]["c"]["votes"]>=1000 or (not generic and near[0]["yp"]==2)): return ("match",near[0]["c"]["tt"],"exact title + year"+(" + agreement" if near[0]["agree"] else ""))
        d=dominant(near)
        if d: return ("match",d["c"]["tt"],"votes dominate among year-near exact titles")
        return ("review",None,"ambiguous")
    if old and p["year_kind"] in("mc","apple-field"):
        # nothing at the claimed year: the claimed year is a re-release/commerce date
        if len(old)==1 and old[0]["agree"]: return ("match",old[0]["c"]["tt"],"unique older exact title (commerce year = re-release)")
        d=dominant(old)
        if d and d["agree"]: return ("match",d["c"]["tt"],"votes dominate among older exact titles")
        return ("review",None,"ambiguous (older candidates)")
    if p["yq"] is None and len(surv)==1 and top["agree"] and not generic: return ("match",top["c"]["tt"],"dateless: unique exact + agreement")
    if top["lvl"]==2 and top["yp"]>=1 and top["agree"]: return ("match",top["c"]["tt"],"longer official title + year + agreement")
    return ("review",None,"weak")

# ---------- run ----------
import sqlite3
db=sqlite3.connect(f"file:{CFG}/movie-brain.db?mode=ro",uri=True)
rows=list(csv.DictReader(open(f"{SP}/eval_set_v1.csv")))
for r in rows:
    r["_director"]=db.execute("select director from films where id=?",(r["film_id"],)).fetchone()[0] if r["film_id"] else None
only=sys.argv[2] if len(sys.argv)>2 else None
ALGS={"ALG0 current":alg0,"ALG1 seed order":alg1,"ALG2 seed+director+hazard":alg2,"ALG3 +names/commerce-gap/credits":alg3,"ALG4 ALG3+apple runtime":lambda r: alg3(r,use_runtime=True)}
from collections import Counter, defaultdict
report={}
for name,fn in ALGS.items():
    tally=Counter(); wrong=[]; reviews=defaultdict(list); bygroup=defaultdict(Counter)
    for r in rows:
        if not r["expected_tt"]: continue   # unresolved cases skipped
        if only and r["status"]!=only and r["status"]!="verified": continue
        exp=r["expected_tt"]; kind,tt,why=fn(r)
        if kind=="match": res="correct" if tt==exp else "WRONG"
        else: res="review-none-ok" if exp=="NONE" else "review"
        tally[res]+=1; bygroup[r["group"][:12]][res]+=1
        if res=="WRONG": wrong.append((r["group"][:6],r["source"],r["title_ingested"],r["year_ingested"],"exp",exp,"got",tt,why,r["status"]))
        elif res=="review": reviews[why].append(r["title_ingested"])
    n=sum(tally.values()); print(f"\n=== {name}  n={n}  WRONG={tally['WRONG']}  auto-correct={tally['correct']} ({100*tally['correct']/n:.1f}%)  review={tally['review']+tally['review-none-ok']} ({100*(tally['review']+tally['review-none-ok'])/n:.1f}%)")
    for g,t in sorted(bygroup.items()): print(f"   {g:14} {dict(t)}")
    print("   review reasons:",{k:len(v) for k,v in reviews.items()})
    for w in wrong: print("   WRONG:",w)
    report[name]=dict(tally=dict(tally),wrong=wrong,reviews={k:v for k,v in reviews.items()})
    if name.startswith("ALG4"):
        print("   --- review cases (ALG2) ---")
        for r in rows:
            if not r["expected_tt"]: continue
            kind,tt,why=fn(r)
            if kind=="review" and r["expected_tt"]!="NONE":
                p=pool(r); cs=sorted(p["cands"],key=lambda c:-(c["votes"]))[:3]
                print(f"     [{why}] {r['group'][:6]} {r['source'][:4]} {r['title_ingested']!r} {r['year_ingested']} exp={r['expected_tt']} dir={p['crit_director']!r} :: "+" | ".join(f"{c['tt']} {c['titles'][0][:28]!r} {c['year']} {c['director'][:18]!r} v={c['votes']}{' T' if c['in_tmdb'] else ''}{' O' if c['in_omdb'] else ''}" for c in cs))
        vt=Counter()
        for r in rows:
            if not r["expected_tt"]: continue
            kind,tt,why=fn(r); res="correct" if kind=="match" and tt==r["expected_tt"] else "WRONG" if kind=="match" else "review"
            vt[(r["status"],res)]+=1
        print("   by status:",dict(vt))
json.dump(report,open(f"{SP}/score_report.json","w"),indent=1,ensure_ascii=False)

