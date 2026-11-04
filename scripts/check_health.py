"""Fail a run for stale source data, not just for transport errors."""
import datetime as dt
from daily_changes import DATA,KST,read,sessions

def main():
    d=read(DATA/'changes.json')
    today=dt.datetime.now(KST).date().isoformat()
    bad=[x for x in d['etfs'] if not x.get('latest_date') or x['latest_date']>today or sessions(x['latest_date'],today)>2]
    lag=sessions(d['market_asof'],today)
    failed=[k for k,v in read(DATA/'collection_status.json',{}).get('results',{}).items() if not v.get('ok')]
    print('SOURCE HEALTH',len(d['etfs']),'ETFs;',len(bad),'stale/missing;',len(failed),'collection failures; KRX lag',lag)
    if bad:print('Stale tickers:',','.join(x['ticker'] for x in bad))
    report=read(DATA/'impact/status.json',{})
    report_bad=not report.get('ok') or not report.get('as_of')
    if not report_bad:
        report_bad=report['as_of']>today or sessions(report['as_of'],today)>2
    print('IMPACT REPORT HEALTH', 'failed/stale' if report_bad else 'ok',report.get('as_of','unknown'))
    return int(bool(bad or failed or lag>2 or report_bad))
if __name__=='__main__':raise SystemExit(main())
