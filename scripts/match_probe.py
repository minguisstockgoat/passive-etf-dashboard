# -*- coding: utf-8 -*-
"""32 큐레이션 이름을 KRX 스냅샷에 매칭해 티커/ISIN 확인 (진단용)."""
from __future__ import annotations
import sys, re
sys.stdout.reconfigure(encoding="utf-8")

from etf_meta import build_curated
from krx_fetch import latest_etf_snapshot
from fetchers import krx_etf_universe


def norm(s: str) -> str:
    s = str(s or "").upper().replace(" ", "")
    s = s.replace("플러스", "+").replace("PLUS", "+")
    s = s.replace("TR", "").replace("(H)", "").replace("(합성)", "")
    s = re.sub(r"[·\-_&]", "", s)
    return s


bas, rows = latest_etf_snapshot()
by_norm = {}
for r in rows:
    by_norm.setdefault(norm(r["name"]), r)

# ISIN 맵
try:
    uni = krx_etf_universe()
    isin_by_ticker = {u["ticker"]: u["isin"] for u in uni}
except Exception as e:
    print("finder 실패:", e); isin_by_ticker = {}

curated = build_curated()
matched, unmatched = [], []
for c in curated:
    key = norm(c["name"])
    r = by_norm.get(key)
    if not r:
        # 부분 포함 매칭
        cand = [rr for k, rr in by_norm.items() if key in k or k in key]
        r = cand[0] if len(cand) == 1 else None
    if r:
        matched.append((c["name"], r["name"], r["ticker"], isin_by_ticker.get(r["ticker"], "?"),
                        r["market_cap"], r["index_indicator_name"]))
    else:
        unmatched.append(c["name"])

print(f"기준일 {bas} · 매칭 {len(matched)}/{len(curated)}")
for m in matched:
    print(f"  OK  {m[0]:28} -> {m[1]:30} {m[2]:8} {m[3]:14} {m[4]/1e8:>10,.0f}억  [{m[5]}]")
print("--- 미매칭 ---")
for u in unmatched:
    print("  ??", u)
