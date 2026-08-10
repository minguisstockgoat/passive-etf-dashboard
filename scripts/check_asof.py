#!/usr/bin/env python3
"""data/etfs.json 의 KRX 기준일이 실제 최신 영업일인지 확인한다.

krx_fetch.latest_etf_snapshot 은 해당 일자 데이터가 없으면 조용히 전 영업일로
폴백한다. 그래서 실행 시각이 KRX 공개 시각보다 이르면 워크플로는 초록불인데
기준일만 매일 하루씩 밀린 채 굳는다 — 이 저장소에서 실제로 발생한 실패 모드다.

연휴·휴장은 알 수 없으므로 1영업일 지연은 경고, 3영업일 이상이면 실패로 끝낸다.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KST = dt.timezone(dt.timedelta(hours=9))


def last_weekday(d: dt.date) -> dt.date:
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def weekdays_between(start: dt.date, end: dt.date) -> int:
    """start(제외) ~ end(포함) 사이 평일 수."""
    n, cur = 0, start + dt.timedelta(days=1)
    while cur <= end:
        if cur.weekday() < 5:
            n += 1
        cur += dt.timedelta(days=1)
    return n


def main() -> int:
    meta = json.loads((ROOT / "data" / "etfs.json").read_text(encoding="utf-8"))
    as_of = dt.date.fromisoformat(meta["as_of"])

    now = dt.datetime.now(KST)
    # 20:10 KST 실행 기준: 오늘이 평일이면 오늘 종가가 목표. 새벽·주말이면 직전 평일.
    target = last_weekday(now.date() if now.hour >= 18 else now.date() - dt.timedelta(days=1))
    lag = weekdays_between(as_of, target)

    print(f"KRX 기준일 {as_of} / 목표 {target} / 지연 {lag}영업일 (종목 {meta.get('count')}종)")

    if lag >= 3:
        print(f"::error::기준일이 {lag}영업일 밀렸다. KRX_API_KEY 만료 또는 OPEN API 응답 확인.",
              file=sys.stderr)
        return 1
    if lag >= 1:
        print(f"::warning::기준일이 {lag}영업일 밀렸다. 휴장일이면 정상, 아니면 실행 시각이 "
              f"KRX 공개(대략 18시 KST 이후)보다 이른지 확인하라.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
