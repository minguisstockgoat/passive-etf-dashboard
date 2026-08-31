# -*- coding: utf-8 -*-
"""
정기변경(리밸런싱) 예정일 계산 → etfs.json 의 `rebalance` 필드.

`etf_meta`/`index_rules` 가 들고 있는 정기변경 서술(예: "6·12월 선물옵션 만기일 D+2",
"익주 첫 영업일", "2·5·8·11월 말")을 실제 날짜로 옮긴다. 목록 화면에서 '정기변경 임박'
순으로 정렬·필터하려면 월(月)만으로는 부족하고 날짜가 있어야 한다.

기준점(anchor)
  - 선물옵션 만기일 = 해당 월 **두 번째 목요일** (KRX). 대부분의 지수가 이 날을 기준으로
    D+n 영업일에 정기변경을 건다.
  - "익주 첫/두번째 영업일", "월말", "월 첫 영업일", "두 번째 금요일" 도 각각 처리.
  - 아무 단서가 없으면 만기일 D+1 로 두고 estimated=True 로 표시한다.

⚠ 영업일은 **주말만** 제외한다(공휴일 미반영). 하루 이틀 밀릴 수 있어 화면에는 '예상'으로
   표기한다. 임박 여부를 가리는 용도로는 충분하다.
⚠ 여기서 내는 날짜는 **지수 변경 효력일**이다. ETF 의 실제 매매는 통상 그 직전 거래일
   종가에 몰린다(화면 각주에 명시).
"""
from __future__ import annotations
import re
import datetime as dt

KST = dt.timezone(dt.timedelta(hours=9))


def kst_today() -> dt.date:
    return dt.datetime.now(KST).date()


def _is_bday(d: dt.date) -> bool:
    return d.weekday() < 5


def _bday_add(d: dt.date, n: int) -> dt.date:
    """영업일 n 만큼 이동(주말만 제외). n=0 이면 그날이 휴일일 때 다음 영업일."""
    while not _is_bday(d):
        d += dt.timedelta(days=1)
    step = 1 if n >= 0 else -1
    for _ in range(abs(n)):
        d += dt.timedelta(days=step)
        while not _is_bday(d):
            d += dt.timedelta(days=step)
    return d


def nth_weekday(y: int, m: int, weekday: int, nth: int) -> dt.date:
    """그 달의 n번째 요일(weekday: 월0…일6)."""
    d = dt.date(y, m, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(days=7 * (nth - 1))


def expiry(y: int, m: int) -> dt.date:
    """선물옵션 만기일 = 두 번째 목요일(휴일이면 직전 영업일)."""
    d = nth_weekday(y, m, 3, 2)
    while not _is_bday(d):
        d -= dt.timedelta(days=1)
    return d


def month_end(y: int, m: int) -> dt.date:
    d = dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1) - dt.timedelta(days=1)
    while not _is_bday(d):
        d -= dt.timedelta(days=1)
    return d


def month_first(y: int, m: int) -> dt.date:
    return _bday_add(dt.date(y, m, 1), 0)


def next_week_first(d: dt.date) -> dt.date:
    """d 가 속한 주의 다음 주 첫 영업일."""
    return _bday_add(d + dt.timedelta(days=7 - d.weekday()), 0)


# ---------------------------------------------------------------------------
# 서술 → 규칙
# ---------------------------------------------------------------------------
def parse_rule(label: str, detail: str) -> tuple[str, int, str, bool]:
    """(kind, n, 사람이 읽는 규칙, 단서없이 기본값을 쓴 것인지)"""
    t = f"{label or ''} {detail or ''}"

    if re.search(r"두\s*번째\s*금요일", t):
        return "nth_fri", 2, "둘째 금요일", False
    if re.search(r"(익주|다음\s*주)\s*두\s*?번째\s*영업일", t):
        return "next_week", 1, "만기일 익주 둘째 영업일", False
    if re.search(r"(익주|다음\s*주|만기주\s*다음\s*주)\s*첫\s*영업일", t):
        return "next_week", 0, "만기일 익주 첫 영업일", False
    m = re.search(r"말\s*·?\s*수행\s*D\+(\d+)", t)
    if m:                                        # 월말 기준일 + n영업일 수행
        return "month_end", int(m.group(1)), f"월말 기준 D+{m.group(1)}", False
    m = (re.search(r"D\+(\d+)", t)
         or re.search(r"만기(?:일)?\s*\+?\s*(\d+)\s*영업일", t)
         or re.search(r"(?:선물|옵션)만기(?:일)?\s*(\d+)\s*영업일\s*후", t)
         or re.search(r"선물만기\s*(\d+)영업일\s*후", t))
    if m:
        n = int(m.group(1))
        return "expiry", n, f"만기일 D+{n}", False
    if re.search(r"익일|익영업일|다음\s*영업일|다음\s*거래일", t):
        return "expiry", 1, "만기일 D+1", False
    if re.search(r"월\s?말\s*(효력|정기변경|리밸런싱)|월\s?말$|월\s말", (label or "")) \
       or re.search(r"말\s*효력", t):
        return "month_end", 0, "월말", False
    if re.search(r"첫\s*영업일", t):
        return "month_first", 0, "월 첫 영업일", False
    if re.search(r"만기일\s*$|만기일\)|선물옵션\s*만기일", t):
        return "expiry", 0, "만기일 당일", False
    return "expiry", 1, "만기일 D+1(단서 없음)", True


def rule_date(kind: str, n: int, y: int, m: int) -> dt.date:
    if kind == "expiry":
        return _bday_add(expiry(y, m), n)
    if kind == "next_week":
        return _bday_add(next_week_first(expiry(y, m)), n)
    if kind == "month_end":
        return _bday_add(month_end(y, m), n)
    if kind == "month_first":
        return _bday_add(month_first(y, m), n)
    if kind == "nth_fri":
        d = nth_weekday(y, m, 4, n)
        return _bday_add(d, 0)
    return _bday_add(expiry(y, m), 1)


def upcoming(months, label: str, detail: str, today: dt.date | None = None,
             count: int = 4) -> dict | None:
    """정기변경 월 목록 → 앞으로의 정기변경 예정일 count 개.
    months 가 None(미확인)/빈 리스트(수시)면 None."""
    if not months:
        return None
    kind, n, rule, guessed = parse_rule(label, detail)
    today = today or kst_today()
    out = []
    for y in (today.year, today.year + 1, today.year + 2):
        for m in sorted(set(int(x) for x in months if 1 <= int(x) <= 12)):
            try:
                d = rule_date(kind, n, y, m)
            except ValueError:
                continue
            if d >= today:
                out.append(d)
        if len(out) >= count:
            break
    out = sorted(set(out))[:count]
    if not out:
        return None
    return {"dates": [d.isoformat() for d in out], "rule": rule, "guessed": guessed}


def attach(etfs: list, today: dt.date | None = None) -> int:
    """etfs 레코드에 rebalance 필드를 붙이고, 채워진 개수를 돌려준다."""
    today = today or kst_today()
    n = 0
    for e in etfs:
        r = upcoming(e.get("months"), e.get("schedule_label", ""),
                     e.get("schedule_detail", ""), today)
        if r:
            # 일정 자체가 자동추정이면 날짜도 추정치다
            r["estimated"] = bool(r.pop("guessed") or not e.get("schedule_verified"))
            n += 1
        e["rebalance"] = r
    return n


if __name__ == "__main__":
    import os, sys, json
    sys.stdout.reconfigure(encoding="utf-8")
    DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    etfs = json.load(open(os.path.join(DATA, "etfs.json"), encoding="utf-8"))["etfs"]
    attach(etfs)
    today = kst_today()
    rows = [e for e in etfs if e.get("rebalance")]
    rows.sort(key=lambda e: e["rebalance"]["dates"][0])
    for e in rows[:25]:
        r = e["rebalance"]
        d = dt.date.fromisoformat(r["dates"][0])
        print(f"D-{(d - today).days:<4} {r['dates'][0]}  {e['name'][:26]:28} "
              f"[{e['schedule_label']}] → {r['rule']}{' (추정)' if r['estimated'] else ''}")
    print(f"\n일정 있음 {len(rows)} / 전체 {len(etfs)}")
