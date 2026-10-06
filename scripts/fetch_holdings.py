# -*- coding: utf-8 -*-
"""
운용사별 최신 구성종목(PDF) 수집 → data/holdings/{ticker}.json.

운용사별 fetcher 를 공통 인터페이스로 감싼다. 지원 운용사는 아래 DISPATCH 참고.
아직 엔드포인트 미확보 운용사는 자동 건너뜀(대시보드에서 '구성종목 준비중' 표시).

data/holdings/{ticker}.json:
  { ticker, name, manager, source, asof, total_weight,
    holdings: [ {code, name, weight, shares, amount} ] }
"""
from __future__ import annotations
import os, sys, json, datetime as dt

sys.stdout.reconfigure(encoding="utf-8")
import urllib3
urllib3.disable_warnings()

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
HOLD = os.path.join(DATA, "holdings")

from fetchers import (TigerFetcher, SolFetcher, RiseFetcher,
                      KodexFetcher, KiwoomFetcher, AceFetcher,
                      PlusFetcher, HanaroFetcher, Holding)

# 지연 초기화 캐시
_tiger = _sol = _rise = _kodex = _kiwoom = None
_ace = _plus = _hanaro = None
_sol_map = None   # ticker6 -> FUND_CD
_rise_cache = {}  # ticker -> kbam fund_cd

# 해외 IP 에서 막히는 운용사(TIGER 403·KB 접속불가). GitHub Actions 는 SKIP_MANAGERS=TIGER,RISE
# 로 건너뛰고(기존 파일 유지), 국내 PC(Mac mini)의 local_refresh.py 가 따로 채운다.
SKIP = {m.strip().upper() for m in os.environ.get("SKIP_MANAGERS", "").split(",") if m.strip()}


def tiger():
    global _tiger
    if _tiger is None:
        _tiger = TigerFetcher()
    return _tiger


def sol():
    global _sol
    if _sol is None:
        _sol = SolFetcher()
    return _sol


def rise():
    global _rise
    if _rise is None:
        _rise = RiseFetcher()
    return _rise


def kodex():
    global _kodex
    if _kodex is None:
        _kodex = KodexFetcher()
    return _kodex


def kiwoom():
    global _kiwoom
    if _kiwoom is None:
        _kiwoom = KiwoomFetcher()
    return _kiwoom


def ace():
    global _ace
    if _ace is None:
        _ace = AceFetcher()
    return _ace


def plus():
    global _plus
    if _plus is None:
        _plus = PlusFetcher()
    return _plus


def hanaro():
    global _hanaro
    if _hanaro is None:
        _hanaro = HanaroFetcher()
    return _hanaro


def sol_fund_cd(ticker: str):
    global _sol_map
    if _sol_map is None:
        _sol_map = {}
        for it in sol().list_products():
            t = str(it.get("ETF_CD6") or "").strip()
            if t:
                _sol_map[t] = str(it.get("FUND_CD"))
    return _sol_map.get(ticker)


def rise_code(ticker: str):
    """RISE 는 KB 통합 사이트(kbam.co.kr) ETF 목록의 krx_cd(=티커)로 fund_cd 를 찾는다.
    (예전 riseetf.co.kr 이름 검색은 사이트 이전 후 동작하지 않음 — 2026-09-19 부터 수집 중단됐었다)"""
    if ticker not in _rise_cache:
        _rise_cache[ticker] = rise().code_of(ticker)
    return _rise_cache[ticker]


def _pack(holdings, asof, ticker, name, manager, source):
    hs = [{"code": h.stock_code, "name": h.stock_name,
           "weight": round(h.weight, 4), "shares": h.shares, "amount": h.amount}
          for h in holdings if h.stock_name]
    return {
        "ticker": ticker, "name": name, "manager": manager, "source": source,
        "asof": asof.isoformat() if isinstance(asof, dt.date) else (asof or ""),
        "total_weight": round(sum(x["weight"] for x in hs), 2),
        "count": len(hs),
        "holdings": hs,
    }


def fetch_one(etf: dict):
    """etf(dict from etfs.json) → holdings payload 또는 None(미지원/실패)."""
    mgr = etf["manager"]; ticker = etf["ticker"]; isin = etf.get("isin"); name = etf["name"]
    try:
        if mgr == "TIGER":
            asof = tiger().latest_date(isin)
            hs = tiger().fetch(isin, None)
            return _pack(hs, asof, ticker, name, mgr, "미래에셋 TIGER")
        if mgr == "SOL":
            fc = sol_fund_cd(ticker)
            if not fc:
                print(f"    - SOL FUND_CD 미발견 {ticker} {name}"); return None
            hs, work_dt = sol().fetch(fc)
            asof = work_dt
            if len(work_dt) == 8 and work_dt.isdigit():
                asof = f"{work_dt[:4]}-{work_dt[4:6]}-{work_dt[6:]}"
            return _pack(hs, asof, ticker, name, mgr, "신한 SOL")
        if mgr == "RISE":
            rc = rise_code(ticker)
            if not rc:
                print(f"    - RISE code 미발견 {ticker} {name}"); return None
            asof = rise().latest_date(rc)
            hs = rise().fetch(rc, None)
            return _pack(hs, asof, ticker, name, mgr, "KB RISE")
        if mgr == "KODEX":
            hs, asof = kodex().fetch(ticker)
            if len(str(asof)) == 8 and str(asof).isdigit():
                asof = f"{asof[:4]}-{asof[4:6]}-{asof[6:]}"
            return _pack(hs, asof, ticker, name, mgr, "삼성 KODEX")
        if mgr == "KIWOOM":
            hs, asof = kiwoom().fetch(ticker)
            return _pack(hs, asof, ticker, name, mgr, "키움 KIWOOM")
        if mgr == "ACE":
            hs, asof = ace().fetch(ticker)
            return _pack(hs, asof, ticker, name, mgr, "한국투자 ACE")
        if mgr == "PLUS":
            hs, asof = plus().fetch(name)
            return _pack(hs, asof, ticker, name, mgr, "한화 PLUS")
        if mgr == "HANARO":
            hs, asof = hanaro().fetch(name)
            return _pack(hs, asof, ticker, name, mgr, "NH아문디 HANARO")
    except Exception as e:
        print(f"    ! {mgr} {name} 실패: {e}")
        return None
    return None  # 미지원 운용사


def _save(e, payload):
    with open(os.path.join(HOLD, f"{e['ticker']}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    top = payload["holdings"][0]
    print(f"  OK {e['name']:26} {payload['count']:>3}종 asof={payload['asof']} "
          f"top={top['name']}({top['weight']}%)")


def main(only=None):
    etfs = json.load(open(os.path.join(DATA, "etfs.json"), encoding="utf-8"))["etfs"]
    os.makedirs(HOLD, exist_ok=True)
    ok, failed = 0, []
    if SKIP:
        print(f"  (건너뜀: {', '.join(sorted(SKIP))} — 기존 파일 유지)")
    for e in etfs:
        if only and e["manager"] not in only:
            continue
        if e["manager"] in SKIP:
            continue
        payload = fetch_one(e)
        if payload and payload["holdings"]:
            _save(e, payload); ok += 1
        else:
            failed.append(e)

    # 실패분(주로 KODEX 429) 재시도 패스 — 충분히 쉬고 세션 리셋 후 천천히 재시도
    if failed:
        import time
        global _kodex, _ace, _plus, _hanaro
        print(f"\n재시도 대기(60초 쿨다운)… ({len(failed)}종)")
        _kodex = _ace = _plus = _hanaro = None       # 세션 리셋(레이트리밋 완화)
        time.sleep(60)
        still = []
        for e in failed:
            payload = fetch_one(e)
            if payload and payload["holdings"]:
                _save(e, payload); ok += 1
            else:
                still.append(e)
            time.sleep(5)                            # 재시도는 넉넉히 간격
        failed = still

    print(f"\n수집 {ok} · 미수집 {len(failed)}"
          + (" : " + ", ".join(x["name"] for x in failed) if failed else ""))


if __name__ == "__main__":
    only = None
    if len(sys.argv) > 1:
        only = set(a.upper() for a in sys.argv[1:])
    main(only)
