# -*- coding: utf-8 -*-
"""비중 cap 초과 판정 + 매도규모 계산."""
from __future__ import annotations


def compute_breach(holdings: list[dict], cap: dict | None, market_cap: int):
    """holdings 각 항목에 over_cap 플래그를 달고, cap 초과 요약을 만든다.

    매도규모 = 시가총액 × (초과 %p / 100)   (사용자 지정 단순식)
    index_exception(지수 복제형) 또는 상한 미설정이면 강제 매도 대상 없음.
    return: (enriched_holdings, breach_summary | None)
    """
    for h in holdings:
        h["over_cap"] = False

    if not cap or cap.get("single_cap") is None or cap.get("index_exception"):
        return holdings, None

    sc = float(cap["single_cap"])          # 예: 0.30
    cap_pct = sc * 100.0
    items = []
    for h in holdings:
        w = float(h.get("weight", 0.0))
        if w > cap_pct + 1e-9:
            h["over_cap"] = True
            excess_pp = round(w - cap_pct, 3)
            sell = int(round(market_cap * (excess_pp / 100.0)))
            items.append({
                "code": h.get("code"), "name": h.get("name"),
                "weight": round(w, 3), "cap_pct": round(cap_pct, 2),
                "excess_pp": excess_pp, "sell_amount": sell,
            })
    if not items:
        return holdings, None
    items.sort(key=lambda x: x["excess_pp"], reverse=True)
    summary = {
        "cap_pct": round(cap_pct, 2),
        "verified": bool(cap.get("verified")),
        "count": len(items),
        "total_sell": int(sum(i["sell_amount"] for i in items)),
        "items": items,
    }
    return holdings, summary
