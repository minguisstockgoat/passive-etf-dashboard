# -*- coding: utf-8 -*-
"""
운용사별 ETF 구성종목(PDF) 수집기.

운용사마다 다른 엔드포인트를 하나의 공통 스키마(Holding)로 정규화한다.
브라우저 네트워크 분석으로 확인한 공개 엔드포인트를 사용 (인증 불필요).

- TIGER : POST .../pdfListAjax.ajax   (ksdFund=ISIN, fixDate=YYYY.MM.DD)   과거조회 O(2019~)
          ⚠ 2026-07 부터 TLS 지문으로 비브라우저를 차단 → curl_cffi(크롬 흉내) 세션 필요.
            해외 IP(GitHub Actions)는 그래도 403 이라 국내 PC 에서만 받힌다.
- SOL   : GET  /api/etf/pds/pdf/{FUND_CD}  (JSON)  최신 / 과거는 /api/fund/pdfList?fund_cd=&work_dt=
- RISE  : GET  kbam.co.kr/api/products/etfs/{fund_cd}/holdings?download=xlsx&base_dt=YYYYMMDD
          (2026-09 KB자산운용 통합 사이트로 이전, 최근 ~60영업일만 과거조회. 해외 IP 접속 불가)
- KODEX : GET  .../product-pdf/{fId}.do?gijunYMD=YYYY.MM.DD                과거조회 O
- KIWOOM/ACE/PLUS/HANARO : 날짜 파라미터로 과거조회 O
"""
from __future__ import annotations
import io
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


def _browser_session():
    """TLS 지문까지 크롬처럼 보이는 세션(curl_cffi). 미설치면 일반 requests 로 폴백.
    미래에셋(TIGER)은 2026-07 부터 python-requests 의 TLS 핸드셰이크를 끊어버린다."""
    try:
        from curl_cffi import requests as cr
    except ImportError:
        return _session()
    s = cr.Session(impersonate="chrome")
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
        self.s = _browser_session()

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

    def fetch_hist(self, fund_cd: str, date: dt.date) -> tuple[list[Holding], str]:
        """과거 PDF: 상품 페이지 '검색 시작일' 이 쓰는 /api/fund/pdfList (work_dt=YYYYMMDD).
        응답 행마다 WORK_DT 가 찍혀 있어 요청한 날짜인지 확인할 수 있다. 자료가 없으면 []."""
        r = self.s.get(f"{self.BASE}/api/fund/pdfList",
                       params={"fund_cd": fund_cd, "work_dt": date.strftime("%Y%m%d")},
                       headers={"X-Requested-With": "XMLHttpRequest",
                                "Referer": f"{self.BASE}/ko/fund/etf/{fund_cd}?tabIndex=3"},
                       timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        rows = r.json() or []
        work_dt = str(rows[0].get("WORK_DT") or "") if rows else ""
        out = []
        for it in rows:
            code = str(it.get("STOCK_CODE") or it.get("SEC_NM") or "")
            name = str(it.get("SEC_NM", ""))
            if code.upper() == "CASH00000001" or name.replace(" ", "").endswith("현금설정액"):
                continue
            out.append(Holding(_code(code), name, _num(it.get("QTY")), _num(it.get("PRICE")),
                               _num(it.get("WT_DISP"))))
        return out, work_dt

    def fetch(self, fund_cd: str, date: Optional[dt.date] = None) -> tuple[list[Holding], str]:
        """최신 PDF (holdings, work_dt). 과거는 fetch_hist."""
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
# RISE (KB)  — 2026-09 riseetf.co.kr 이 KB자산운용 통합 사이트(kbam.co.kr)로 이전.
#   목록   GET /api/products/etfs?page=N          (krx_cd=티커 → fund_cd)
#   최신일 GET /api/products/etfs/{fund_cd}/holdings  → base_dt, available_dates(최근 ~60영업일)
#   전체   GET .../holdings?download=xlsx&base_dt=YYYYMMDD   (JSON 은 상위 30종만 준다)
#   ⚠ available_dates 밖의 base_dt 는 에러 없이 최신을 돌려준다 → 반드시 목록으로 거른다.
#   ⚠ 해외 IP(GitHub Actions)에서는 접속 자체가 안 된다(connect timeout).
# ---------------------------------------------------------------------------
class RiseFetcher:
    BASE = "https://kbam.co.kr/api/products"

    def __init__(self):
        self.s = _session()
        self._map = None       # 티커 -> fund_cd
        self._meta = {}        # fund_cd -> holdings JSON(최신일·가능일자)

    def etf_map(self) -> dict:
        if self._map is not None:
            return self._map
        m, page = {}, 1
        while True:
            r = self.s.get(f"{self.BASE}/etfs", params={"page": page}, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            j = r.json()
            for it in j.get("page_items") or []:
                if it.get("krx_cd") and it.get("fund_cd"):
                    m[str(it["krx_cd"]).strip()] = str(it["fund_cd"]).strip()
            info = j.get("page_info") or {}
            if not info.get("next_page") or page >= int(info.get("total_page") or 1):
                break
            page += 1
        self._map = m
        return m

    def code_of(self, ticker: str) -> Optional[str]:
        return self.etf_map().get(str(ticker))

    def _holdings_meta(self, fund_cd: str) -> dict:
        if fund_cd not in self._meta:
            r = self.s.get(f"{self.BASE}/etfs/{fund_cd}/holdings", timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            self._meta[fund_cd] = r.json() or {}
        return self._meta[fund_cd]

    @staticmethod
    def _d(s) -> Optional[dt.date]:
        s = str(s or "")
        return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8])) if len(s) == 8 and s.isdigit() else None

    def latest_date(self, fund_cd: str) -> Optional[dt.date]:
        return self._d(self._holdings_meta(fund_cd).get("base_dt"))

    def available_dates(self, fund_cd: str) -> set:
        return {d for d in (self._d(x) for x in self._holdings_meta(fund_cd).get("available_dates") or []) if d}

    def fetch(self, fund_cd: str, date: Optional[dt.date] = None) -> list[Holding]:
        params = {"download": "xlsx"}
        if date is not None:
            if date not in self.available_dates(fund_cd):
                return []                       # 범위 밖이면 최신을 돌려주므로 아예 요청하지 않는다
            params["base_dt"] = date.strftime("%Y%m%d")
        r = self.s.get(f"{self.BASE}/etfs/{fund_cd}/holdings", params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return self._parse_xlsx(r.content)

    @staticmethod
    def _parse_xlsx(blob: bytes) -> list[Holding]:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(blob), read_only=True)
        rows = list(wb.active.iter_rows(values_only=True))
        out = []
        for row in rows[1:]:                    # 헤더: 종목코드·종목명·수량(주)·보유비중(%)·평가금액(원)
            if not row or len(row) < 5 or not row[1]:
                continue
            code, name = str(row[0] or "").strip(), str(row[1]).strip()
            if code.upper().startswith(("CASH", "KRD")) or name.replace(" ", "").endswith(("예금", "현금")):
                continue
            out.append(Holding(_code(code) or name, name, _num(row[2]), _num(row[4]), _num(row[3])))
        return out


# ---------------------------------------------------------------------------
# KODEX (삼성)  — samsungfund.com 공개 API. ticker→내부 fId 매핑 후 조회.
# ---------------------------------------------------------------------------
class KodexFetcher:
    BASE = "https://www.samsungfund.com/api/v1/kodex"

    def __init__(self):
        self.s = _session()
        self._map = None   # stkTicker -> fId
        self._count = 0    # 429 회피용 요청 카운터

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
        # 대량 수집 시 samsungfund 레이트리밋(~8req/window) 회피: 6요청마다 쿨다운
        self._count += 1
        if self._count % 6 == 0:
            time.sleep(62)
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
            nm = nm.replace("&amp;", "&").replace("&#38;", "&")   # HTML 엔티티 복원
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
        # 날짜를 주면 그날만 조회(과거 이력용 — 다른 날로 폴백하면 기준일이 섞인다).
        # 날짜가 없으면 오늘부터 거슬러 올라가며 최신을 찾는다.
        if date is not None:
            cands = [date]
        else:
            d0 = dt.date.today()
            cands = [d0 - dt.timedelta(days=i) for i in range(0, 6)]
        for d in cands:
            if d.weekday() >= 5:
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
        if date is not None:
            return [], ""
        raise RuntimeError(f"PLUS 데이터 없음: {name}")


# ---------------------------------------------------------------------------
# HANARO (NH아문디)  — hanaroetf.com 공개. 검색→uid, holdings 는 HTML tr.
# ---------------------------------------------------------------------------
class HanaroFetcher:
    BASE = "https://www.hanaroetf.com"

    def __init__(self):
        self.s = _session()
        self._uid = {}   # name -> uid
        self._latest = {}  # uid -> 최신 PDF 기준일

    def uid_of(self, name: str) -> Optional[str]:
        if name in self._uid:
            return self._uid[name]

        def nz(s):
            s = str(s or "").replace("&amp;", "&").replace("&#38;", "&")
            return re.sub(r"\s+", "", s).upper()
        target = nz(name)
        # 검색어 후보: HANARO 사이트명은 공백이 다를 수 있어(예: '200 TR') 넓게 검색
        num = re.search(r"\d+", name)
        terms = [name, name.split(" ", 1)[0] + " " + (num.group(0) if num else ""),
                 name.split(" ", 1)[0]]
        uid = None
        for term in terms:
            r = self.s.get(f"{self.BASE}/api/v1/fund/get-fund-search-list",
                           params={"pageNo": 1, "searchWord": term.strip()}, timeout=REQUEST_TIMEOUT)
            for mt in re.finditer(r'data-fund-name="([^"]+)"[^>]*>.*?/fund/([0-9A-Fa-f]{12,20})',
                                  r.text, re.S):
                if nz(mt.group(1)) == target:
                    uid = mt.group(2); break
            if uid:
                break
        self._uid[name] = uid
        return uid

    def latest_date(self, uid: str) -> Optional[dt.date]:
        """상품 페이지 PDF 기준일 입력칸(#pdfDate)의 기본값 = 운용사가 게시한 최신 PDF 날짜."""
        if uid in self._latest:
            return self._latest[uid]
        d = None
        try:
            r = self.s.get(f"{self.BASE}/fund/{uid}", timeout=REQUEST_TIMEOUT)
            m = re.search(r'id="pdfDate".*?value="(\d{4})\.(\d{2})\.(\d{2})"', r.text, re.S)
            if m:
                d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
        self._latest[uid] = d
        return d

    def fetch(self, name: str, date: Optional[dt.date] = None) -> tuple[list[Holding], str]:
        """baseDate 는 'YYYY.MM.DD' 형식이어야 과거조회가 된다. 'YYYY-MM-DD' 로 보내면
        (최신일 외에는) 빈 응답이라 예전 코드는 매번 최신으로 폴백하면서 요청한 날짜를
        기준일로 붙이는 오류가 있었다. 최신 이후 날짜를 주면 조용히 최신을 돌려준다."""
        uid = self.uid_of(name)
        if not uid:
            raise RuntimeError(f"HANARO uid 미발견: {name}")
        latest = self.latest_date(uid)
        if date is not None:
            if latest and date > latest:
                return [], ""
            cands = [date]
        elif latest:
            cands = [latest]
        else:
            d0 = dt.date.today()
            cands = [d0 - dt.timedelta(days=i) for i in range(0, 6)]
        for d in cands:
            if d.weekday() >= 5:
                continue
            r = self.s.get(f"{self.BASE}/api/v1/fund/{uid}/get-fund-holdings-list",
                           params={"baseDate": d.strftime("%Y.%m.%d")},
                           headers={"Referer": f"{self.BASE}/fund/{uid}"}, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200 or "<tr" not in r.text:
                continue
            out = self._parse(r.text)
            if out:
                return out, d.isoformat()
        if date is not None:
            return [], ""
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

    print("--- RISE 200 (kbam 4435) ---")
    rf = RiseFetcher()
    print("  latest", rf.latest_date("4435"))
    for h in rf.fetch("4435")[:4]:
        print(" ", h)
