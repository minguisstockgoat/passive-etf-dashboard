# -*- coding: utf-8 -*-
"""
유니버스 자동 확장: KRX 스냅샷에서 국내주식형 패시브 ETF를 골라내고
(운용사·시총 필터 + 커버드콜/레버리지/인버스/액티브/채권/단일종목/해외 제외)
비큐레이션 종목의 분류·정기변경 일정을 자동 추정한다.

큐레이션 32종(etf_meta)은 손으로 검증된 값을 그대로 쓰고, 그 외 종목만 여기서
자동 분류한다. 자동 항목은 auto=True 로 표시되어 화면에서 '확인 요' 처리된다.
"""
from __future__ import annotations
import re

BIG8 = {"KODEX", "TIGER", "RISE", "SOL", "ACE", "PLUS", "KIWOOM", "HANARO"}
MINCAP_DEFAULT = 3e10   # 300억

# 제외: 커버드콜·레버리지·인버스·액티브·채권·금리·통화·원자재·TDF 등
_EXC = re.compile(
    r"레버리지|인버스|커버드콜|버퍼|프리미엄|타겟위클리|데일리커버|위클리커버|"
    r"액티브|채권|혼합|금리|CD ?금리|머니마켓|MMF|달러|엔화|위안|골드|금\(|원유|"
    r"구리|은\(|TDF|TRF|만기|국공채|국채|국고채|물가|머니|현금|플로팅|양매도|"
    r"국제금|금현물|금선물|귀금속|숏|선물지수|롱숏")
# 해외/글로벌 제외
_FOREIGN = re.compile(
    r"미국|나스닥|S&P|다우|차이나|중국|일본|인도|베트남|글로벌|선진|신흥|유럽|아세안|"
    r"대만|필라델피아|월배당|브라질|멕시코|독일|아시아|APAC|리츠|한중|한·중|CSI")
# 국내 주식 지수만
_DOMIDX = re.compile(r"코스피|코스닥|KRX|FnGuide|iSelect|KEDI|MSCI Korea|코리아|밸류업|Fn |그룹|WISE|KAP|에프앤")

# 시장대표(정통 시가총액 가중) 지수 → (분류, 정기변경 라벨, months, 설명)
_MARKET_REP = [
    (re.compile(r"코스피\s?200(?!\s?동일|.*비중상한)"), "6·12월 D+1", [6, 12], "코스피200 표준 정기변경(6·12월 선물만기, 자동추정)"),
    (re.compile(r"코스닥\s?150"), "6·12월 D+1", [6, 12], "코스닥150 표준 정기변경(6·12월, 자동추정)"),
    (re.compile(r"코스피\s?100"), "6·12월 D+1", [6, 12], "코스피100 표준 정기변경(자동추정)"),
    (re.compile(r"코스피\s?50"), "6·12월 D+1", [6, 12], "코스피50 표준 정기변경(자동추정)"),
    (re.compile(r"MSCI\s?Korea"), "2·5·8·11월 말", [2, 5, 8, 11], "MSCI 분기 리뷰(2·5·8·11월, 자동추정)"),
    (re.compile(r"밸류업"), "6월 D+1, 연 1회", [6], "코리아 밸류업 지수 정기변경(6월, 자동추정)"),
    (re.compile(r"코리아\s?TOP\s?10"), "3·9월 D+2", [3, 9], "코리아TOP10 정기변경(3·9월, 자동추정)"),
    (re.compile(r"^코스피$|코스피\s?지수|유가증권"), "수시", [], "유가증권시장 전 종목 지수 — 수시 반영(자동추정)"),
]
# 시장대표로 보되 섹터 성격(코스피200 섹터지수 등)
_SECTOR_HINT = re.compile(r"정보기술|헬스케어|금융|산업재|소재|경기소비재|필수소비재|커뮤니케이션|에너지화학|철강|은행|증권|보험|자동차|건설|중공업")


def passes(row, mincap: float = MINCAP_DEFAULT) -> bool:
    """국내주식형 패시브 + 8대 브랜드 + 시총 필터."""
    if row["market_cap"] < mincap:
        return False
    name, idx = row["name"], row["index_indicator_name"]
    if name.split(" ", 1)[0].upper() not in BIG8:
        return False
    if _EXC.search(name):
        return False
    if _FOREIGN.search(name) or _FOREIGN.search(idx):
        return False
    if not _DOMIDX.search(idx):
        return False
    return True


def market_rep(index_name: str):
    for pat, label, months, detail in _MARKET_REP:
        if pat.search(index_name):
            return label, months, detail
    return None


def classify(name: str, index_name: str) -> tuple[str, bool]:
    """(category, is_market_rep). 자동은 시장대표/섹터/테마 3분류만."""
    if market_rep(index_name):
        if _SECTOR_HINT.search(index_name) and "코스피" in index_name:
            return "섹터", True    # 코스피200 섹터지수 등도 복제형(시총가중)
        return "시장대표", True
    if _SECTOR_HINT.search(index_name) or _SECTOR_HINT.search(name):
        return "섹터", False
    return "테마", False


def auto_record(row: dict) -> dict:
    """비큐레이션 ETF 의 자동 메타(정기변경·분류)."""
    name, idx = row["name"], row["index_indicator_name"]
    cat, is_mkt = classify(name, idx)
    mr = market_rep(idx)
    if mr:
        label, months, detail = mr
    else:
        label, months, detail = "정기변경일 확인 요", None, "지수 방법론에 따름 — 개별 확인 필요(자동)"
    return {
        "name": name,
        "manager": name.split(" ", 1)[0].upper(),
        "category": cat,
        "is_theme": cat != "시장대표",
        "schedule_label": label,
        "schedule_detail": detail,
        "months": months,             # None 이면 '미확인'
        "auto": True,
    }
