# -*- coding: utf-8 -*-
"""
KRX OPEN API (data-dbg.krx.co.kr) 자립형 커넥터.

krx-market-data 스킬과 동일한 엔드포인트(etp/etf_bydd_trd)를 직접 호출한다.
GitHub Actions·로컬 빌드에서 KRX_API_KEY(=AUTH_KEY 헤더)만 있으면 동작하도록
스킬 의존 없이 최소 구현.
"""
from __future__ import annotations
import os
import datetime as dt
from typing import Optional

import requests

ETF_URL = "https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_trd"
STOCK_URL = "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd"
KOSDAQ_URL = "https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd"
TIMEOUT = 30

FIELD_MAP = {
    "ISU_CD": "ticker", "ISU_NM": "name", "TDD_CLSPRC": "close",
    "MKTCAP": "market_cap", "LIST_SHRS": "shares",
    "IDX_IND_NM": "index_indicator_name", "NAV": "nav",
    "BAS_DD": "trade_date",
}


def _key() -> str:
    k = os.environ.get("KRX_API_KEY") or os.environ.get("KRX_AUTH_KEY")
    if not k:
        raise RuntimeError("KRX_API_KEY 환경변수가 필요합니다. (setx KRX_API_KEY \"인증키\")")
    return k.strip()


def _num(s):
    try:
        return float(str(s).replace(",", "")) if s not in (None, "", "-") else 0.0
    except ValueError:
        return 0.0


def fetch_etf_raw(bas_dd: str) -> list[dict]:
    """basDd(YYYYMMDD) ETF 전종목 일별매매정보 원본 rows."""
    r = requests.get(
        ETF_URL, params={"basDd": bas_dd},
        headers={"AUTH_KEY": _key()}, timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("OutBlock_1", []) or []


def _norm_rows(raw: list[dict]) -> list[dict]:
    out = []
    for row in raw:
        d = {}
        for k, v in FIELD_MAP.items():
            d[v] = row.get(k, "")
        d["ticker"] = str(d["ticker"]).strip()
        d["name"] = str(d["name"]).strip()
        d["market_cap"] = _num(d["market_cap"])
        d["shares"] = _num(d["shares"])
        d["close"] = _num(d["close"])
        d["nav"] = _num(d["nav"])
        d["index_indicator_name"] = str(d["index_indicator_name"]).strip()
        out.append(d)
    return out


def latest_etf_snapshot(asof: Optional[dt.date] = None, lookback: int = 10) -> tuple[str, list[dict]]:
    """asof(기본 오늘)부터 최대 lookback 영업일 역순으로 데이터가 있는 최신일을 찾는다.
    return (기준일 YYYYMMDD, 정규화 rows)."""
    d = asof or dt.date.today()
    for _ in range(lookback):
        if d.weekday() < 5:  # 월~금만 시도
            bas = d.strftime("%Y%m%d")
            try:
                raw = fetch_etf_raw(bas)
            except Exception:
                raw = []
            if raw:
                return bas, _norm_rows(raw)
        d -= dt.timedelta(days=1)
    raise RuntimeError("최근 영업일 ETF 스냅샷을 찾지 못했습니다.")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    asof = None
    if len(sys.argv) > 1:
        asof = dt.datetime.strptime(sys.argv[1], "%Y%m%d").date()
    bas, rows = latest_etf_snapshot(asof)
    print(f"기준일 {bas} · {len(rows)}종")
    for r in rows[:3]:
        print(" ", r["ticker"], r["name"], f"{r['market_cap']:,.0f}", r["index_indicator_name"])
