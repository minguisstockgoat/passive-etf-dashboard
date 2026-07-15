# -*- coding: utf-8 -*-
"""
지수(기초지수)별 정기변경·비중 cap 규칙 — 자동 확장 종목용.

두 소스를 합친다:
1) MARKET_REP: 시장대표/대표지수의 확정 캘린더(코스피200=6·12월, MSCI=분기, 밸류업=6월 등).
   이들은 지수 복제형이라 강제 cap 없음(밸류업만 15%).
2) `_verify/index_rules.json`: 방법론서/투자설명서 조사(리서치 에이전트) 결과.
   {지수명: {cap_type, single_cap, top_n, top_cap, rest_cap, months, schedule, source, confidence}}

build_data 는 비큐레이션 ETF 의 기초지수명으로 여기서 정기변경·cap 을 조회한다.
"""
from __future__ import annotations
import os, re, json

HERE = os.path.dirname(os.path.abspath(__file__))
_JSON = os.path.join(HERE, "_verify", "index_rules.json")

# ── 시장대표 확정 캘린더 (pattern, months, label, detail) ────────────────────
MARKET_REP = [
    (re.compile(r"코스피\s?200"), [6, 12], "6·12월 D+1",
     "코스피200 정기변경(6·12월 선물옵션 만기일 다음 거래일)"),
    (re.compile(r"코스닥\s?150"), [6, 12], "6·12월 D+1", "코스닥150 정기변경(6·12월)"),
    (re.compile(r"코스피\s?100"), [6, 12], "6·12월 D+1", "코스피100 정기변경(6·12월)"),
    (re.compile(r"코스피\s?50(?!\d)"), [6, 12], "6·12월 D+1", "코스피50 정기변경(6·12월)"),
    (re.compile(r"KRX\s?100|KRX\s?300"), [6, 12], "6·12월", "KRX 대표지수 정기변경(6·12월)"),
    (re.compile(r"MSCI\s?Korea"), [2, 5, 8, 11], "2·5·8·11월 말", "MSCI 분기 리뷰(2·5·8·11월)"),
    (re.compile(r"밸류업"), [6], "6월, 연 1회", "코리아 밸류업 지수 정기변경(연 1회 6월)"),
    (re.compile(r"^코스피(\s?TR)?$|코스피 지수"), [], "수시",
     "유가증권시장 전 종목 지수 — 신규상장·상장폐지 수시 반영"),
]


def _replicator_cap():
    return {"single_cap": None, "index_exception": True,
            "label": "기초지수 비중 복제 · 단일종목 상한 없음",
            "source": "자본시장법 시행령 §80(지수 비중까지 예외 허용)", "verified": True,
            "note": "기초지수 시가총액 비중을 그대로 복제. 강제 비중조절 대상 아님(지수 정기변경 시 조정)."}


def _valueup_cap():
    return {"single_cap": 0.15, "index_exception": False, "label": "단일종목 15% 상한",
            "source": "KRX 코리아 밸류업 지수 방법론(개별종목 15%)", "verified": True,
            "note": "개별종목 비중 15% 상한. 정기변경(연 1회 6월) 시 조정."}


# ── 리서치 결과(JSON) → cap dict 변환 ───────────────────────────────────────
def _cap_from_research(r: dict) -> dict:
    ct = (r.get("cap_type") or "none").lower()
    ver = (r.get("confidence") or "low").lower() in ("high", "med", "medium")
    src = r.get("source", "")
    if ct == "none":
        return {"single_cap": None, "index_exception": True,
                "label": "기초지수 비중 복제 · 단일종목 상한 없음",
                "source": src or "지수 방법론(상한 없음)", "verified": ver,
                "note": "시가총액 가중 복제 — 별도 단일종목 상한 없음."}
    if ct == "equal":
        return {"single_cap": None, "index_exception": False,
                "label": "동일가중 방식 · 종목 상한 이슈 없음",
                "source": src, "verified": ver, "note": "동일가중(±틸팅). 단일종목 비중이 낮아 cap 초과 이슈 없음."}
    if ct == "top_n":
        tc = r.get("top_cap")
        return {"single_cap": tc, "index_exception": False, "top_n": r.get("top_n"),
                "top_cap": tc, "rest_cap": r.get("rest_cap"),
                "label": f"상위 {r.get('top_n')}종목 각 {int((tc or 0)*100)}%"
                         + (f" · 나머지 {int(r['rest_cap']*100)}%" if r.get("rest_cap") else ""),
                "source": src, "verified": ver,
                "note": ("상위 종목 상한 기준으로 초과를 계산한다(보수적). " + (r.get("schedule") or ""))}
    # single
    sc = r.get("single_cap")
    return {"single_cap": sc, "index_exception": False,
            "label": f"단일종목 {int((sc or 0)*100)}% 상한" if sc else "비중상한 확인 요",
            "source": src, "verified": ver, "note": r.get("schedule") or ""}


_AGENT = None


def _norm_ix(s: str) -> str:
    """지수명 정규화: (PR)/(Price Return)/(시장가격) 등 괄호·'지수'·공백 제거."""
    s = re.sub(r"\(.*?\)", "", str(s or ""))
    s = s.replace("지수", "").replace("Index", "").replace("index", "")
    return re.sub(r"[\s·]", "", s).upper()


def _load():
    global _AGENT
    if _AGENT is None:
        try:
            raw = json.load(open(_JSON, encoding="utf-8"))
            _AGENT = {_norm_ix(k): v for k, v in raw.items()}
        except Exception:
            _AGENT = {}
    return _AGENT


def resolve_schedule(index_name: str):
    """(months, label, detail, verified) 또는 None."""
    a = _load().get(_norm_ix(index_name))
    if a and a.get("months") is not None:
        ver = (a.get("confidence") or "low").lower() in ("high", "med", "medium")
        return a["months"], a.get("schedule_label") or _label_from_months(a["months"]), \
            a.get("schedule") or "", ver
    for pat, months, label, detail in MARKET_REP:
        if pat.search(index_name):
            return months, label, detail, True
    return None


def resolve_cap(index_name: str):
    """cap dict 또는 None."""
    a = _load().get(_norm_ix(index_name))
    if a and a.get("cap_type"):
        return _cap_from_research(a)
    for pat, months, label, detail in MARKET_REP:
        if pat.search(index_name):
            return _valueup_cap() if "밸류업" in index_name else _replicator_cap()
    return None


def _label_from_months(months):
    if not months:
        return "수시"
    return "·".join(str(m) for m in months) + "월"
