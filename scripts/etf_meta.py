# -*- coding: utf-8 -*-
"""
국내 상장 패시브 ETF 대시보드 - 큐레이션 메타데이터.

`passive_etf_rebalancing_schedule.md`(2026-07-13 KRX 종가, 시총 9천억원 이상
국내주식형 실물 패시브 ETF 32종)를 구조화한 것.

각 항목의 시가총액/상장좌수/기초지수/티커/ISIN 은 빌드 시점에 KRX OPEN API
(etf-daily-trade) 스냅샷에서 이름 매칭으로 채운다. 여기에는 이름 매칭·정기변경
일정·분류·비중 cap 규칙 등 KRX 스냅샷으로는 알 수 없는 큐레이션 값만 둔다.

category  : 시장대표 | 섹터 | 테마 | 전략 | 그룹주
is_theme  : (category != "시장대표")  → 섹터/테마 필터에서 사용
schedule  : 표기용 정기변경 일정 문자열 (MD 원문)
months    : 정기변경이 일어나는 월(1~12) 리스트. 수시(고정 없음)는 [].
effday    : 지수변경 효력일 기준 D 설명 (툴팁)
cap       : 비중 cap 규칙 (아래 CAP_RULES 참고). None 이면 별도 종목상한 없음.
"""
from __future__ import annotations

# 정기변경 일정 그룹 (MD 표의 행) -----------------------------------------
# label, months, 소속 ETF(정식명에 가까운 요청명)
SCHEDULE_GROUPS = [
    {
        "label": "6·12월 D+1",
        "months": [6, 12],
        "detail": "6·12월 선물옵션 만기일(D) 다음 영업일 지수변경 → 통상 효력일 직전 거래일 종가 매매",
        "etfs": [
            "KODEX 200", "TIGER 200", "KODEX 200TR", "KODEX 코스닥150",
            "RISE 200", "TIGER 200 IT", "KIWOOM 200TR", "ACE 200",
            "PLUS 200", "TIGER 코스닥150", "KODEX 코스피100",
        ],
    },
    {
        "label": "6·12월 D+2",
        "months": [6, 12],
        "detail": "6·12월 만기일 +2 영업일 지수변경",
        "etfs": [
            "KODEX AI반도체TOP2플러스", "KODEX AI전력핵심설비",
            "SOL AI반도체소부장", "PLUS K방산",
        ],
    },
    {
        "label": "6·12월 D+3",
        "months": [6, 12],
        "detail": "6·12월 만기일 +3 영업일 지수변경",
        "etfs": ["TIGER 코리아AI전력기기TOP3플러스"],
    },
    {
        "label": "6·12월 D+4",
        "months": [6, 12],
        "detail": "6·12월 만기일 +4 영업일 지수변경",
        "etfs": ["HANARO Fn K-반도체", "PLUS 고배당주"],
    },
    {
        "label": "6·12월 D+1~5 분할",
        "months": [6, 12],
        "detail": "6·12월 만기일 이후 5영업일에 걸쳐 분할 리밸런싱",
        "etfs": ["KODEX 삼성그룹"],
    },
    {
        "label": "4·10월 D+2",
        "months": [4, 10],
        "detail": "4·10월 만기일 +2 영업일 지수변경",
        "etfs": ["TIGER 반도체TOP10"],
    },
    {
        "label": "1·4·7·10월 D+2",
        "months": [1, 4, 7, 10],
        "detail": "분기(1·4·7·10월) 만기일 +2 영업일 지수변경",
        "etfs": ["SOL AI반도체TOP2플러스"],
    },
    {
        "label": "9월 D+1, 연 1회",
        "months": [9],
        "detail": "연 1회 9월 만기일 +1 영업일 지수변경",
        "etfs": ["KODEX 반도체", "TIGER 반도체"],
    },
    {
        "label": "2·5·8·11월 말",
        "months": [2, 5, 8, 11],
        "detail": "MSCI 분기 리뷰 — 2·5·8·11월 말 효력",
        "etfs": ["TIGER MSCI Korea TR", "KODEX MSCI Korea TR"],
    },
    {
        "label": "3·9월 D+2",
        "months": [3, 9],
        "detail": "3·9월 만기일 +2 영업일 지수변경",
        "etfs": ["TIGER 코리아TOP10"],
    },
    {
        "label": "6월 D+2, 연 1회",
        "months": [6],
        "detail": "연 1회 6월 만기일 +2 영업일 지수변경",
        "etfs": ["KODEX Top5PlusTR"],
    },
    {
        "label": "3·6·9·12월 D+2~4",
        "months": [3, 6, 9, 12],
        "detail": "분기(3·6·9·12월) 만기일 +2~4 영업일 지수변경",
        "etfs": ["KODEX 2차전지산업", "ACE AI반도체TOP3+"],
    },
    {
        "label": "2·5·8·11월 D+2",
        "months": [2, 5, 8, 11],
        "detail": "분기(2·5·8·11월) 만기일 +2 영업일 지수변경",
        "etfs": ["SOL 조선TOP3플러스"],
    },
    {
        "label": "6월 D+1, 연 1회",
        "months": [6],
        "detail": "연 1회 6월 만기일 +1 영업일 지수변경",
        "etfs": ["RISE 코리아밸류업"],
    },
    {
        "label": "수시 (고정 정기 종목교체 없음)",
        "months": [],
        "detail": "유가증권시장 전 종목 지수라 신규상장·상장폐지 등을 수시 반영",
        "etfs": ["KODEX 코스피"],
    },
]

# ETF 분류 (섹터/테마 필터용) --------------------------------------------
CATEGORY = {
    # 시장대표 (정통 시가총액가중 패시브)
    "KODEX 200": "시장대표", "TIGER 200": "시장대표", "KODEX 200TR": "시장대표",
    "KODEX 코스닥150": "시장대표", "RISE 200": "시장대표", "KIWOOM 200TR": "시장대표",
    "ACE 200": "시장대표", "PLUS 200": "시장대표", "TIGER 코스닥150": "시장대표",
    "KODEX 코스피100": "시장대표", "KODEX 코스피": "시장대표",
    "TIGER MSCI Korea TR": "시장대표", "KODEX MSCI Korea TR": "시장대표",
    # 섹터
    "TIGER 200 IT": "섹터", "KODEX 반도체": "섹터", "TIGER 반도체": "섹터",
    # 테마
    "KODEX AI반도체TOP2플러스": "테마", "KODEX AI전력핵심설비": "테마",
    "SOL AI반도체소부장": "테마", "PLUS K방산": "테마",
    "TIGER 코리아AI전력기기TOP3플러스": "테마", "HANARO Fn K-반도체": "테마",
    "TIGER 반도체TOP10": "테마", "SOL AI반도체TOP2플러스": "테마",
    "KODEX 2차전지산업": "테마", "ACE AI반도체TOP3+": "테마",
    "SOL 조선TOP3플러스": "테마",
    # 전략
    "PLUS 고배당주": "전략", "TIGER 코리아TOP10": "전략",
    "KODEX Top5PlusTR": "전략", "RISE 코리아밸류업": "전략",
    # 그룹주
    "KODEX 삼성그룹": "그룹주",
}

# 운용사 (ETF명 접두어 → 운용사/브랜드) ----------------------------------
MANAGERS = {
    "KODEX":  {"company": "삼성자산운용",     "brand": "KODEX",  "color": "#1428A0"},
    "TIGER":  {"company": "미래에셋자산운용", "brand": "TIGER",  "color": "#F05A22"},
    "RISE":   {"company": "KB자산운용",       "brand": "RISE",   "color": "#F5A623"},
    "SOL":    {"company": "신한자산운용",     "brand": "SOL",    "color": "#0046FF"},
    "ACE":    {"company": "한국투자신탁운용", "brand": "ACE",    "color": "#E60012"},
    "PLUS":   {"company": "한화자산운용",     "brand": "PLUS",   "color": "#F37021"},
    "KIWOOM": {"company": "키움투자자산운용", "brand": "KIWOOM", "color": "#D6001C"},
    "HANARO": {"company": "NH아문디자산운용", "brand": "HANARO", "color": "#00A19C"},
}


def manager_of(name: str) -> str:
    return name.split(" ", 1)[0].upper() if name else ""


def build_curated() -> list[dict]:
    """32종 큐레이션 레코드(정기변경/분류/운용사) 조립. 시총·티커·지수는 빌드시 KRX로 채움."""
    out = []
    for grp in SCHEDULE_GROUPS:
        for nm in grp["etfs"]:
            cat = CATEGORY.get(nm, "테마")
            out.append({
                "name": nm,
                "manager": manager_of(nm),
                "category": cat,
                "is_theme": cat != "시장대표",
                "schedule_label": grp["label"],
                "schedule_detail": grp["detail"],
                "months": grp["months"],
            })
    return out


if __name__ == "__main__":
    import sys, json
    sys.stdout.reconfigure(encoding="utf-8")
    rows = build_curated()
    print(f"{len(rows)}종")
    for r in rows:
        print(f"  {r['manager']:7} {r['name']:28} {r['category']:5} {r['schedule_label']}")
