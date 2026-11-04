"""One domestic collector, serial per manager and parallel across managers."""
from __future__ import annotations
import datetime as dt
import math
import time
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import fetch_holdings as FH
from daily_changes import DATA,KST,read,write,remember


def valid(payload, previous, today):
    if not payload or not payload.get('holdings'):return 'empty'
    try:day=dt.date.fromisoformat(payload.get('asof',''))
    except (TypeError,ValueError):return 'invalid_source_date'
    if day>today:return 'future_source_date'
    if previous.get('asof','')>day.isoformat():return 'source_date_regressed'
    hs=payload['holdings']
    if any(not math.isfinite(float(h.get('weight') or 0)) for h in hs):return 'invalid_weight'
    weight=sum(float(h.get('weight') or 0) for h in hs)
    if weight<60 or weight>220:return 'incomplete_weights'
    if len(previous.get('holdings',[]))>10 and len(hs)<len(previous['holdings'])*.5:return 'holdings_count_collapsed'
    return None


def main():
    meta=read(DATA/'etfs.json')
    groups=defaultdict(list)
    for e in meta['etfs']:groups[e['manager']].append(e)
    today=dt.datetime.now(KST).date()
    def group(job):
        manager,etfs=job;out={};consecutive=0
        for e in etfs:
            t=e['ticker'];path=DATA/'holdings'/(t+'.json');prev=read(path,{})
            if consecutive>=3:
                out[t]={'ok':False,'reason':'manager_circuit_open','source_date':prev.get('asof')};continue
            payload=FH.fetch_one(e)
            reason=valid(payload,prev,today)
            if reason:
                time.sleep(3)
                payload=FH.fetch_one(e);reason=valid(payload,prev,today)
            if reason:
                consecutive+=1;out[t]={'ok':False,'reason':reason,'source_date':prev.get('asof')}
                print('FAILED',manager,t,reason,flush=True)
            else:
                remember(t,prev);remember(t,payload);write(path,payload)
                consecutive=0;out[t]={'ok':True,'source_date':payload['asof']}
                print('OK',manager,t,payload['asof'],flush=True)
            time.sleep(1.2)
        return out
    results={}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(group,groups.items()):results.update(result)
    write(DATA/'collection_status.json',{'checked_at':dt.datetime.now(KST).isoformat(timespec='seconds'),'results':results})
    print('COLLECTION',sum(v['ok'] for v in results.values()),'/',len(results),flush=True)
    return results

if __name__=='__main__':main()
