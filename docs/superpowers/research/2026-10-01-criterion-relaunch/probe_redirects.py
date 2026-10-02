import json,time,requests,sys,re
S=sys.argv[1]; UA="movie-brain/0.1 (personal watchlist tool)"
m=json.load(open(f"{S}/match.json")); s=requests.Session(); out=[]
for fid,title,year,url in m["gone"]:
    try:
        r=s.head(url,headers={"User-Agent":UA},allow_redirects=False,timeout=30)
        loc=r.headers.get("location","")
        mm=re.search(r"/films/([^/]+)/",loc)
        out.append((fid,title,year,url,r.status_code,loc,mm.group(1) if mm else None))
    except Exception as e: out.append((fid,title,year,url,None,str(e),None))
    time.sleep(0.4)
json.dump(out,open(f"{S}/redir.json","w"),indent=0)
import collections; print(collections.Counter((o[4], o[6] is not None) for o in out))
