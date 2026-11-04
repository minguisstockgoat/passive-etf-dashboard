#!/usr/bin/env python3
"""Publish report inputs; credentials stay local. No report generation needs a server/token.
KRX: five common completed sessions, actual turnover (never close*volume).
FnGuide: vendor float, not an index provider's rounded inclusion factor.
"""
from __future__ import annotations
import argparse, csv, datetime as dt, gzip, json, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from daily_changes import ROOT, DATA, KST, read, write
from krx_fetch import STOCK_URL, KOSDAQ_URL, _key
from run_daily import credentials

CACHE=ROOT/'scripts/.impact_cache'
SHORT=Path.home()/'short-dashboard/data'
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36'

def number(x):
    try:return float(str(x).replace(',',''))
    except (TypeError,ValueError):return None

def market_day(market, url, day):
    key=day.replace('-',''); p=CACHE/f'{market}_{key}.json.gz'
    for candidate in (p,SHORT/'raw/open_api'/p.name):
        if candidate.exists():
            try:
                with gzip.open(candidate,'rt') as f: rows=json.load(f)
                if len(rows)>500 and sum((number(x.get('MKTCAP')) or 0)>0 for x in rows)>500:return rows
            except (OSError,ValueError):pass
    response=requests.get(url,params={'basDd':key},headers={'AUTH_KEY':_key()},timeout=45)
    response.raise_for_status(); rows=response.json().get('OutBlock_1') or []
    if len(rows)<500 or sum((number(x.get('MKTCAP')) or 0)>0 for x in rows)<500:return []
    with gzip.open(p,'wt') as f:json.dump(rows,f,ensure_ascii=False)
    return rows

def float_one(code):
    time.sleep(.2)
    url=f'https://wcomp.fnguide.com/CompanyInfo/Snapshot?cmp_cd={code}'
    try:
        response=requests.get(url,headers={'User-Agent':UA,'Referer':'https://wcomp.fnguide.com/'},timeout=20)
        response.raise_for_status(); soup=BeautifulSoup(response.text,'html.parser')
        for el in soup(['script','style']):el.decompose()
        text=' '.join(soup.stripped_strings)
        m=re.search(r'유동주식수\s*/\s*비율\s*\(보통주\)\s*([\d,]+)\s*/\s*([\d.]+)',text)
        if not m:return None
        shares=int(m[1].replace(',',''));ratio=float(m[2])
        if not(0<ratio<=100 and shares>0):return None
        return {'code':code,'float_shares':shares,'float_ratio':ratio,'fetched_at':dt.datetime.now(KST).date().isoformat(),'source':url}
    except (requests.RequestException,ValueError):return None

def iso(x):
    x=str(x or '');return x[:4]+'-'+x[4:6]+'-'+x[6:8] if re.fullmatch(r'\d{8}',x) else x

def build(float_limit):
    credentials();CACHE.mkdir(parents=True,exist_ok=True)
    etfs=read(DATA/'etfs.json'); end=dt.date.fromisoformat(etfs['as_of'])
    sessions=[]; daily={};holidays=set(read(DATA/'holidays.json',{}).get('dates',[]))
    for offset in range(22):
        day=end-dt.timedelta(days=offset)
        if day.weekday()>=5 or day.isoformat() in holidays:continue
        key=day.isoformat()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(market_day,m,u,key) for m,u in [('KOSPI',STOCK_URL),('KOSDAQ',KOSDAQ_URL)]]
            markets=[f.result() for f in futures]
        if not all(markets):
            # A missing expected session is an outage, not permission to substitute an older session.
            raise RuntimeError(f'KRX common trading session unavailable: {key}')
        sessions.append(key);daily[key]=sum(markets,[])
        if len(sessions)==5:break
    if len(sessions)!=5:raise RuntimeError('Five complete KRX sessions unavailable')
    floats=read(CACHE/'float.json',{})
    if (SHORT/'free_float.csv').exists():
        for r in csv.DictReader((SHORT/'free_float.csv').open(encoding='utf-8-sig')):
            c=r['code'];d=iso(r['fetched_at'])
            if d>floats.get(c,{}).get('fetched_at',''):
                floats[c]={'code':c,'float_shares':number(r['float_shares']),'float_ratio':number(r['float_ratio']),'fetched_at':d,'source':f'https://wcomp.fnguide.com/CompanyInfo/Snapshot?cmp_cd={c}'}
    wanted=set()
    for e in etfs['etfs']:
        wanted.update(str(h['code']) for h in read(DATA/'holdings'/f"{e['ticker']}.json",{}).get('holdings',[]))
    current={str(r['ISU_CD']):r for r in daily[sessions[0]]}
    cutoff=(dt.datetime.now(KST).date()-dt.timedelta(days=7)).isoformat()
    todo=sorted(c for c in wanted&current.keys() if floats.get(c,{}).get('fetched_at','')<cutoff)[:float_limit]
    fetched=0
    print(f'Float refresh: {len(todo)} candidates',flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(float_one,c) for c in todo]):
            r=f.result()
            if r:
                floats[r['code']]=r;fetched+=1
                if fetched%50==0:print(f'Float refreshed: {fetched}',flush=True)
    write(CACHE/'float.json',floats)
    history={}
    for day in sorted(sessions):
        for r in daily[day]:
            c=str(r['ISU_CD']); value=number(r.get('ACC_TRDVAL'))
            history.setdefault(c,[]).append({'date':day,'value':value})
    stocks={}
    for code,r in current.items():
        bars=history[code];complete=len(bars)==5 and all(b['value'] is not None and b['value']>=0 for b in bars)
        f=floats.get(code,{})
        close=number(r.get('TDD_CLSPRC')); listed=number(r.get('LIST_SHRS'));fs=f.get('float_shares');fr=f.get('float_ratio')
        valid=bool(fs and listed and fr and 0<fs<=listed and 0<fr<=100 and abs(fs/listed*100-fr)<1)
        stocks[code]={'code':code,'name':r['ISU_NM'],'close':close,'market_cap':number(r.get('MKTCAP')),'listed_shares':listed,
            'turnover5':bars,'adtv5':sum(b['value'] for b in bars)/5 if complete else None,'price_date':sessions[0],
            'float_shares':fs if valid else None,'float_pct':fr if valid else None,'float_cap':fs*close if valid and close else None,
            'float_fetched_at':f.get('fetched_at'),'float_source':f.get('source'),
            'float_note':'FnGuide 보통주 유동주식수. 관측일은 수집일이며 주주변동 반영일·지수 편입계수와 다를 수 있음.'}
    payload={'schema':1,'generated_at':dt.datetime.now(KST).isoformat(timespec='seconds'),'as_of':sessions[0],'sessions':sorted(sessions),
      'sources':{'turnover':'https://data-dbg.krx.co.kr','float':'https://wcomp.fnguide.com'},'stocks':stocks,
      'coverage':{'held_stocks':len(wanted&current.keys()),'held_float':sum(bool(stocks[c]['float_cap']) for c in wanted&current.keys()),'float_refresh_ok':fetched,'float_refresh_attempted':len(todo)}}
    write(DATA/'impact/market.json',payload)
    write(DATA/'impact/status.json',{'ok':True,'as_of':sessions[0],'generated_at':payload['generated_at'],'coverage':payload['coverage']})
    print(json.dumps({'as_of':sessions[0],'sessions':sorted(sessions),**payload['coverage']},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--float-limit',type=int,default=120);a=p.parse_args()
    try:build(a.float_limit)
    except Exception as e:
        write(DATA/'impact/status.json',{'ok':False,'checked_at':dt.datetime.now(KST).isoformat(timespec='seconds'),'error':type(e).__name__,'note':'직전 자료 보존. 보고서 기준일 확인 필요.'})
        raise
