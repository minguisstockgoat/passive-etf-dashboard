# -*- coding: utf-8 -*-
"""
과거 정기변경 이력 → data/rebal/{ticker}.json

정기변경일 전후의 운용사 PDF(CU 구성)를 비교해, 그날 무엇이 바뀌었는지 남긴다.
  - 편입 / 편출 종목
  - 비중 확대·축소 종목과 그 크기(순매매 %p) — cap 상한 때문에 상위 종목을 덜어내고
    하위 종목을 채워 넣는 조정이 여기서 보인다.

어떻게 비교하나
  1) 정기변경 예정 효력일 D 는 rebal_dates 규칙(만기일 D+n 등)으로 과거 달에 대해 계산한다.
  2) D 전후 영업일 창(기본 D-5 ~ D+5, 일정이 자동추정이면 D+12 까지)의 PDF 를 이분 탐색으로
     조회해 '구성이 실제로 바뀐 날'을 찾는다. 운용사마다 PDF 날짜 표기가 달라서다:
     KODEX 는 효력일 전일(D-1) 날짜 PDF 에 이미 새 구성이 반영되고, TIGER·ACE·PLUS·KIWOOM 은
     효력일(D) 날짜 PDF 부터 바뀐다(2026-06 코스피200 정기변경으로 확인).
  3) 바뀌기 직전 PDF(pre)와 바뀐 뒤 PDF(post)를 종목별로 대조한다.

순매매 %p (가격 효과 제거)
  PDF 비중은 주가만 움직여도 매일 변한다. 리밸런싱으로 '사고판 양'만 보려고 CU 보유수량
  변화에 post 시점 가격을 곱해 펀드 대비 비율로 바꾼다.
      순매매_i = (post수량_i − pre수량_i) × post가격_i / post 주식평가액 합계 × 100
  편출 종목은 post 가격이 없으므로 pre 평가액을 나머지 종목의 평균 가격변화로 옮겨 쓴다.
  추정 매매금액 = 순매매 %p × 그날 순자산총액(KRX NAV × 상장좌수).
  분할·무상증자처럼 수량은 크게 변했는데 비중은 그대로인 종목은 '주식수 조정'으로 따로 표시한다.

데이터 출처
  - TIGER·KODEX·ACE·PLUS·KIWOOM·HANARO : 운용사 PDF 과거조회(날짜 파라미터)
  - SOL  : 상품 페이지 날짜검색 API(/api/fund/pdfList, work_dt)
  - RISE : KB 사이트가 최근 ~60영업일만 과거조회 → 그 이전은 대시보드 일별 스냅샷(git 이력)

실행
  py rebal_history.py                     # 증분: 최근 정기변경만(매일 자동 갱신용)
  py rebal_history.py --backfill          # 2024-01 이후 전체(최초 1회, KODEX 레이트리밋 때문에 오래 걸림)
  py rebal_history.py --backfill --tickers 069500 102110
  py rebal_history.py --plan              # 조회할 정기변경 건수만 출력
  py rebal_history.py --backfill --budget 12   # 12분 동안만 백필을 이어간다(GitHub Actions 매일)
환경변수 SKIP_MANAGERS=TIGER,RISE 면 해당 운용사는 건너뛴다(해외 IP 차단, fetch_holdings 와 공유).
"""
from __future__ import annotations
import os, re, sys, json, math, time, random, argparse, subprocess, threading
import datetime as dt
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8")
import urllib3
urllib3.disable_warnings()

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(DATA, "rebal")
CACHE = os.path.join(HERE, ".rebal_cache")       # 조회한 PDF 캐시(gitignore) — 재실행 시 재조회 방지

import kr_holidays as KH
import rebal_dates as RD
import fetch_holdings as FH

SINCE = dt.date(2024, 1, 1)
WIN_BEFORE, WIN_AFTER, WIN_AFTER_EST = 5, 5, 12
THR = 0.01                                        # 순매매 |%p| 이 이보다 작으면 '변동 없음'
SKIP = {m.strip().upper() for m in os.environ.get("SKIP_MANAGERS", "").split(",") if m.strip()}
GIT_ONLY: set = set()                             # 과거조회 API 가 없는 운용사(현재 없음)
GIT_FALLBACK = {"RISE"}                           # API 범위 밖은 git 스냅샷으로
CODE_RE = re.compile(r"^[0-9A-Z]{6}$")            # KRX 종목코드(현금·선물·예금 행 제외)
CASH_WORDS = ("현금", "예금", "설정액", "원화")     # 6자리 코드를 단 현금성 행(옛 RISE 등)

_print_lock = threading.Lock()


def log(*a):
    with _print_lock:
        print(*a, flush=True)


# ---------------------------------------------------------------------------
# 영업일
# ---------------------------------------------------------------------------
def is_bday(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in KH.load()


def bday_shift(d: dt.date, n: int) -> dt.date:
    return RD._bday_add(d, n)


def bdays_between(a: dt.date, b: dt.date) -> list:
    out, d = [], a
    while d <= b:
        if is_bday(d):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def kst_today() -> dt.date:
    return RD.kst_today()


# ---------------------------------------------------------------------------
# 스냅샷: {code: {"n": 이름, "s": CU 수량, "w": 비중%, "a": 평가금액}}  (주식 행만)
# ---------------------------------------------------------------------------
def to_snap(holdings) -> dict | None:
    out = {}
    for h in holdings or []:
        if isinstance(h, dict):
            c, n, s, w, a = h.get("code"), h.get("name"), h.get("shares"), h.get("weight"), h.get("amount")
        else:
            c, n, s, w, a = h.stock_code, h.stock_name, h.shares, h.weight, h.amount
        c = str(c or "").strip().upper()
        nm = str(n or "").replace(" ", "")
        if not CODE_RE.match(c) or not s or float(s) <= 0 or any(k in nm for k in CASH_WORDS):
            continue
        if c in out:                                  # 같은 코드가 두 줄이면 합친다
            out[c]["s"] += float(s); out[c]["w"] += float(w or 0); out[c]["a"] += float(a or 0)
            continue
        out[c] = {"n": str(n or c), "s": float(s), "w": float(w or 0), "a": float(a or 0)}
    return out or None


def values(S: dict) -> dict:
    """종목별 평가액 벡터. 운용사마다 '평가금액' 열의 의미가 달라(TIGER 옛 자료는 단가) 비중과
    맞아떨어지는 쪽을 고른다. 다 안 맞으면 비중 자체를 평가액으로 쓴다(소수 2자리라 덜 정밀)."""
    codes = list(S)
    w = {c: S[c]["w"] for c in codes}
    W = sum(w.values()) or 1.0
    top = sorted(codes, key=lambda c: -w[c])[:6]
    cands = []
    if sum(1 for c in codes if S[c]["a"] > 0) >= 0.9 * len(codes):
        cands.append({c: S[c]["a"] for c in codes})
        cands.append({c: S[c]["a"] * S[c]["s"] for c in codes})
    for v in cands:
        V = sum(v.values())
        if V > 0 and all(abs(v[c] / V * W - w[c]) <= max(0.06, 0.03 * w[c]) for c in top):
            return v
    return w


def _wmedian(pairs):
    pairs = sorted(pairs)
    tot = sum(p[1] for p in pairs)
    acc = 0.0
    for r, wt in pairs:
        acc += wt
        if acc >= tot / 2:
            return r
    return 1.0


def diff(A: dict, B: dict, cap: dict | None = None, aum: float = 0.0) -> dict:
    """pre(A) → post(B) 종목별 변화와 요약."""
    vA, vB = values(A), values(B)
    VA, VB = sum(vA.values()) or 1.0, sum(vB.values()) or 1.0
    cont = [c for c in A if c in B]

    # CU 크기 변경(전 종목 수량이 같은 배율로 변함)은 매매가 아니다
    scale = 1.0
    if cont:
        pr = [(B[c]["s"] / A[c]["s"], vB[c]) for c in cont if A[c]["s"] > 0 and B[c]["s"] > 0 and vB[c] > 0]
        s = _wmedian(pr) if pr else 1.0
        if abs(s - 1) > 0.05:
            near = sum(wt for r, wt in pr if abs(r / s - 1) < 0.02)
            if near >= 0.6 * sum(wt for _, wt in pr):
                scale = s

    pB = {c: vB[c] / B[c]["s"] for c in B if B[c]["s"] > 0}
    num = sum(A[c]["s"] * scale * pB[c] for c in cont if c in pB)
    den = sum(vA[c] for c in cont)
    k = (num / den) if den > 0 and num > 0 else VB / VA     # pre 평가단위 → post 평가단위

    items = []
    for c in set(A) | set(B):
        a, b = A.get(c), B.get(c)
        w0 = round(a["w"], 4) if a else 0.0
        w1 = round(b["w"], 4) if b else 0.0
        it = {"c": c, "n": (b or a)["n"], "w0": w0, "w1": w1,
              "s0": a["s"] if a else 0, "s1": b["s"] if b else 0}
        if a and not b:
            it["t"], tr = "out", -(vA[c] * k) / VB * 100
        elif b and not a:
            it["t"], tr = "in", vB[c] / VB * 100
        else:
            r = b["s"] / (a["s"] * scale) if a["s"] > 0 else 1.0
            sa, sb = vA[c] / VA, vB[c] / VB
            if r > 0 and abs(math.log(r)) > 0.18 and sa > 0 and sb > 0 and abs(math.log(sb / sa)) < 0.1:
                it["t"], tr = "ca", 0.0                  # 분할·병합·무상증자 추정
            else:
                tr = (b["s"] - a["s"] * scale) * pB.get(c, 0) / VB * 100
                it["t"] = "up" if tr >= THR else ("down" if tr <= -THR else "same")
        it["tr"] = round(tr, 4)
        if aum > 0 and it["t"] != "ca":
            it["amt"] = int(round(tr / 100 * aum))
        items.append(it)

    # 종목코드만 바뀐 경우(같은 이름이 편출·편입에 동시에) → 코드 변경으로 묶는다
    outs = {i["n"].replace(" ", ""): i for i in items if i["t"] == "out"}
    for i in items:
        if i["t"] == "in":
            o = outs.get(i["n"].replace(" ", ""))
            if o and o["t"] == "out":
                o["t"] = i["t"] = "recode"; o["tr"] = i["tr"] = 0.0
                o.pop("amt", None); i.pop("amt", None)

    _flag_caps(items, cap)
    moved = [i for i in items if i["t"] not in ("same", "ca", "recode")]
    buy = sum(i["tr"] for i in moved if i["tr"] > 0)
    sell = -sum(i["tr"] for i in moved if i["tr"] < 0)
    summ = {
        "in": sum(1 for i in items if i["t"] == "in"),
        "out": sum(1 for i in items if i["t"] == "out"),
        "up": sum(1 for i in items if i["t"] == "up"),
        "down": sum(1 for i in items if i["t"] == "down"),
        "ca": sum(1 for i in items if i["t"] == "ca"),
        "recode": sum(1 for i in items if i["t"] == "recode") // 2,
        "same": sum(1 for i in items if i["t"] == "same"),
        "cap_cut": sum(1 for i in items if i.get("cap") == "cut"),
        "to": round((buy + sell) / 2, 3),            # 편도 회전율(%)
        "buy": round(buy, 3), "sell": round(sell, 3),
    }
    if aum > 0:
        summ["buy_amt"] = int(round(buy / 100 * aum))
        summ["sell_amt"] = int(round(sell / 100 * aum))
    order = {"in": 0, "out": 1, "down": 2, "up": 3, "ca": 4, "recode": 5}
    keep = sorted((i for i in items if i["t"] != "same"),
                  key=lambda i: (order.get(i["t"], 9), -abs(i["tr"]), -i["w1"]))
    return {"sum": summ, "items": keep, "n0": len(A), "n1": len(B)}


def _flag_caps(items, cap):
    """현재 cap 규칙 기준으로 '상한 초과분 매도(cut)' / '상한까지 채움(fill)' 표시."""
    if not cap or cap.get("index_exception") or not cap.get("single_cap"):
        return
    single = float(cap["single_cap"]) * 100
    top_n = cap.get("top_n")
    top_cap = float(cap["top_cap"]) * 100 if cap.get("top_cap") else single
    rest = cap.get("rest_cap")
    rest_cap = float(rest) * 100 if rest else (None if top_n else single)
    ranked = sorted((i for i in items if i["w1"] > 0), key=lambda i: -i["w1"])
    rank = {i["c"]: r + 1 for r, i in enumerate(ranked)}
    for i in items:
        r = rank.get(i["c"])
        top = bool(top_n and r and r <= int(top_n))
        # '15% 초과 종목은 15%, 그 외 10%' 처럼 상위 상한을 받는 종목이 여럿일 수 있다
        # → 조정 후에도 하위 상한보다 확실히 큰 종목은 상위 상한을 적용한다
        if rest_cap is not None and i["w1"] > rest_cap + 1.0:
            top = True
        lim = top_cap if top else rest_cap
        if lim is None:
            continue
        if i["t"] == "down" and i["w0"] > lim + 0.05:
            i["cap"] = "cut"
        elif i["t"] in ("up", "in") and i["w1"] >= lim - 1.0 and i["tr"] >= 0.1:
            i["cap"] = "fill"
        if "cap" in i:
            i["lim"] = round(lim, 2)


def material(d: dict) -> bool:
    s = d["sum"]
    return (s["in"] + s["out"] > 0) or s["to"] >= 0.3 or ((s["up"] + s["down"]) >= 3 and s["to"] >= 0.05)


# ---------------------------------------------------------------------------
# 운용사별 과거 PDF 조회 (+디스크 캐시)
# ---------------------------------------------------------------------------
class Source:
    def __init__(self, etf: dict):
        self.e = etf
        self.mgr = etf["manager"]
        self.mem = {}
        self.dir = os.path.join(CACHE, etf["ticker"])
        self._git = None
        self.calls = 0

    # --- 캐시 ---
    def _cpath(self, d):
        return os.path.join(self.dir, d.strftime("%Y%m%d") + ".json")

    def get(self, d: dt.date) -> dict | None:
        if d in self.mem:
            return self.mem[d]
        p = self._cpath(d)
        if os.path.exists(p):
            try:
                j = json.load(open(p, encoding="utf-8"))
                snap = j.get("snap")
                if snap:                               # 캐시도 현재 필터 규칙으로 다시 거른다
                    snap = to_snap([{"code": c, "name": v["n"], "shares": v["s"], "weight": v["w"],
                                     "amount": v["a"]} for c, v in snap.items()])
                self.mem[d] = snap
                return snap
            except Exception:
                pass
        snap, failed = None, False
        if self.mgr not in GIT_ONLY:
            for attempt in range(3):                   # 일시적 연결 끊김(TIGER 등) 재시도
                try:
                    snap = self._api(d)
                    break
                except Exception as ex:
                    if attempt == 2:
                        log(f"    ! {self.e['name']} {d} 조회 실패: {str(ex)[:90]}")
                        failed = True
                    else:
                        # 403/429 = 과다요청 차단 → 길게 쉰다(SOL 은 몰아치면 IP 를 잠시 막는다)
                        blocked = any(k in str(ex) for k in ("403", "429"))
                        time.sleep((90 if blocked else 3) + (60 if blocked else 5) * attempt)
                        if self.mgr == "TIGER":
                            FH._tiger = None           # 세션 새로 열기
        if snap is None and (self.mgr in GIT_ONLY or self.mgr in GIT_FALLBACK):
            snap = self.git().get(d)
        self.mem[d] = snap
        if failed:                                     # 조회 실패는 '자료 없음'과 다르다 → 캐시하지 않음
            return None
        # 빈 결과는 충분히 지난 날짜만 캐시(최근 날짜는 나중에 올라올 수 있다)
        if snap is not None or d < kst_today() - dt.timedelta(days=10):
            os.makedirs(self.dir, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"snap": snap}, f, ensure_ascii=False)
        return snap

    # --- 운용사 API ---
    def _api(self, d: dt.date) -> dict | None:
        e, m = self.e, self.mgr
        ymd = d.strftime("%Y%m%d")
        self.calls += 1
        if m == "TIGER":
            return to_snap(FH.tiger().fetch(e["isin"], d))
        if m == "KODEX":
            hs, asof = kodex_paced(e["ticker"], d)
            return to_snap(hs) if str(asof).replace("-", "").replace(".", "") == ymd else None
        if m == "KIWOOM":
            hs, asof = FH.kiwoom().fetch(e["ticker"], d)
            return to_snap(hs) if str(asof).replace("-", "") == ymd else None
        if m == "ACE":
            hs, asof = FH.ace().fetch(e["ticker"], d)
            return to_snap(hs) if str(asof).replace("-", "") == ymd else None
        if m == "PLUS":
            hs, asof = FH.plus().fetch(e["name"], d)
            return to_snap(hs) if str(asof).replace("-", "") == ymd else None
        if m == "HANARO":
            hs, asof = FH.hanaro().fetch(e["name"], d)
            return to_snap(hs) if str(asof).replace("-", "") == ymd else None
        if m == "SOL":
            fc = FH.sol_fund_cd(e["ticker"])
            if not fc:
                return None
            _throttle("SOL", 2.5)
            hs, asof = FH.sol().fetch_hist(fc, d)
            return to_snap(hs) if str(asof) == ymd else None
        if m == "RISE":
            fc = FH.rise_code(e["ticker"])
            return to_snap(FH.rise().fetch(fc, d)) if fc else None
        return None

    # --- git 이력의 일별 스냅샷 ---
    def git(self) -> dict:
        if self._git is None:
            self._git = git_snapshots(self.e["ticker"])
        return self._git


def git_snapshots(ticker: str) -> dict:
    """data/holdings/{ticker}.json 의 커밋 이력 → {기준일: snap}. 같은 기준일이면 최신 커밋 우선."""
    rel = f"data/holdings/{ticker}.json"
    try:
        hashes = subprocess.run(["git", "log", "--format=%H", "--", rel], cwd=ROOT,
                                capture_output=True, text=True, check=True).stdout.split()
    except Exception:
        return {}
    out = {}
    for h in hashes:
        try:
            raw = subprocess.run(["git", "show", f"{h}:{rel}"], cwd=ROOT, capture_output=True,
                                 check=True).stdout.decode("utf-8")
            j = json.loads(raw)
            asof = dt.date.fromisoformat(str(j.get("asof"))[:10])
        except Exception:
            continue
        if asof not in out:
            out[asof] = to_snap(j.get("holdings"))
    return out


_thr_lock = threading.Lock()
_thr_last = defaultdict(float)


def _throttle(key: str, gap: float):
    """같은 운용사 요청 사이에 최소 gap 초(+지터) 간격을 둔다."""
    with _thr_lock:
        wait = _thr_last[key] + gap + random.random() - time.time()
        if wait > 0:
            time.sleep(wait)
        _thr_last[key] = time.time()


# KODEX(samsungfund)는 레이트리밋이 세다(429). 이력 수집은 천천히, 429 면 길게 쉬고 재시도.
_kodex_lock = threading.Lock()
_kodex_last = [0.0]


def kodex_paced(ticker: str, d: dt.date):
    k = FH.kodex()
    fid = k.fid(ticker)
    if not fid:
        raise RuntimeError(f"KODEX fId 미발견: {ticker}")
    for attempt in range(6):
        with _kodex_lock:
            wait = _kodex_last[0] + 3.0 + random.random() - time.time()
            if wait > 0:
                time.sleep(wait)
            r = k.s.get(f"{k.BASE}/product-pdf/{fid}.do", params={"gijunYMD": d.strftime("%Y.%m.%d")},
                        timeout=30)
            _kodex_last[0] = time.time()
        if r.status_code == 429:
            time.sleep(65 + 20 * attempt)
            continue
        r.raise_for_status()
        pdf = (r.json() or {}).get("pdf", {}) or {}
        hs = [{"code": str(it.get("itmNo", "")).strip()[3:9] if str(it.get("itmNo", "")).startswith("KR7")
               else str(it.get("itmNo", "")).strip(),
               "name": str(it.get("secNm", "")).strip(), "shares": it.get("applyQ"),
               "weight": it.get("ratio"), "amount": it.get("evalA")}
              for it in pdf.get("list", []) or [] if it.get("ratio") is not None]
        for h in hs:
            for f in ("shares", "weight", "amount"):
                try:
                    h[f] = float(str(h[f]).replace(",", "")) if h[f] not in (None, "") else 0.0
                except ValueError:
                    h[f] = 0.0
        return hs, str(pdf.get("gijunYMD", ""))
    raise RuntimeError("KODEX 429 반복")


# ---------------------------------------------------------------------------
# 순자산총액(그날) — KRX OPEN API 일별매매정보
# ---------------------------------------------------------------------------
_aum_cache = {}
_aum_lock = threading.Lock()


def aum_on(ticker: str, d: dt.date) -> float:
    ymd = d.strftime("%Y%m%d")
    with _aum_lock:
        if ymd not in _aum_cache:
            p = os.path.join(CACHE, f"_krx_{ymd}.json")
            rows = None
            if os.path.exists(p):
                try:
                    rows = json.load(open(p, encoding="utf-8"))
                except Exception:
                    rows = None
            if rows is None:
                try:
                    from krx_fetch import fetch_etf_raw, _num
                    raw = fetch_etf_raw(ymd)
                    rows = {str(r.get("ISU_CD", "")).strip():
                            (_num(r.get("NAV")) * _num(r.get("LIST_SHRS"))) or _num(r.get("MKTCAP"))
                            for r in raw}
                    if rows:
                        os.makedirs(CACHE, exist_ok=True)
                        json.dump(rows, open(p, "w", encoding="utf-8"))
                except Exception as ex:
                    log(f"    ! KRX {ymd} 순자산 조회 실패: {str(ex)[:80]}")
                    rows = {}
            _aum_cache[ymd] = rows or {}
        return float(_aum_cache[ymd].get(ticker) or 0.0)


# ---------------------------------------------------------------------------
# 정기변경 일정(과거)
# ---------------------------------------------------------------------------
def past_events(e: dict, since: dt.date, until: dt.date) -> list:
    months = e.get("months")
    if not months:
        return []
    kind, n, rule, guessed = RD.parse_rule(e.get("schedule_label", ""), e.get("schedule_detail", ""))
    est = bool(guessed or not e.get("schedule_verified"))
    out = []
    for y in range(since.year, until.year + 1):
        for m in sorted(set(int(x) for x in months if 1 <= int(x) <= 12)):
            try:
                d = RD.rule_date(kind, n, y, m)
            except ValueError:
                continue
            if since <= d <= until:
                out.append({"date": d, "rule": rule, "est": est})
    return sorted(out, key=lambda x: x["date"], reverse=True)


def locate(src: Source, days: list, expect: dt.date | None, cap) -> tuple:
    """days 구간에서 구성이 실질적으로 바뀐 구간들을 찾는다 → (intervals[(pre,post)], snaps)."""
    # 1) 빠른 경로: 운용사 관례상 바뀌는 날(expect) 전후 3일만 보고 확정되면 끝(KODEX 호출 절약)
    if expect in days:
        i = days.index(expect)
        if 0 < i < len(days) - 1:
            a, b, c = src.get(days[i - 1]), src.get(days[i]), src.get(days[i + 1])
            if a and b and c and material(diff(a, b, cap)) and not material(diff(b, c, cap)):
                return [(days[i - 1], days[i])]

    # 2) 일반 경로: 창 양 끝에서 시작해 이분 탐색
    avail = list(days)

    def snap_at(idx):
        return src.get(avail[idx])

    lo, hi = 0, len(avail) - 1
    while lo < hi and snap_at(lo) is None:
        lo += 1
    while hi > lo and snap_at(hi) is None:
        hi -= 1
    if lo >= hi:
        return None
    # 변경 전·후를 다 덮어야 비교가 성립한다. 스냅샷이 효력일 뒤에만 있으면(SOL 수집 시작 직후 등)
    # '변동 없음'으로 오판하므로 자료 없음 처리한다.
    if expect and not (avail[lo] < expect <= avail[hi]):
        return None

    def rec(a, b):
        if not material(diff(snap_at(a), snap_at(b), cap)):
            return []
        if b - a == 1:
            return [(avail[a], avail[b])]
        mid = (a + b) // 2
        for off in (0, 1, -1, 2, -2, 3, -3):
            m = mid + off
            if a < m < b and snap_at(m) is not None:
                return rec(a, m) + rec(m, b)
        return [(avail[a], avail[b])]                # 가운데 날짜가 비어 더 못 좁힘

    return rec(lo, hi), (avail[lo], avail[hi])


def build_event(e: dict, ev: dict, src: Source, today: dt.date) -> dict | None:
    D = ev["date"]
    after = WIN_AFTER_EST if ev["est"] else WIN_AFTER
    start, end = bday_shift(D, -WIN_BEFORE), bday_shift(D, after)
    last = today if is_bday(today) else bday_shift(today, -1)
    provisional = end > last
    days = bdays_between(start, min(end, last))
    if len(days) < 2:
        return None
    expect = bday_shift(D, -1) if e["manager"] == "KODEX" else D
    cap = e.get("cap")
    res = locate(src, days, expect, cap)
    rec = {"date": D.isoformat(), "rule": ev["rule"], "est": ev["est"]}
    if provisional:
        rec["provisional"] = True
    if res is None:
        return None                                   # 창 전체가 비어 있음(상장 전·자료 없음)
    if isinstance(res, list):                          # 빠른 경로
        intervals, ends = res, None
    else:
        intervals, ends = res
    if not intervals:
        a, b = ends
        rec.update({"status": "nochange", "pre": a.isoformat(), "post": b.isoformat(), "days": []})
        d = diff(src.get(a), src.get(b), cap)
        rec.update({"n0": d["n0"], "n1": d["n1"], "sum": d["sum"], "items": d["items"][:40]})
        return rec
    pre, post = intervals[0][0], intervals[-1][1]
    aum = aum_on(e["ticker"], post)
    d = diff(src.get(pre), src.get(post), cap, aum)
    rec.update({"status": "ok", "pre": pre.isoformat(), "post": post.isoformat(),
                "days": [b.isoformat() for _, b in intervals], "aum": int(aum) if aum else None,
                "n0": d["n0"], "n1": d["n1"], "sum": d["sum"], "items": d["items"]})
    return rec


# ---------------------------------------------------------------------------
# ETF 단위 처리
# ---------------------------------------------------------------------------
SOURCE_NOTE = {
    "RISE": "KB RISE 는 최근 약 60영업일만 과거 PDF 를 제공해, 그 이전은 대시보드 일별 스냅샷(2026-07-14~)으로 보완합니다.",
}


def load_existing(t: str) -> dict:
    p = os.path.join(OUT_DIR, f"{t}.json")
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    return {}


DEADLINE = [None]                                   # --budget: 이 시각 이후엔 새 이벤트를 시작하지 않는다


def process(e: dict, since: dt.date, backfill: bool, today: dt.date, rebuild: bool = False) -> tuple:
    t = e["ticker"]
    old = load_existing(t)
    by_date = {x["date"]: x for x in old.get("events", [])}
    # floor: 이 날짜 이전은 PDF 가 없다고 확인됨(상장 전·운용사 보관기간 밖) → 다시 조회하지 않는다
    floor = old.get("floor") if old.get("since") == since.isoformat() else None
    events = past_events(e, since, today)
    src = Source(e)
    new_n, misses = 0, 0
    horizon = today - dt.timedelta(days=45)           # 증분 모드: 최근 정기변경만 다시 본다
    for ev in events:
        key = ev["date"].isoformat()
        cur = by_date.get(key)
        done = cur and cur.get("status") in ("ok", "nochange") and not cur.get("provisional")
        if done and not rebuild:
            continue
        if not backfill and ev["date"] < horizon:
            continue
        if floor and key <= floor and not cur:
            break
        if DEADLINE[0] and time.time() > DEADLINE[0]:
            break
        rec = build_event(e, ev, src, today)
        if rec is None:
            misses += 1
            if backfill and misses >= 2:             # 연속으로 비면 상장 전 → 더 과거는 볼 필요 없음
                floor = key
                break
            continue
        misses = 0
        by_date[key] = rec
        new_n += 1
        s = rec.get("sum") or {}
        log(f"  {e['manager']:6} {e['name'][:24]:26} {key} {rec['status']:8} "
            f"편입{s.get('in', 0)} 편출{s.get('out', 0)} 확대{s.get('up', 0)} 축소{s.get('down', 0)} "
            f"회전{s.get('to', 0)}%  pre={rec.get('pre')} post={rec.get('post')}"
            + (" (잠정)" if rec.get("provisional") else ""))

    evs = sorted(by_date.values(), key=lambda x: x["date"], reverse=True)
    payload = {
        "ticker": t, "name": e["name"], "manager": e["manager"],
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "since": since.isoformat(),
        "floor": floor,
        "note": SOURCE_NOTE.get(e["manager"], ""),
        "events": evs,
    }
    if evs or old or floor:
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, f"{t}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    return new_n, src.calls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="SINCE 이후 전체(기본은 최근분만)")
    ap.add_argument("--since", default=SINCE.isoformat())
    ap.add_argument("--tickers", nargs="*")
    ap.add_argument("--managers", nargs="*")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="이미 만든 이벤트도 다시 계산(조회 결과는 캐시 재사용)")
    ap.add_argument("--budget", type=float, default=0, help="분. 이 시간이 지나면 새 이벤트를 시작하지 않음(매일 조금씩 백필)")
    args = ap.parse_args()

    since = dt.date.fromisoformat(args.since)
    today = kst_today()
    if args.budget > 0:
        DEADLINE[0] = time.time() + args.budget * 60
    # 과거 영업일 계산에 쓸 휴장일(holidays.json 이 과거 연도를 안 덮으면 즉석 계산으로 보강)
    hol, _ = KH.compute(min(since.year, 2023), today.year + 3)
    KH._CACHE = (KH.load() | hol)

    etfs = json.load(open(os.path.join(DATA, "etfs.json"), encoding="utf-8"))["etfs"]
    if args.tickers:
        etfs = [e for e in etfs if e["ticker"] in set(args.tickers)]
    if args.managers:
        etfs = [e for e in etfs if e["manager"] in {m.upper() for m in args.managers}]
    etfs = [e for e in etfs if e["manager"] not in SKIP]

    if args.plan:
        cnt = defaultdict(int)
        for e in etfs:
            cnt[e["manager"]] += len(past_events(e, since, today))
        print(dict(cnt), "합계", sum(cnt.values()))
        return

    if SKIP:
        log(f"(건너뜀: {', '.join(sorted(SKIP))})")
    groups = defaultdict(list)
    for e in etfs:
        groups[e["manager"]].append(e)

    stats = {}

    def run_group(mgr):
        n = calls = 0
        for e in groups[mgr]:
            try:
                a, b = process(e, since, args.backfill, today, args.rebuild)
                n += a; calls += b
            except Exception as ex:
                log(f"  ! {mgr} {e['name']} 실패: {ex}")
        stats[mgr] = (len(groups[mgr]), n, calls)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(groups) or 1) as ex:
        list(ex.map(run_group, list(groups)))
    for m, (ne, nn, nc) in sorted(stats.items()):
        log(f"{m:7} ETF {ne:3} · 갱신 이벤트 {nn:4} · PDF 조회 {nc:5}")
    log(f"완료 {time.time() - t0:.0f}s → data/rebal/")


if __name__ == "__main__":
    main()
