#!/usr/bin/env python3
"""data/etfs.json 의 KRX 기준일이 실제 최신 거래일인지 확인한다.

krx_fetch.latest_etf_snapshot 은 해당 일자 데이터가 없으면 조용히 전 영업일로
폴백한다. 그래서 실행 시각이 KRX 공개 시각보다 이르면 워크플로는 초록불인데
기준일만 매일 하루씩 밀린 채 굳는다 — 이 저장소에서 실제로 발생한 실패 모드다.

지연은 **휴장일을 뺀 실제 거래일**로 센다. 예전엔 주말만 빼고 세는 바람에
연휴가 끼면 멀쩡한 데이터를 두고 실패했다 — 2026-09-26 추석 연휴(9/24·9/25)에
"목표 2026-09-25 / 지연 3영업일" 로 오탐이 났다. 휴장일 달력은 같은 패키지의
kr_holidays 가 이미 들고 있다.

1거래일 지연은 경고(정상 T-1), 3거래일 이상이면 실패로 끝낸다.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
KST = dt.timezone(dt.timedelta(hours=9))


def holidays() -> set[dt.date]:
    """휴장일 집합. 달력을 못 읽으면 빈 집합 — 주말만 빼는 예전 동작으로 되돌아간다."""
    try:
        import kr_holidays
        return kr_holidays.load()
    except Exception as e:                       # noqa: BLE001
        print(f"::warning::휴장일 달력을 읽지 못했다({e}). 주말만 제외하고 센다.")
        return set()


def is_trading_day(d: dt.date, hol: set[dt.date]) -> bool:
    return d.weekday() < 5 and d not in hol


def last_trading_day(d: dt.date, hol: set[dt.date]) -> dt.date:
    while not is_trading_day(d, hol):
        d -= dt.timedelta(days=1)
    return d


def trading_days_between(start: dt.date, end: dt.date, hol: set[dt.date]) -> int:
    """start(제외) ~ end(포함) 사이 거래일 수."""
    n, cur = 0, start + dt.timedelta(days=1)
    while cur <= end:
        if is_trading_day(cur, hol):
            n += 1
        cur += dt.timedelta(days=1)
    return n


def main() -> int:
    meta = json.loads((ROOT / "data" / "etfs.json").read_text(encoding="utf-8"))
    as_of = dt.date.fromisoformat(meta["as_of"])
    hol = holidays()

    now = dt.datetime.now(KST)
    # 20:10 KST 실행 기준: 오늘이 거래일이면 오늘 종가가 목표. 새벽·휴장이면 직전 거래일.
    base = now.date() if now.hour >= 18 else now.date() - dt.timedelta(days=1)
    target = last_trading_day(base, hol)
    lag = trading_days_between(as_of, target, hol)

    print(f"KRX 기준일 {as_of} / 목표 {target} / 지연 {lag}거래일 (종목 {meta.get('count')}종)")

    if lag >= 3:
        print(f"::error::기준일이 {lag}거래일 밀렸다. KRX_API_KEY 만료 또는 OPEN API 응답 확인.",
              file=sys.stderr)
        return 1
    if lag >= 1:
        print(f"::warning::기준일이 {lag}거래일 밀렸다. T-1 은 정상이다. 계속 늘어나면 "
              f"실행 시각이 KRX 공개(대략 18시 KST 이후)보다 이른지 확인하라.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
