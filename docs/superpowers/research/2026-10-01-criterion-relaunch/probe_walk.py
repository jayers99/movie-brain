import json,time,requests,sys
S=sys.argv[1]; UA="movie-brain/0.1 (personal watchlist tool)"
s=requests.Session(); items=[]; key=None; calls=0
while True:
    p={"page_limit":200}
    if key: p["pagination_key"]=key
    r=s.get("https://www.criterionchannel.com/api/all-films/results",params=p,headers={"User-Agent":UA},timeout=30); calls+=1
    r.raise_for_status(); d=r.json(); items+=d["items"]; key=(d.get("paging") or {}).get("next_pagination_key")
    if not key: break
    time.sleep(1)
json.dump(items,open(f"{S}/catalog.json","w"))
print(calls,"calls",len(items),"items total",d["total"], "unique mediaid",len({i['mediaid'] for i in items}))
