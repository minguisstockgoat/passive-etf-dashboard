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
import universe as U
import index_rules as IR
from cap_rules import cap_for, CAP_RULES, REG_NOTE

MINCAP = float(os.environ.get("ETF_MIN_CAP", U.MINCAP_DEFAULT))   # 기본 300억

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


def _resolve_row(c, by_ticker, by_norm):
    tkr = TICKER_OVERRIDE.get(c["name"])
    r = by_ticker.get(tkr) if tkr else None
    if r is None:
        r = by_norm.get(norm(c["name"]))
    return r


def main():
    os.makedirs(HOLD, exist_ok=True)
    bas, by_ticker, by_norm, isin_by_ticker = resolve_universe()

    # 1) 큐레이션 32종 (검증된 정기변경·분류·cap)
    pairs = []          # (meta, row)
    used = set()
    missing = []
    for c in build_curated():
        r = _resolve_row(c, by_ticker, by_norm)
        if r is None:
            missing.append(c["name"]); continue
        c["auto"] = False
        pairs.append((c, r)); used.add(r["ticker"])

    # 2) 자동 확장: 8대 브랜드 · 국내주식형 패시브 · 시총 필터
    auto_n = 0
    for r in by_ticker.values():
        if r["ticker"] in used:
            continue
        if not U.passes(r, MINCAP):
            continue
        pairs.append((U.auto_record(r), r)); used.add(r["ticker"]); auto_n += 1

    # 3) 레코드 생성 (+ cap 판정, 단일종목 제외)
    etfs, single = [], 0
    for c, r in pairs:
        ticker = r["ticker"]; mgr = c["manager"]; idxnm = r["index_indicator_name"]
        is_mkt = U.classify(c["name"], idxnm)[1]

        # 정기변경: 큐레이션=검증 / 자동=index_rules 조회(있으면 검증) 아니면 자동추정
        sched_verified = not c.get("auto", False)
        if c.get("auto"):
            sr = IR.resolve_schedule(idxnm)
            if sr:
                c["months"], c["schedule_label"], c["schedule_detail"], sched_verified = sr

        # cap: 큐레이션 규칙 > index_rules(지수) > 복제형/미확인
        if c["name"] in CAP_RULES:
            cap = CAP_RULES[c["name"]]
        else:
            cap = IR.resolve_cap(idxnm) or cap_for(c["name"], is_mkt)

        hpath = os.path.join(HOLD, f"{ticker}.json")
        has_h, h_asof, breach = False, None, None
        if os.path.exists(hpath):
            try:
                hj = json.load(open(hpath, encoding="utf-8"))
                holds = hj.get("holdings") or []
                # 단일/2종목 ETF = 사실상 단일종목형 → 제외
                if 0 < len(holds) <= 2:
                    single += 1
                    continue
                has_h = bool(holds)
                h_asof = hj.get("asof")
                holds, breach = compute_breach(holds, cap, int(r["market_cap"]))
                hj["holdings"] = holds; hj["breach_summary"] = breach; hj["cap"] = cap
                with open(hpath, "w", encoding="utf-8") as f:
                    json.dump(hj, f, ensure_ascii=False, indent=1)
            except Exception as e:
                print(f"  ! holdings 처리 실패 {ticker}: {e}")

        etfs.append({
            "ticker": ticker,
            "isin": isin_by_ticker.get(ticker, f"KR7{ticker}00" if ticker.isdigit() else ""),
            "name": c["name"], "krx_name": r["name"], "manager": mgr,
            "company": MANAGERS.get(mgr, {}).get("company", ""),
            "color": MANAGERS.get(mgr, {}).get("color", "#2d8b8b"),
            "category": c["category"], "is_theme": c["is_theme"],
            "index_name": r["index_indicator_name"],
            "market_cap": int(r["market_cap"]), "shares": int(r["shares"]),
            "close": r["close"], "nav": r["nav"],
            "schedule_label": c["schedule_label"], "schedule_detail": c["schedule_detail"],
            "months": c["months"], "auto": c.get("auto", False),
            "schedule_verified": sched_verified,
            "cap": cap, "cap_verified": bool(cap and cap.get("verified")),
            "has_holdings": has_h, "holdings_asof": h_asof, "breach_summary": breach,
        })

    etfs.sort(key=lambda x: x["market_cap"], reverse=True)
    out = {
        "as_of": f"{bas[:4]}-{bas[4:6]}-{bas[6:]}",
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "count": len(etfs),
        "min_cap_eok": int(MINCAP / 1e8),
        "reg_note": REG_NOTE,
        "etfs": etfs,
    }
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "etfs.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    hs = sum(1 for e in etfs if e["has_holdings"])
    auto = sum(1 for e in etfs if e.get("auto"))
    print(f"기준일 {out['as_of']} · {len(etfs)}종 (커버레이션 {len(etfs)-auto} + 자동 {auto}) "
          f"· 시총 {out['min_cap_eok']:,}억+ → data/etfs.json")
    print(f"  구성종목 보유: {hs}/{len(etfs)} · 단일종목 제외 {single}종")
    if missing:
        print("  ! 큐레이션 미해결:", missing)


if __name__ == "__main__":
    main()
