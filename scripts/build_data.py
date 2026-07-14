# -*- coding: utf-8 -*-
"""
대시보드 데이터 빌드 (1단계: 유니버스).

KRX OPEN API 스냅샷 + 큐레이션 메타(etf_meta) + 비중 cap 규칙(cap_rules)을 합쳐
`../data/etfs.json` 을 생성한다. 구성종목(holdings)·cap 초과 판정은 fetch_holdings.py
가 채운 `../data/holdings/{ticker}.json` 을 읽어 요약만 붙인다(없으면 준비중).
"""
from __future__ import annotations
import os, re, sys, json, datetime as dt

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
HOLD = os.path.join(DATA, "holdings")

from etf_meta import build_curated, MANAGERS
from krx_fetch import latest_etf_snapshot
from fetchers import krx_etf_universe
from caps import compute_breach
try:
    from cap_rules import CAP_RULES, REG_NOTE
except Exception:
    CAP_RULES, REG_NOTE = {}, ""

# 이름이 겹치는 TR/유사 종목의 정확 티커 고정 (스냅샷 이름 정규화 충돌 방지) ----
TICKER_OVERRIDE = {
    "KODEX 200TR": "278530",
    "KIWOOM 200TR": "294400",
    "KODEX MSCI Korea TR": "278540",
}


def norm(s: str) -> str:
    s = str(s or "").upper().replace(" ", "")
    s = s.replace("플러스", "+").replace("PLUS", "+")
    s = re.sub(r"[·\-_&]", "", s)
    return s


def resolve_universe():
    bas, rows = latest_etf_snapshot()
    by_ticker = {r["ticker"]: r for r in rows}
    by_norm = {}
    for r in rows:
        by_norm.setdefault(norm(r["name"]), r)
    try:
        uni = krx_etf_universe()
        isin_by_ticker = {u["ticker"]: u["isin"] for u in uni}
    except Exception as e:
        print("  ! finder 실패(ISIN 생략):", e)
        isin_by_ticker = {}
    return bas, by_ticker, by_norm, isin_by_ticker


def main():
    os.makedirs(HOLD, exist_ok=True)
    bas, by_ticker, by_norm, isin_by_ticker = resolve_universe()
    curated = build_curated()

    etfs, missing = [], []
    for c in curated:
        tkr = TICKER_OVERRIDE.get(c["name"])
        r = by_ticker.get(tkr) if tkr else None
        if r is None:
            r = by_norm.get(norm(c["name"]))
        if r is None:
            missing.append(c["name"]); continue

        ticker = r["ticker"]
        mgr = c["manager"]
        cap = CAP_RULES.get(c["name"])

        # holdings 로드 → cap 초과 판정 → holdings 파일 보강 저장 + 요약 추출
        hpath = os.path.join(HOLD, f"{ticker}.json")
        has_h, h_asof, breach = False, None, None
        if os.path.exists(hpath):
            try:
                hj = json.load(open(hpath, encoding="utf-8"))
                holds = hj.get("holdings") or []
                has_h = bool(holds)
                h_asof = hj.get("asof")
                holds, breach = compute_breach(holds, cap, int(r["market_cap"]))
                hj["holdings"] = holds
                hj["breach_summary"] = breach
                hj["cap"] = cap
                with open(hpath, "w", encoding="utf-8") as f:
                    json.dump(hj, f, ensure_ascii=False, indent=1)
            except Exception as e:
                print(f"  ! holdings 처리 실패 {ticker}: {e}")

        etfs.append({
            "ticker": ticker,
            "isin": isin_by_ticker.get(ticker, f"KR7{ticker}00" if ticker.isdigit() else ""),
            "name": c["name"],
            "krx_name": r["name"],
            "manager": mgr,
            "company": MANAGERS.get(mgr, {}).get("company", ""),
            "color": MANAGERS.get(mgr, {}).get("color", "#2d8b8b"),
            "category": c["category"],
            "is_theme": c["is_theme"],
            "index_name": r["index_indicator_name"],
            "market_cap": int(r["market_cap"]),
            "shares": int(r["shares"]),
            "close": r["close"],
            "nav": r["nav"],
            "schedule_label": c["schedule_label"],
            "schedule_detail": c["schedule_detail"],
            "months": c["months"],
            "cap": cap,
            "has_holdings": has_h,
            "holdings_asof": h_asof,
            "breach_summary": breach,
        })

    etfs.sort(key=lambda x: x["market_cap"], reverse=True)
    out = {
        "as_of": f"{bas[:4]}-{bas[4:6]}-{bas[6:]}",
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "count": len(etfs),
        "reg_note": REG_NOTE,
        "etfs": etfs,
    }
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "etfs.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"기준일 {out['as_of']} · {len(etfs)}종 → data/etfs.json")
    if missing:
        print("  ! 미해결:", missing)
    hs = sum(1 for e in etfs if e["has_holdings"])
    print(f"  구성종목 보유: {hs}/{len(etfs)}")


if __name__ == "__main__":
    main()
