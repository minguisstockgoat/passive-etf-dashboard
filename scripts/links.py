# -*- coding: utf-8 -*-
"""
ETF 외부 링크 빌더 → data/links.json

두 종류의 링크를 ETF 별로 만든다.

1) 운용사 링크
   - product : 운용사 공식 상품 상세페이지
   - pdf     : 그 상품의 구성종목(PDF) 화면 (탭·앵커까지 잡히면 그쪽으로)
   대시보드의 구성종목 표는 하루 한 번 받아둔 스냅샷이라 기준일이 하루 밀릴 수 있다.
   PDF 를 '지금 이 순간' 기준으로 봐야 할 때 이 링크로 운용사 원문을 바로 연다.

2) 기초지수 링크
   - index : 지수 산출기관의 지수 페이지. FnGuide/WISE/MKF 계열은 fnindex 지수코드까지
             찾아 개별 지수 상세페이지로 바로 꽂고(deep=True), 나머지는 산출기관 대표
             페이지로 보낸다(deep=False).

URL 패턴은 전부 각 사이트에서 직접 확인한 것이다(2026-08-31).
  TIGER  investments.miraeasset.com/tigeretf/ko/product/search/detail/index.do?ksdFund={ISIN}  (#section7 = 자산 구성)
  SOL    soletf.com/ko/fund/etf/{FUND_CD}                        (?tabIndex=3 = 구성종목(PDF))
  RISE   riseetf.co.kr/prod/finderDetail/{rise_code}
  KODEX  samsungfund.com/etf/product/view.do?id={fId}
  KIWOOM kiwoometf.com/service/etf/KO02010200M?gcode={ticker}
  ACE    aceetf.co.kr/fund/{fundCd}
  PLUS   plusetf.co.kr/product/detail?n={n}
  HANARO hanaroetf.com/fund/{uid}
  지수   fnindex.co.kr/overview/info/{IDX_CD}

운용사 내부코드(FUND_CD·fId·uid…) 해석은 네트워크 비용이 있어 data/links.json 에 캐시한다.
이미 캐시된 티커는 건너뛰므로 매일 돌려도 신규 상장분만 조회한다.
"""
from __future__ import annotations
import os, re, sys, json

sys.stdout.reconfigure(encoding="utf-8")
import urllib3
urllib3.disable_warnings()

import requests
from config import UA, REQUEST_TIMEOUT

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OUT = os.path.join(DATA, "links.json")

# ---------------------------------------------------------------------------
# 지수 산출기관 (fnindex 로 개별 지수까지 못 잡을 때의 대표 페이지)
# ---------------------------------------------------------------------------
PROVIDERS = {
    "FnGuide": ("FnGuide 지수", "https://www.fnindex.co.kr/overview/info/MIS"),
    "WISE":    ("WISE 인덱스", "https://www.wiseindex.com/Index/Index"),
    "KRX":     ("KRX 지수 (전체지수 시세)", "https://index.krx.co.kr/contents/IDX/0101/IDX0101.jsp"),
    "iSelect": ("NH투자증권 iSelect 인덱스", "https://wts.nhsec.com/wts/etn/wts8068.nh"),
    "KEDI":    ("한국경제 KEDI 지수", "https://www.kedindex.com/underlying/equity"),
    "MSCI":    ("MSCI Indexes", "https://www.msci.com/indexes"),
    "Akros":   ("Akros 지수", "https://www.akrostec.com/"),
}


def guess_provider(index_name: str) -> str:
    n = str(index_name or "")
    u = n.upper()
    if u.startswith("KRX") or n.startswith(("코스피", "코스닥", "코리아 밸류업", "코리아밸류업")):
        return "KRX"
    if "ISELECT" in u:
        return "iSelect"
    if "KEDI" in u:
        return "KEDI"
    if "MSCI" in u:
        return "MSCI"
    if u.startswith("AKROS"):
        return "Akros"
    if u.startswith("WISE") or n.startswith("삼성그룹"):
        return "WISE"
    return "FnGuide"          # FnGuide·MKF 및 그 외 기본값


def _nz(s: str) -> str:
    """지수명 정규화 — 수익률 표기·괄호·조사만 다른 이름을 같은 지수로 본다."""
    s = str(s or "").upper()
    s = re.sub(r"\((?:PR|TR|NR|PRICE\s*RETURN|TOTAL\s*RETURN|NET\s*RETURN|"
               r"시장가격|시장가격지수|총수익|가격지수)\)", "", s)
    s = s.replace("플러스", "+").replace("PLUS", "+")
    s = s.replace("지수", "").replace("INDEX", "")
    s = re.sub(r"[\s·\-_&,\.()]", "", s)
    return s


def fnindex_catalog(sess: requests.Session) -> dict:
    """fnindex 전 지수 트리(IDX_CD·IDX_NM) — 아무 페이지에나 통째로 박혀 있다."""
    r = sess.get("https://www.fnindex.co.kr/overview/info/MIS", timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    rows = re.findall(r'\{"IDX_CD":"([^"]+)","IDX_NM":"((?:[^"\\]|\\.)*)"', r.text)
    cat = {}
    for code, name in rows:
        try:
            name = json.loads(f'"{name}"')          # \uXXXX·& 복원
        except Exception:
            pass
        if code.startswith("DIV."):                # 총수익(TR) 계열은 PR 지수 뒤로
            continue
        cat.setdefault(_nz(name), {"code": code, "name": name,
                                   "url": f"https://www.fnindex.co.kr/overview/info/{code}",
                                   "label": "FnGuide 지수 상세"})
    return cat


def wise_catalog(sess: requests.Session) -> dict:
    """WISE 인덱스 트리(/API/Tree/Get?id=4) — 지수코드 노드만 추린다."""
    r = sess.get("https://www.wiseindex.com/API/Tree/Get", params={"id": 4},
                 headers={"X-Requested-With": "XMLHttpRequest"}, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    cat = {}

    def walk(nodes):
        for n in nodes or []:
            key, title = str(n.get("key") or ""), n.get("title") or ""
            # 분류 노드는 key 가 숫자열, 지수 노드는 WMI500·WTI0101 같은 코드
            if title and not key.isdigit():
                cat.setdefault(_nz(title), {
                    "code": key, "name": title,
                    "url": f"https://www.wiseindex.com/Index/Index#/{key}",
                    "label": "WISE 지수 상세"})
            walk(n.get("children"))

    walk(r.json())
    return cat


def lookup(catalog: dict, index_name: str):
    """지수명 → 카탈로그 항목. 정확일치 우선, 없으면 '한쪽이 다른쪽을 포함'하는
    후보가 딱 하나일 때만 채택(길이비 0.6 이상). 느슨한 매칭으로 엉뚱한 지수에
    링크가 걸리는 것보다 산출기관 대표페이지로 보내는 편이 낫다."""
    key = _nz(index_name)
    if not key:
        return None
    if key in catalog:
        return catalog[key]
    hits = [v for k, v in catalog.items()
            if (k in key or key in k) and min(len(k), len(key)) / max(len(k), len(key)) >= 0.6]
    return hits[0] if len(hits) == 1 else None


# ---------------------------------------------------------------------------
# 운용사별 상품 URL
# ---------------------------------------------------------------------------
MGR_LABEL = {
    "TIGER": "미래에셋 TIGER", "KODEX": "삼성 KODEX", "RISE": "KB RISE",
    "SOL": "신한 SOL", "HANARO": "NH아문디 HANARO", "PLUS": "한화 PLUS",
    "ACE": "한국투자 ACE", "KIWOOM": "키움 KIWOOM",
}

# 내부코드를 못 찾았을 때 보낼 운용사 상품 목록/검색 페이지
MGR_FALLBACK = {
    "TIGER": "https://investments.miraeasset.com/tigeretf/ko/product/search/index.do",
    "KODEX": "https://www.samsungfund.com/etf/product/list.do",
    "RISE": "https://www.riseetf.co.kr/prod/finder",
    "SOL": "https://www.soletf.com/ko/fund",
    "HANARO": "https://www.hanaroetf.com/fund",
    "PLUS": "https://www.plusetf.co.kr/product/overview",
    "ACE": "https://www.aceetf.co.kr/fund",
    "KIWOOM": "https://www.kiwoometf.com/service/etf/KO02010100M",
}


def product_urls(mgr: str, code: str) -> tuple[str, str]:
    """(상품페이지, 구성종목(PDF) 페이지). code=운용사 내부코드(없으면 빈 문자열)."""
    if not code:
        u = MGR_FALLBACK.get(mgr, "")
        return u, u
    if mgr == "TIGER":
        u = ("https://investments.miraeasset.com/tigeretf/ko/product/search/detail/index.do"
             f"?ksdFund={code}")
        return u, u + "#section7"                     # 자산 구성 섹션
    if mgr == "SOL":
        u = f"https://www.soletf.com/ko/fund/etf/{code}"
        return u, u + "?tabIndex=3"                   # 구성종목(PDF) 탭
    if mgr == "RISE":
        u = f"https://www.riseetf.co.kr/prod/finderDetail/{code}"
        return u, u
    if mgr == "KODEX":
        u = f"https://www.samsungfund.com/etf/product/view.do?id={code}"
        return u, u
    if mgr == "KIWOOM":
        u = f"https://www.kiwoometf.com/service/etf/KO02010200M?gcode={code}"
        return u, u
    if mgr == "ACE":
        u = f"https://www.aceetf.co.kr/fund/{code}"
        return u, u
    if mgr == "PLUS":
        u = f"https://www.plusetf.co.kr/product/detail?n={code}"
        return u, u
    if mgr == "HANARO":
        u = f"https://www.hanaroetf.com/fund/{code}"
        return u, u
    return "", ""


class CodeResolver:
    """운용사 내부코드 해석기. 목록형 API 는 첫 호출에서만 받아 캐시한다."""

    def __init__(self):
        self._sol = self._kodex = self._ace = self._plus = None
        self._rise = self._hanaro = None

    def resolve(self, mgr: str, etf: dict) -> str:
        t, name, isin = etf["ticker"], etf["name"], etf.get("isin") or ""
        try:
            if mgr == "TIGER":
                return isin
            if mgr == "KIWOOM":
                return t                                   # gcode = 티커
            if mgr == "SOL":
                if self._sol is None:
                    from fetchers import SolFetcher
                    self._sol = {str(x.get("ETF_CD6") or ""): str(x.get("FUND_CD") or "")
                                 for x in SolFetcher().list_products()}
                return self._sol.get(t, "")
            if mgr == "KODEX":
                if self._kodex is None:
                    from fetchers import KodexFetcher
                    self._kodex = KodexFetcher()
                return str(self._kodex.fid(t) or "")
            if mgr == "ACE":
                if self._ace is None:
                    from fetchers import AceFetcher
                    self._ace = AceFetcher()
                return str(self._ace._load_map().get(t, "") or "")
            if mgr == "PLUS":
                if self._plus is None:
                    from fetchers import PlusFetcher
                    self._plus = PlusFetcher()
                return str(self._plus.n_of(name) or "")
            if mgr == "RISE":
                if self._rise is None:
                    from fetchers import RiseFetcher
                    self._rise = RiseFetcher()
                nz = lambda s: str(s or "").upper().replace(" ", "")
                for r in self._rise.search(name):
                    if nz(r["name"]) == nz(name):
                        return r["rise_code"]
                return ""
            if mgr == "HANARO":
                if self._hanaro is None:
                    from fetchers import HanaroFetcher
                    self._hanaro = HanaroFetcher()
                return str(self._hanaro.uid_of(name) or "")
        except Exception as e:
            print(f"    ! {mgr} {name} 코드 해석 실패: {e}")
        return ""


def build(etfs: list, force: bool = False) -> dict:
    """etfs 레코드 리스트 → {ticker: 링크셋}. data/links.json 에 캐시도 남긴다."""
    cache = {}
    if os.path.exists(OUT) and not force:
        try:
            cache = json.load(open(OUT, encoding="utf-8")).get("links", {})
        except Exception:
            cache = {}

    sess = requests.Session()
    sess.headers.update({"User-Agent": UA})
    sess.verify = False
    catalog = {}
    for tag, fn in (("fnindex", fnindex_catalog), ("wiseindex", wise_catalog)):
        try:
            c = fn(sess)
            catalog.update({k: v for k, v in c.items() if k not in catalog})
            print(f"  {tag} 지수 카탈로그 {len(c):,}건")
        except Exception as e:
            print(f"  ! {tag} 카탈로그 실패(대표 페이지로 폴백):", e)

    res = CodeResolver()
    out, deep, resolved = {}, 0, 0
    for e in etfs:
        t, mgr = e["ticker"], e["manager"]
        old = cache.get(t) or {}
        code = old.get("code") or ""
        if not code:
            code = res.resolve(mgr, e)
            if code:
                resolved += 1
        prod, pdf = product_urls(mgr, code)

        idxnm = e.get("index_name") or ""
        prov = guess_provider(idxnm)
        hit = lookup(catalog, idxnm) if prov in ("FnGuide", "WISE") else None
        if hit:
            idx_url, idx_label = hit["url"], hit["label"]
            deep += 1
            if _nz(hit["name"]) != _nz(idxnm):
                print(f"    ~ 유사매칭 {idxnm}  →  {hit['name']}")
        else:
            idx_label, idx_url = PROVIDERS[prov]

        out[t] = {
            "code": code,
            "manager_label": MGR_LABEL.get(mgr, mgr),
            "product": prod,
            "pdf": pdf,
            "pdf_exact": bool(code),                  # 상품 지정 여부(아니면 목록 페이지)
            "index_url": idx_url,
            "index_label": idx_label,
            "index_provider": prov,
            "index_deep": bool(hit),
        }

    payload = {"count": len(out), "index_deep": deep, "links": out}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    miss = [e["name"] for e in etfs if not out[e["ticker"]]["code"]]
    print(f"링크 {len(out)}종 (신규 코드해석 {resolved}) · 지수 상세링크 {deep}종 → data/links.json")
    if miss:
        print(f"  운용사 코드 미해석 {len(miss)}종(상품목록 페이지로 폴백): " + ", ".join(miss[:12])
              + (" …" if len(miss) > 12 else ""))
    return out


def main(force: bool = False):
    etfs = json.load(open(os.path.join(DATA, "etfs.json"), encoding="utf-8"))["etfs"]
    build(etfs, force)


if __name__ == "__main__":
    main(force="--force" in sys.argv)
