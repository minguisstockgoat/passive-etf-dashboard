# -*- coding: utf-8 -*-
"""
운용사별 ETF 구성종목(PDF) 수집기.

세 운용사의 서로 다른 엔드포인트를 하나의 공통 스키마(Holding)로 정규화한다.
브라우저 네트워크 분석으로 확인한 공개 엔드포인트를 사용 (인증 불필요).

- TIGER : POST .../pdfListAjax.ajax   (ksdFund=ISIN, fixDate=YYYY.MM.DD)   과거조회 O
- SOL   : GET  /api/etf/pds/pdf/{FUND_CD}  (JSON)                          최신만
- RISE  : POST /prod/finder/productViewSearchTabJquery3 (fundCd, searchDate) 과거조회 O
"""
from __future__ import annotations
import re
import json
import datetime as dt
from dataclasses import dataclass, asdict
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import UA, REQUEST_TIMEOUT

# ---------------------------------------------------------------------------
# 공통 스키마
# ---------------------------------------------------------------------------
@dataclass
class Holding:
    stock_code: str      # 종목코드 (KRX 6자리 / ISIN / 특수코드)
    stock_name: str      # 종목명
    shares: float        # 보유 수량(주/계약)
    amount: float        # 평가금액(원)
    weight: float        # 구성비중(%)


def _num(s) -> float:
    """'1,079,884,000' / '36.68' / '99.64%' -> float"""
    if s is None:
        return 0.0
    s = str(s).strip().replace(",", "").replace("%", "").replace("주", "").replace("좌", "")
    if s in ("", "-", "N/A"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        m = re.search(r"-?\d+(\.\d+)?", s)
        return float(m.group()) if m else 0.0


def _code(c) -> str:
    """KRX 주식 ISIN(KR7 + 6자리 티커 + 검증자리) -> 6자리 티커. 그 외(현금/스왑/해외)는 원본 유지."""
    c = str(c or "").strip()
    if len(c) == 12 and c.startswith("KR7"):
        return c[3:9]
    return c


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.verify = False
    return s


# ---------------------------------------------------------------------------
# KRX 종목 파인더 (전 ETF: 공식명 <-> ISIN <-> 티커)  — 공개 엔드포인트
# ---------------------------------------------------------------------------
def krx_etf_universe() -> list[dict]:
    """KRX 정보데이터시스템 파인더에서 전체 ETF(full_code=ISIN, short_code=티커, codeName=공식명)."""
    s = _session()
    r = s.post(
        "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
        data={"bld": "dbms/comm/finder/finder_secuprodisu", "mktsel": "ALL",
              "typeNo": "0", "searchText": ""},
        headers={"Referer": "https://data.krx.co.kr/", "X-Requested-With": "XMLHttpRequest"},
        timeout=REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    block = r.json().get("block1", [])
    return [{"isin": x["full_code"], "ticker": x["short_code"], "name": x["codeName"]} for x in block]


# ---------------------------------------------------------------------------
# TIGER (미래에셋)
# ---------------------------------------------------------------------------
class TigerFetcher:
    BASE = "https://investments.miraeasset.com/tigeretf/ko/product/search/detail"

    def __init__(self):
        self.s = _session()

    def info(self, isin: str) -> dict:
        """TIGER 개요: 벤치마크(기초지수)/상장일/총보수/순자산 (상세페이지 텍스트 파싱)."""
        r = self.s.get(f"{self.BASE}/index.do", params={"ksdFund": isin}, timeout=REQUEST_TIMEOUT)
        txt = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
        d = {}
        m = re.search(r"벤치마크\s+(.+?)\s+거래량", txt)
        if m:
            idx = re.sub(r"\s*\((?:Price Return|PR|Total Return|TR|Net Return|NR)\)", "", m.group(1)).strip()
            d["index_name"] = idx
        m = re.search(r"상장일\s+(\d{4}[-.]\d{2}[-.]\d{2})", txt)
        if m:
            d["listing"] = m.group(1).replace(".", "-")
        m = re.search(r"총보수[^0-9]{0,6}연?\s*([\d.]+)\s*%", txt)
        if m:
            d["fee"] = m.group(1)
        m = re.search(r"순\s?자산\s?규모\s+([\d,]+)\s*억", txt)
        if m:
            d["aum"] = m.group(1) + "억원"
        return d

    def latest_date(self, isin: str) -> Optional[dt.date]:
        """TIGER 최신 기준일 (pdf.ajax 컨테이너의 fixDate)."""
        try:
            r = self.s.post(f"{self.BASE}/pdf.ajax", data={"ksdFund": isin},
                            headers={"X-Requested-With": "XMLHttpRequest",
                                     "Referer": f"{self.BASE}/index.do?ksdFund={isin}",
                                     "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                            timeout=REQUEST_TIMEOUT)
            m = re.search(r'fixDate"[^>]*value="(\d{4})\.(\d{2})\.(\d{2})"', r.text)
            if not m:
                m = re.search(r'fixDate=(\d{4})(\d{2})(\d{2})', r.text)
            if m:
                return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
        return None

    def fetch(self, isin: str, date: Optional[dt.date] = None) -> list[Holding]:
        """isin=ksdFund(KR7...). date=None이면 최신."""
        data = {"ksdFund": isin, "listCnt": "1000", "pageIndex": "1", "firstIndex": "0"}
        if date is not None:
            data["fixDate"] = date.strftime("%Y.%m.%d")
        r = self.s.post(
            f"{self.BASE}/pdfListAjax.ajax", data=data,
            headers={"X-Requested-With": "XMLHttpRequest",
                     "Referer": f"{self.BASE}/index.do?ksdFund={isin}",
                     "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return self._parse(r.text)

    @staticmethod
    def _parse(html: str) -> list[Holding]:
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for tr in soup.select("tr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            code = tds[0].get_text(strip=True)
            name = tds[1].get_text(strip=True)
            shares = _num(tds[2].get_text())
            amount = _num(tds[3].get_text())
            weight = _num(tds[4].get_text())
            if not name:
                continue
            out.append(Holding(_code(code) or name, name, shares, amount, weight))
        return out


# ---------------------------------------------------------------------------
# SOL (신한)  — 최신 구성종목만 제공
# ---------------------------------------------------------------------------
def derive_method(name: str, index_name: str = "") -> str:
    """ETF명 키워드로 종목 구성방식 요약 도출."""
    n = name or ""
    parts = []
    if "레버리지" in n:
        parts.append("기초지수 일간수익률의 2배(2X)를 추종하는 레버리지 ETF(파생 활용)")
    elif "인버스2X" in n or "인버스2배" in n:
        parts.append("기초지수 일간수익률의 -2배를 추종하는 인버스 ETF")
    elif "인버스" in n:
        parts.append("기초지수 일간수익률을 역방향(-1배)으로 추종하는 인버스 ETF")
    elif ("액티브" in n) or ("플러스" in n):
        parts.append("기초지수를 비교지수로 삼되 운용역 재량으로 초과종목을 담는 액티브 ETF")
    else:
        parts.append("기초지수 구성종목을 지수 비중대로 복제하는 패시브(인덱스) ETF")
    m = re.search(r"TOP\s?(\d+)", n, re.I)
    if m:
        parts.append(f"테마 내 대표·상위 {m.group(1)}종목 중심 구성")
    if "소부장" in n:
        parts.append("반도체 소재·부품·장비(소부장) 기업 중심")
    if "TOP2플러스" in n or "TOP3플러스" in n:
        parts.append("핵심 상위종목을 고비중으로 집중 편입")
    return " · ".join(parts)


class SolFetcher:
    BASE = "https://www.soletf.com"

    def __init__(self):
        self.s = _session()
        self._list = None

    def info(self, fund_cd: str) -> dict:
        for it in self.list_products():
            if str(it.get("FUND_CD")) == str(fund_cd):
                return {
                    "index_name": it.get("BASE_ASSET"),
                    "index_desc": it.get("BASE_ASSET_DESCRIPTION"),
                    "fee": it.get("TOTAL_FEE"), "cu": it.get("SET_UNIT"),
                }
        return {}

    def list_products(self) -> list[dict]:
        """SOL 전 ETF: ETF_CD6(티커), FUND_CD(펀드코드), ETF_NAME. (캐시)"""
        if self._list is not None:
            return self._list
        out, page = [], 1
        while True:
            r = self.s.get(f"{self.BASE}/api/etf/pds", params={"searchText": "", "page": page},
                           headers={"X-Requested-With": "XMLHttpRequest",
                                    "Referer": f"{self.BASE}/ko/fund/etf/pds"},
                           timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            j = r.json()
            items = j.get("items", [])
            if not items:
                break
            out.extend(items)
            total_pages = j.get("toalPage") or j.get("totalPage") or 1
            if page >= total_pages:
                break
            page += 1
        self._list = out
        return out

    def fetch(self, fund_cd: str, date: Optional[dt.date] = None) -> tuple[list[Holding], str]:
        """SOL 은 과거조회 미지원 -> date 인자는 무시. (holdings, work_dt) 반환."""
        r = self.s.get(f"{self.BASE}/api/etf/pds/pdf/{fund_cd}",
                       headers={"X-Requested-With": "XMLHttpRequest",
                                "Referer": f"{self.BASE}/ko/fund/etf/pds"},
                       timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        j = r.json()
        work_dt = j.get("workDt", "")
        out = []
        for it in j.get("items", []):
            code = str(it.get("STOCK_CODE") or it.get("SEC_NM") or "")
            name = str(it.get("SEC_NM", ""))
            # '100%현금설정액' 등 설정 총액 요약행(CASH00000001) 제외
            if code.upper() == "CASH00000001" or name.replace(" ", "").endswith("현금설정액"):
                continue
            out.append(Holding(
                stock_code=_code(code),
                stock_name=name,
                shares=_num(it.get("QTY")),
                amount=_num(it.get("PRICE")),
                weight=_num(it.get("WT_DISP")),
            ))
        return out, work_dt


# ---------------------------------------------------------------------------
# RISE (KB)  — 과거조회 지원(searchDate). 세션 쿠키 필요.
# ---------------------------------------------------------------------------
class RiseFetcher:
    BASE = "https://www.riseetf.co.kr"

    def __init__(self):
        self.s = _session()
        self._warmed = set()   # rise_code 별 세션 워밍업 1회만

    def search(self, query: str) -> list[dict]:
        """RISE 파인더 검색 결과 카드(card_type02)에서 (rise_code, name) 추출.
        추천상품 캐러셀(.section)이 아닌 실제 검색결과 카드만 대상으로 한다."""
        r = self.s.get(f"{self.BASE}/prod/finder", params={"searchText": query, "page": 1},
                       headers={"X-Requested-With": "XMLHttpRequest"}, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        out, seen = [], set()
        for card in soup.select(".card_type02"):
            a = card.select_one('a[href*="/prod/finderDetail/"]')
            if not a:
                continue
            m = re.search(r"/prod/finderDetail/([A-Za-z0-9]{3,8})", a.get("href", ""))
            if not m:
                continue
            code = m.group(1)
            # 카드 내 'RISE ...' 로 시작하는 종목명 링크 텍스트
            name = ""
            for aa in card.select('a[href*="/prod/finderDetail/"]'):
                t = re.sub(r"\s+", " ", aa.get_text(" ", strip=True)).strip()
                if t.startswith("RISE"):
                    name = t
                    break
            if code in seen or not name:
                continue
            seen.add(code)
            out.append({"rise_code": code, "name": name})
        return out

    def _warmup(self, rise_code: str) -> Optional[dt.date]:
        """detail 페이지 GET(세션쿠키) + datepicker_pdf 최신 기준일 파싱."""
        r = self.s.get(f"{self.BASE}/prod/finderDetail/{rise_code}",
                       headers={"Referer": f"{self.BASE}/prod/finder"}, timeout=REQUEST_TIMEOUT)
        m = re.search(r'id="datepicker_pdf"[^>]*value="(\d{4})-(\d{2})-(\d{2})"', r.text)
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None

    def latest_date(self, rise_code: str) -> Optional[dt.date]:
        d = self._warmup(rise_code)
        self._warmed.add(rise_code)
        return d

    def info(self, rise_code: str) -> dict:
        """RISE 개요: 기초지수/상장일/설정단위/순자산/총보수 (기본정보 표 파싱)."""
        r = self.s.get(f"{self.BASE}/prod/finderDetail/{rise_code}", timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(r.text, "html.parser")
        d = {}
        for t in soup.select("table"):
            txt = t.get_text(" ", strip=True)
            if "기초지수" in txt and ("상장일" in txt or "설정단위" in txt):
                ths = [re.sub(r"툴팁 열기", "", th.get_text(" ", strip=True)).strip() for th in t.select("th")]
                tds = [td.get_text(" ", strip=True) for td in t.select("td")]
                kv = dict(zip(ths, tds))
                d["index_name"] = next((v for k, v in kv.items() if "기초지수" in k), None)
                d["listing"] = next((v for k, v in kv.items() if "상장일" in k), None)
                d["cu"] = next((v for k, v in kv.items() if "설정단위" in k), None)
                aum = next((v for k, v in kv.items() if "순 자산" in k or "순자산" in k), None)
                if aum and aum.replace(",", "").isdigit():
                    d["aum"] = f"{round(int(aum.replace(',', '')) / 1e8):,}억원"
                break
        # 총보수: 별도 보수 표(헤더 '총보수(%)')에서 값 추출
        for t in soup.select("table"):
            if "총보수" in t.get_text():
                ths = [th.get_text(" ", strip=True) for th in t.select("th")]
                tds = [td.get_text(" ", strip=True) for td in t.select("td")]
                fee = next((tds[i] for i, h in enumerate(ths) if "총보수" in h and i < len(tds)), None)
                fm = re.search(r"(\d+\.\d+)", fee) if fee else None
                if fm:
                    d["fee"] = fm.group(1)
                    break
        if "fee" not in d:
            m = re.search(r"총보수[^0-9%]{0,6}연?\s*([\d.]+)\s*%", r.text)
            if m:
                d["fee"] = m.group(1)
        return d

    def fetch(self, rise_code: str, date: Optional[dt.date] = None) -> list[Holding]:
        if rise_code not in self._warmed:      # 세션쿠키/최신일 확보 1회
            self._warmup(rise_code)
            self._warmed.add(rise_code)
        data = {"fundCd": rise_code}
        if date is not None:
            data["searchDate"] = date.strftime("%Y-%m-%d")
        r = self.s.post(f"{self.BASE}/prod/finder/productViewSearchTabJquery3", data=data,
                        headers={"X-Requested-With": "XMLHttpRequest",
                                 "Referer": f"{self.BASE}/prod/finderDetail/{rise_code}",
                                 "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                        timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return self._parse(r.text)

    @staticmethod
    def _parse(html: str) -> list[Holding]:
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for tr in soup.select("tr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            name = tds[0].get_text(strip=True)
            code = tds[1].get_text(strip=True)
            shares = _num(tds[2].get_text())
            weight = _num(tds[3].get_text())
            amount = _num(tds[4].get_text())
            if not name or not code:
                continue
            # '설정현금액' 총액 요약행(비중 100, 코드 CASH00000001) 제외
            if code.upper().startswith("CASH") and weight >= 99.999 and name.replace(" ", "") == "설정현금액":
                continue
            out.append(Holding(_code(code), name, shares, amount, weight))
        return out


# ---------------------------------------------------------------------------
# KODEX (삼성)  — samsungfund.com 공개 API. ticker→내부 fId 매핑 후 조회.
# ---------------------------------------------------------------------------
class KodexFetcher:
    BASE = "https://www.samsungfund.com/api/v1/kodex"

    def __init__(self):
        self.s = _session()
        self._map = None   # stkTicker -> fId

    def _load_map(self):
        if self._map is not None:
            return self._map
        m = {}
        for page in range(1, 40):
            r = self.s.get(f"{self.BASE}/product.do",
                           params={"ordrColm": "YIELD_WEEK", "ordrSort": "DESC",
                                   "pageNo": page, "srchTerm": "w", "pageRows": 100},
                           timeout=REQUEST_TIMEOUT)
            lst = r.json()
            if not lst:
                break
            for it in lst:
                t = str(it.get("stkTicker") or "").strip()
                if t:
                    m[t] = it.get("fId")
        self._map = m
        return m

    def fid(self, ticker: str) -> Optional[str]:
        return self._load_map().get(str(ticker))

    def fetch(self, ticker: str, date: Optional[dt.date] = None) -> tuple[list[Holding], str]:
        fid = self.fid(ticker)
        if not fid:
            raise RuntimeError(f"KODEX fId 미발견: {ticker}")
        gijun = (date or dt.date.today()).strftime("%Y.%m.%d")
        import time, random
        time.sleep(1.4 + random.random())            # 요청 간 간격(429 예방)
        r = None
        for attempt in range(6):                     # 429 rate-limit 완화(지수 백오프)
            r = self.s.get(f"{self.BASE}/product-pdf/{fid}.do", params={"gijunYMD": gijun},
                           timeout=REQUEST_TIMEOUT)
            if r.status_code != 429:
                break
            time.sleep(4 * (attempt + 1) + random.random())
        r.raise_for_status()
        pdf = (r.json() or {}).get("pdf", {}) or {}
        asof = pdf.get("gijunYMD", "")
        out = []
        for it in pdf.get("list", []) or []:
            ratio = it.get("ratio")
            name = str(it.get("secNm", "")).strip()
            code = str(it.get("itmNo", "")).strip()
            if ratio is None:                       # 원화예금 등 현금행
                continue
            if code in ("KRD010010001",) or name.replace(" ", "").endswith("예금"):
                continue
            out.append(Holding(_code(code) or name, name,
                               _num(it.get("applyQ")), _num(it.get("evalA")), _num(ratio)))
        return out, asof


# ---------------------------------------------------------------------------
# KIWOOM (키움)  — kiwoometf.com 공개 AJAX. ticker 직접 사용.
# ---------------------------------------------------------------------------
class KiwoomFetcher:
    BASE = "https://www.kiwoometf.com"

    def __init__(self):
        self.s = _session()

    def fetch(self, ticker: str, date: Optional[dt.date] = None) -> tuple[list[Holding], str]:
        start = (date or dt.date.today()).strftime("%Y%m%d")
        r = self.s.post(f"{self.BASE}/service/etf/KO02010200MAjax4",
                        data={"schGubun1": ticker, "startDate": start},
                        headers={"X-Requested-With": "XMLHttpRequest",
                                 "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                        timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        j = r.json() or {}
        rows = j.get("pdfList", []) or []
        asof = (rows[0].get("businessDate") if rows else "") or ""
        asof = str(asof).replace(".", "-")           # 2026.07.13 -> 2026-07-13
        out = []
        for it in rows:
            name = str(it.get("itemTitle", "")).strip()
            code = str(it.get("gcode") or it.get("itemCode") or "").strip()
            weight = _num(it.get("ratio"))
            if not name or code.upper().startswith("CASH") or code == "KRD010010001":
                continue
            out.append(Holding(_code(code) or name, name,
                               _num(it.get("volume")), _num(it.get("assessment")), weight))
        return out, asof


# ---------------------------------------------------------------------------
# ACE (한국투자)  — papi.aceetf.co.kr 공개 JSON API.
# ---------------------------------------------------------------------------
class AceFetcher:
    API = "https://papi.aceetf.co.kr/api"
    REF = "https://www.aceetf.co.kr/"

    def __init__(self):
        self.s = _session()
        self.s.headers.update({"Referer": self.REF})
        self._map = None   # ticker6 -> fundCd

    def _load_map(self):
        if self._map is not None:
            return self._map
        r = self.s.get(f"{self.API}/funds", params={"page": 1, "size": 1000}, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        j = r.json()
        funds = (j.get("data") or j.get("funds") or j.get("content") or j.get("list")
                 or (j if isinstance(j, list) else []))
        m = {}
        for it in funds:
            isin = str(it.get("stockCd") or it.get("isin") or "")
            fc = it.get("fundCd") or it.get("fund_cd")
            if len(isin) == 12 and isin.startswith("KR7") and fc:
                m[isin[3:9]] = fc
        self._map = m
        return m

    def fetch(self, ticker: str, date: Optional[dt.date] = None) -> tuple[list[Holding], str]:
        fc = self._load_map().get(str(ticker))
        if not fc:
            raise RuntimeError(f"ACE fundCd 미발견: {ticker}")
        params = {"page": 1, "size": 1000}
        if date is not None:
            params["std_dt"] = date.strftime("%Y%m%d")
        r = self.s.get(f"{self.API}/funds/{fc}/pdf", params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        j = r.json()
        rows = j.get("pdfList") or j.get("content") or []
        asof = ""
        out = []
        for it in rows:
            name = str(it.get("sec_NM") or it.get("secNm") or "").strip()
            code = str(it.get("jm_KSC_CD") or it.get("jmKscCd") or "").strip()
            wg = _num(it.get("wg"))
            asof = asof or str(it.get("std_DT") or it.get("stdDt") or "")
            if not name or code.upper().startswith("KRD") or name.replace(" ", "").endswith("예금"):
                continue
            out.append(Holding(_code(code) or name, name,
                               _num(it.get("cu_ITEM_CNT") or it.get("cuItemCnt")),
                               _num(it.get("val_AM") or it.get("valAm")), wg))
        if len(asof) == 8 and asof.isdigit():
            asof = f"{asof[:4]}-{asof[4:6]}-{asof[6:]}"
        return out, asof


# ---------------------------------------------------------------------------
# PLUS (한화)  — plusetf.co.kr 공개 JSON API. ticker→내부 product code(n) 매핑.
# ---------------------------------------------------------------------------
class PlusFetcher:
    BASE = "https://www.plusetf.co.kr"

    def __init__(self):
        self.s = _session()
        self._name2n = None

    def _load_map(self):
        """제품 개요 페이지에서 (상품명 -> n) 매핑."""
        if self._name2n is not None:
            return self._name2n
        r = self.s.get(f"{self.BASE}/product/overview", timeout=REQUEST_TIMEOUT)
        m = {}
        for mt in re.finditer(r'/product/detail\?n=(\d+)"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{2,40})', r.text):
            n, nm = mt.group(1), re.sub(r"\s+", " ", mt.group(2)).strip()
            if nm.upper().startswith("PLUS"):
                m.setdefault(nm.replace(" ", ""), n)
        self._name2n = m
        return m

    def n_of(self, name: str) -> Optional[str]:
        return self._load_map().get(name.replace(" ", ""))

    def fetch(self, name: str, date: Optional[dt.date] = None) -> tuple[list[Holding], str]:
        n = self.n_of(name)
        if not n:
            raise RuntimeError(f"PLUS n 미발견: {name}")
        cands = [date] if date else []
        d0 = dt.date.today()
        cands += [d0 - dt.timedelta(days=i) for i in range(0, 6)]
        for d in cands:
            if d is None or d.weekday() >= 5:
                continue
            r = self.s.get(f"{self.BASE}/api/v1/product/pdf/list",
                           params={"n": n, "page": 0, "pageSize": 1000, "d": d.strftime("%Y%m%d")},
                           headers={"Referer": f"{self.BASE}/product/detail?n={n}"},
                           timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                continue
            content = (r.json() or {}).get("content") or []
            if content:
                out = []
                asof = ""
                for it in content:
                    nm = str(it.get("jmNm") or "").strip()
                    code = str(it.get("jmCd") or "").strip()
                    asof = asof or str(it.get("wkdate") or "")
                    if not nm or code.upper().startswith("KRD") or nm.replace(" ", "").endswith("예금"):
                        continue
                    out.append(Holding(_code(code) or nm, nm, _num(it.get("amount")),
                                       0.0, _num(it.get("ratio"))))
                if len(asof) == 8 and asof.isdigit():
                    asof = f"{asof[:4]}-{asof[4:6]}-{asof[6:]}"
                return out, asof
        raise RuntimeError(f"PLUS 데이터 없음: {name}")


# ---------------------------------------------------------------------------
# HANARO (NH아문디)  — hanaroetf.com 공개. 검색→uid, holdings 는 HTML tr.
# ---------------------------------------------------------------------------
class HanaroFetcher:
    BASE = "https://www.hanaroetf.com"

    def __init__(self):
        self.s = _session()
        self._uid = {}   # name -> uid

    def uid_of(self, name: str) -> Optional[str]:
        if name in self._uid:
            return self._uid[name]
        import urllib.parse
        r = self.s.get(f"{self.BASE}/api/v1/fund/get-fund-search-list",
                       params={"pageNo": 1, "searchWord": name}, timeout=REQUEST_TIMEOUT)
        uid = None
        for mt in re.finditer(r'data-fund-name="([^"]+)"[^>]*>.*?/fund/([0-9A-Fa-f]{12,20})',
                              r.text, re.S):
            if mt.group(1).replace(" ", "") == name.replace(" ", ""):
                uid = mt.group(2); break
        if uid is None:
            m = re.search(r'/fund/([0-9A-Fa-f]{12,20})', r.text)
            uid = m.group(1) if m else None
        self._uid[name] = uid
        return uid

    def fetch(self, name: str, date: Optional[dt.date] = None) -> tuple[list[Holding], str]:
        uid = self.uid_of(name)
        if not uid:
            raise RuntimeError(f"HANARO uid 미발견: {name}")
        cands = [date] if date else []
        d0 = dt.date.today()
        cands += [d0 - dt.timedelta(days=i) for i in range(0, 6)]
        for d in cands:
            if d is None or d.weekday() >= 5:
                continue
            r = self.s.get(f"{self.BASE}/api/v1/fund/{uid}/get-fund-holdings-list",
                           params={"baseDate": d.strftime("%Y-%m-%d")},
                           headers={"Referer": f"{self.BASE}/fund/{uid}"}, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200 or "<tr" not in r.text:
                continue
            out = self._parse(r.text)
            if out:
                return out, d.isoformat()
        raise RuntimeError(f"HANARO 데이터 없음: {name}")

    @staticmethod
    def _parse(html: str) -> list[Holding]:
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for tr in soup.select("tr"):
            tds = tr.find_all(["td", "th"])      # 종목명은 <th scope="row">
            if len(tds) < 5:
                continue
            cells = [td.get_text(strip=True) for td in tds]
            # rank, ISIN, 종목명, 수량, 평가금액, 비중  (rank 유무 대비 유연 파싱)
            isin = next((c for c in cells if re.fullmatch(r"KR7[0-9A-Z]{9}", c)), None)
            if not isin:
                continue
            i = cells.index(isin)
            name = cells[i + 1] if i + 1 < len(cells) else ""
            shares = _num(cells[i + 2]) if i + 2 < len(cells) else 0
            amount = _num(cells[i + 3]) if i + 3 < len(cells) else 0
            weight = _num(cells[i + 4]) if i + 4 < len(cells) else 0
            if not name or name.replace(" ", "").endswith("예금"):
                continue
            out.append(Holding(_code(isin), name, shares, amount, weight))
        return out


if __name__ == "__main__":
    # 파싱 스모크 테스트
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    y = dt.date(2026, 7, 9)

    print("--- TIGER 반도체 (KR7091230003) ---")
    for h in TigerFetcher().fetch("KR7091230003", y)[:4]:
        print(" ", h)

    print("--- SOL 210367 ---")
    hs, wd = SolFetcher().fetch("210367")
    print("  workDt", wd)
    for h in hs[:4]:
        print(" ", h)

    print("--- RISE 44A9 (미국나스닥100) ---")
    for h in RiseFetcher().fetch("44A9", y)[:4]:
        print(" ", h)
