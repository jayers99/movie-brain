import json,time,requests,sys,collections
S=sys.argv[1]; UA="movie-brain/0.1 (personal watchlist tool)"
cat={i['mediaid']:i for i in json.load(open(f"{S}/catalog.json"))}
r=json.load(open(f"{S}/redir.json")); m=json.load(open(f"{S}/match.json"))
used={x[6] for x in r if x[6]}; un=[x for x in m['miss'] if x[2] not in used]
s=requests.Session(); out=[]
for t,rd,mid in un:
    d=s.get(f"https://cdn.jwplayer.com/v2/media/{mid}",headers={"User-Agent":UA},timeout=30).json()['playlist'][0]
    out.append({k:d.get(k) for k in ('title','mediaid','release_date','director','license_start_date_time','license_end_date_time','criterion_id','title_original','contentType','pubdate')})
    time.sleep(0.3)
json.dump(out,open(f"{S}/unexpl.json","w"),indent=0)
c=collections.Counter((o['license_start_date_time'] or '')[:7] for o in out); print(sorted(c.items()))
print("no director:",sum(o['director'] in (None,'','[]') for o in out),"of",len(out))
