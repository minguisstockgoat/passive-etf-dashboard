"""One-time gap repair from date-specific official manager endpoints."""
import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from daily_changes import DATA,read,remember,sessions
import rebal_history as RH

def main():
    groups=defaultdict(list)
    for e in read(DATA/'etfs.json')['etfs']:
        current=read(DATA/'holdings'/(e['ticker']+'.json'),{})
        if not current.get('asof'):continue
        prior=RH.bday_shift(dt.date.fromisoformat(current['asof']),-1)
        dates={p['asof'] for p in read(DATA/'history'/(e['ticker']+'.json'),{'snapshots':[]})['snapshots']}
        if prior.isoformat() not in dates and e['manager'] in ('TIGER','RISE'):
            groups[e['manager']].append((e,prior))
    def group(job):
        manager,items=job;ok=0
        for e,prior in items:
            try:
                # RISE available_dates is checked before querying; TIGER uses its dated PDF endpoint.
                snap=RH.Source(e)._api(prior)
                if snap:
                    hs=[{'code':c,'name':h['n'],'shares':h['s'],'weight':h['w'],'amount':h['a']} for c,h in snap.items()]
                    remember(e['ticker'],{'asof':prior.isoformat(),'holdings':hs});ok+=1
                    print('PREVIOUS',manager,e['ticker'],prior,flush=True)
            except Exception as ex:print('PREVIOUS FAILED',manager,e['ticker'],type(ex).__name__,flush=True)
            time.sleep(1.5)
        return manager,ok,len(items)
    with ThreadPoolExecutor(max_workers=2) as pool:
        for r in pool.map(group,groups.items()):print('PREVIOUS TOTAL',r,flush=True)
if __name__=='__main__':main()
