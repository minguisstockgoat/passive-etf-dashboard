# -*- coding: utf-8 -*-
"""
KRX 휴장일 캘린더 → data/holidays.json

정기변경 예정일(rebal_dates)을 영업일 기준으로 세려면 공휴일이 필요하다.
KRX 정보데이터시스템의 휴장일 화면은 **로그인 회원 전용**(비로그인 호출은 `LOGOUT` 반환)이라
공개 API 로는 못 받는다. 그래서 `holidays` 패키지(한국 공휴일, 음력·대체공휴일 계산 포함)로
만들고, 아래 두 가지를 더한다.

  + 근로자의날 5/1      — 공휴일은 아니지만 증시는 휴장. 패키지가 연도에 따라 누락한다.
  + 연말 폐장일 12/31    — 평일이면 휴장(마지막 거래일은 통상 12/30).
  - '노동절 대체 휴일'   — 근로자의날에는 대체휴일이 없다(증시 정상 개장). 제외.

검증(`py kr_holidays.py --verify`): 네이버 KOSPI 일봉의 실제 거래일과 대조한다.
2024-01-01 ~ 2026-08-31 구간에서 위 규칙으로 **불일치 0건**을 확인했다(2026-08-31).

⚠ 임시공휴일(수시 지정)은 예측할 수 없다. 지정되면 이 스크립트를 다시 돌려
   data/holidays.json 을 갱신하거나, `EXTRA_HOLIDAYS` 에 직접 넣는다.
"""
from __future__ import annotations
import os, sys, json, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OUT = os.path.join(DATA, "holidays.json")

# 임시공휴일 등 수동 추가분 (ISO 날짜)
EXTRA_HOLIDAYS: list[str] = []

_CACHE: set[dt.date] | None = None


def _year_end_close(y: int) -> list[dt.date]:
    d = dt.date(y, 12, 31)
    return [d] if d.weekday() < 5 else []


def compute(y0: int, y1: int) -> tuple[set[dt.date], str]:
    """(휴장일 집합, 출처 설명). holidays 패키지가 없으면 빈 집합."""
    try:
        import holidays as H
    except ImportError:
        return set(), "holidays 패키지 없음"
    years = list(range(y0, y1 + 1))
    kr = H.KR(years=years)
    out = set()
    for d, name in kr.items():
        if "노동절 대체" in name:          # 근로자의날엔 대체휴일 없음 → 증시 개장
            continue
        out.add(d)
    for y in years:
        out.add(dt.date(y, 5, 1))          # 근로자의날
        out.update(_year_end_close(y))     # 연말 폐장일
    out.update(dt.date.fromisoformat(s) for s in EXTRA_HOLIDAYS)
    return out, f"holidays {H.__version__} (KR) + 근로자의날 + 연말 폐장일"


def load() -> set[dt.date]:
    """휴장일 집합. data/holidays.json 우선(빌드 산출물), 없으면 즉석 계산."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    days: set[dt.date] = set()
    if os.path.exists(OUT):
        try:
            j = json.load(open(OUT, encoding="utf-8"))
            days = {dt.date.fromisoformat(s) for s in j.get("dates", [])}
        except Exception:
            days = set()
    if not days:
        days, _ = compute(dt.date.today().year - 1, dt.date.today().year + 3)
    _CACHE = days
    return days


def save(y0: int, y1: int) -> int:
    days, src = compute(y0, y1)
    if not days:
        print("  ! 휴장일 계산 실패(holidays 패키지 없음) — 주말만 제외합니다")
        return 0
    payload = {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "years": [y0, y1],
        "source": src,
        "note": "KRX 휴장일(공휴일+근로자의날+연말 폐장일). 임시공휴일은 지정 후 재생성 필요.",
        "dates": [d.isoformat() for d in sorted(days)],
    }
    os.makedirs(DATA, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    global _CACHE
    _CACHE = days
    return len(days)


def verify(y0: int = 2024, y1: int | None = None) -> int:
    """네이버 KOSPI 일봉의 실제 거래일과 대조. 불일치 건수를 돌려준다."""
    import re, requests, urllib3
    urllib3.disable_warnings()
    y1 = y1 or dt.date.today().year
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"})
    s.verify = False
    traded: set[dt.date] = set()
    for y in range(y0, y1 + 1):
        r = s.get("https://api.finance.naver.com/siseJson.naver",
                  params={"symbol": "KOSPI", "requestType": 1,
                          "startTime": f"{y}0101", "endTime": f"{y}1231", "timeframe": "day"},
                  timeout=30)
        for d in re.findall(r'"(\d{8})"', r.text):
            traded.add(dt.date(int(d[:4]), int(d[4:6]), int(d[6:])))
    if not traded:
        print("  ! 네이버 거래일 조회 실패 — 검증 건너뜀")
        return -1
    hol, _ = compute(y0, y1)
    bad = 0
    d, end = dt.date(y0, 1, 1), max(traded)
    while d <= end:
        if d.weekday() < 5:
            pred_open, real_open = d not in hol, d in traded
            if pred_open != real_open:
                bad += 1
                print(f"  불일치 {d} {d:%a} 예측={'개장' if pred_open else '휴장'} "
                      f"실제={'개장' if real_open else '휴장'}")
        d += dt.timedelta(days=1)
    print(f"검증 {y0}~{max(traded)} · 거래일 {len(traded)}일 · 불일치 {bad}건")
    return bad


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--verify" in sys.argv:
        verify()
    else:
        y = dt.date.today().year
        n = save(y - 1, y + 3)
        print(f"휴장일 {n}일 ({y-1}~{y+3}) → data/holidays.json")
