"""Verified daily snapshots + change analysis shared with scheduled rebalance history.
Source dates, collection times and market dates are intentionally kept separate.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import sqlite3
import subprocess
from pathlib import Path
from collections import Counter
import rebal_history as RH
import kr_holidays as KH

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
KST = dt.timezone(dt.timedelta(hours=9))

def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    tmp.replace(path)

def sessions(a, b):
    holidays = KH.load()
    d, n = dt.date.fromisoformat(a), 0
    end = dt.date.fromisoformat(b)
    while d < end:
        d += dt.timedelta(days=1)
        n += d.weekday() < 5 and d not in holidays
    return n

def remember(ticker, payload):
    date = payload.get('asof', '')
    try: dt.date.fromisoformat(date)
    except (ValueError, TypeError): return False
    if not payload.get('holdings'): return False
    p = DATA / 'history' / (ticker + '.json')
    data = read(p, {'ticker':ticker, 'snapshots':[]})
    by_date = {x['asof']:x for x in data['snapshots']}
    by_date[date] = {'asof':date,'holdings':[
        {k:h.get(k) for k in ('code','name','weight','shares','amount')}
        for h in payload['holdings']]}
    data['snapshots'] = [by_date[d] for d in sorted(by_date)[-32:]]
    write(p, data)
    return True

def capture():
    for p in (DATA/'holdings').glob('*.json'):
        remember(p.stem, read(p))

def seed_git():
    # Read actual historical files; never label a current response as a past day.
    commits = subprocess.check_output(['git','log','-12','--format=%H'],cwd=ROOT,text=True).split()
    for sha in reversed(commits):
        names = subprocess.check_output(['git','ls-tree','-r','--name-only',sha,'data/holdings'],cwd=ROOT,text=True).splitlines()
        for name in names:
            if not name.endswith('.json'): continue
            raw = subprocess.check_output(['git','show',f'{sha}:{name}'],cwd=ROOT)
            remember(Path(name).stem, json.loads(raw))
    capture()

def seed_legacy(path):
    conn = sqlite3.connect('file:'+str(Path(path).resolve())+'?mode=ro',uri=True)
    conn.row_factory = sqlite3.Row
    for e in conn.execute('select etf_id,ticker from etfs'):
        rows = conn.execute('select distinct base_date from snapshots where etf_id=? order by base_date desc limit 32',(e['etf_id'],)).fetchall()
        for row in reversed(rows):
            d = row['base_date']
            hs = conn.execute('select * from snapshots where etf_id=? and base_date=?',(e['etf_id'],d))
            remember(e['ticker'],{'asof':f'{d[:4]}-{d[4:6]}-{d[6:]}','holdings':[
                {'code':h['stock_code'],'name':h['stock_name'],'weight':h['weight'],
                 'shares':h['shares'],'amount':h['amount']} for h in hs]})
    conn.close()

def compare(previous, current, cap=None, aum=0):
    a,b = RH.to_snap(previous['holdings']),RH.to_snap(current['holdings'])
    if not a or not b: return None
    result=RH.diff(a,b,cap,aum)
    changes={x['c']:x for x in result['items']}
    rows=[]
    for c in sorted(set(a)|set(b),key=lambda c:-(b.get(c) or a[c])['w']):
        x,y=a.get(c),b.get(c)
        it=changes.get(c,{})
        rows.append({'code':c,'name':(y or x)['n'],'weight':y['w'] if y else 0,
          'weight_prev':x['w'] if x else 0,'weight_delta':round((y['w'] if y else 0)-(x['w'] if x else 0),4),
          'shares':y['s'] if y else 0,'shares_prev':x['s'] if x else 0,
          'shares_delta':round((y['s'] if y else 0)-(x['s'] if x else 0),4),
          'kind':it.get('t','same'),'trade_pp':it.get('tr',0)})
    return {'summary':result['sum'],'rows':rows}

def build():
    capture()
    meta=read(DATA/'etfs.json')
    today=dt.datetime.now(KST).date().isoformat()
    results=[]
    collection=read(DATA/'collection_status.json',{})
    for e in meta['etfs']:
        current=read(DATA/'holdings'/(e['ticker']+'.json'),{})
        history=read(DATA/'history'/(e['ticker']+'.json'),{'snapshots':[]})['snapshots']
        latest=current.get('asof')
        valid=bool(latest and current.get('holdings'))
        prior=[p for p in history if valid and p['asof']<latest]
        prev=prior[-1] if prior else None
        lag=sessions(latest,today) if valid else None
        future=valid and latest>today
        gap=sessions(prev['asof'],latest) if prev else None
        status='missing' if not valid else ('future' if future else ('stale' if lag>2 else ('lagging' if lag>1 else 'current')))
        comp=compare(prev,current,e.get('cap'),0) if prev and valid and not future else None
        record={'ticker':e['ticker'],'name':e['name'],'manager':e['manager'],
          'watchlist':bool(e.get('watchlist')),'latest_date':latest,
          'prev_date':prev['asof'] if prev else None,'gap_sessions':gap,'lag_sessions':lag,'status':status,
          'daily_comparable':bool(comp and gap==1 and status=='current'),
          'available_dates':[p['asof'] for p in history],
          'summary':comp['summary'] if comp else None,
          'rows':comp['rows'] if comp else [],
          'collection':collection.get('results',{}).get(e['ticker'])}
        write(DATA/'changes'/(e['ticker']+'.json'),record)
        results.append({k:v for k,v in record.items() if k not in ('rows','available_dates')})
    counts=Counter(r['status'] for r in results)
    payload={'generated_at':dt.datetime.now(KST).isoformat(timespec='seconds'),
      'as_of':today,'market_asof':meta['as_of'],'counts':dict(counts),'etfs':results,
      'method':'직전 관측일 대비 CU 수량·비중 변화. 가격효과와 단위변경을 보정한 추정이며 실제 체결 확정이 아님.'}
    write(DATA/'changes.json',payload)
    print('Daily changes:',dict(counts),'daily comparable',sum(r['daily_comparable'] for r in results))
    return payload

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seed-git',action='store_true');p.add_argument('--legacy-db');a=p.parse_args()
    if a.legacy_db:seed_legacy(a.legacy_db)
    if a.seed_git:seed_git()
    build()
