> **현재 운영 안내:** 2026-11-04부터 아래 「통합 운영」 절을 따릅니다. 기존 GitHub 수집과 `local_refresh.py`는 중단되었습니다.

# 국내 상장 패시브 ETF 대시보드

시가총액 **9,000억원 이상** 국내주식형 패시브 ETF(32종)의 **정기변경 일정 · 시가총액 ·
구성종목(PDF) · 비중 cap 규제**를 한 화면에 정리하는 GitHub Pages 정적 대시보드.

## 화면
- **초기화면(index.html)** — 시가총액 순 테이블(ETF명 · 정기변경 일정 · 시가총액 · 운용사).
  필터: ① 섹터·테마 여부 ② 시가총액 범위 ③ **정기변경 임박**(2주/1개월/3개월) ④ 정기변경 월 ⑤ 운용사.
  상단 **실시간 갱신** 버튼. **다음 정기변경** 열은 D-day 로 정렬 가능(임박 필터를 켜면 자동으로 임박순).
- **개별 ETF(etf.html?ticker=)** — 기초지수 · 정기변경일 · 비중 cap 규칙(확인/확인 요 배지) 요약,
  cap 초과 시 **※주의 매도규모**(= 시가총액 × 초과 %p), 하단 **구성종목(PDF)** 표(초과 종목 강조).
  상단에 **운용사 상품페이지 · 구성종목(PDF) 원문 · 기초지수 산출기관** 바로가기 링크.
  표의 구성종목은 매일 저녁 받아둔 스냅샷이라, 지금 이 순간 기준 PDF 는 원문 링크로 확인한다.
  구성종목 표 **아래에 과거 정기변경 이력**(2024-01 이후 회차별 편입·편출, 비중 확대·축소, cap 상한 조정)을 붙였다.

## 데이터 파이프라인 (scripts/)
| 파일 | 역할 |
|------|------|
| `etf_meta.py` | 대상 32종 큐레이션(정기변경 일정·분류·월) |
| `cap_rules.py` | ETF별 비중 cap 규칙(지수 방법론/투자설명서 조사 반영) |
| `krx_fetch.py` | KRX OPEN API(ETF 일별매매정보) — 시총·상장좌수·기초지수 |
| `fetchers.py` | 운용사별 구성종목(PDF) 수집기 (KODEX·TIGER·RISE·SOL·ACE·PLUS·KIWOOM·HANARO, 과거일자 조회 포함) |
| `fetch_holdings.py` | 위 fetcher로 `data/holdings/{ticker}.json` 생성 |
| `caps.py` | cap 초과 판정 + 매도규모 계산 |
| `kr_holidays.py` | KRX 휴장일 캘린더 → `data/holidays.json` (`--verify` 로 실거래일 대조) |
| `rebal_dates.py` | 정기변경 서술 → 다음 정기변경 예정일(선물옵션 만기일=둘째 목요일 기준 D+n 등) |
| `links.py` | 운용사 상품·PDF 원문 URL + 기초지수 산출기관 URL → `data/links.json` |
| `rebal_history.py` | 과거 정기변경일 전후 운용사 PDF 비교 → `data/rebal/{ticker}.json` |
| `local_refresh.py` | 국내 PC 전용: TIGER·RISE 수집 + 이력 + 빌드 → push (해외 IP 차단 대응) |
| `build_data.py` | 스냅샷+메타+cap(+links) → `data/etfs.json` |
| `refresh_all.py` | 전체 갱신(수집→빌드) |

### 로컬 실행
```bash
# KRX_API_KEY 환경변수 필요 (KRX 데이터 마켓플레이스 OPEN API 인증키)
cd scripts
py refresh_all.py            # 전체 갱신
# 미리보기
py -m http.server 8860 --directory ..   # http://localhost:8860
```

## 다음 정기변경 예정일 (rebal_dates.py)
`months` + 정기변경 서술(`schedule_label`/`schedule_detail`)을 실제 날짜로 옮겨
`etfs.json` 의 `rebalance = {dates[], rule, estimated}` 에 넣는다(앞으로 4회분).
기준점은 **선물옵션 만기일 = 그 달 둘째 목요일**이며, 서술에서 `D+n`·`익주 첫/둘째 영업일`·
`월말`·`월 첫 영업일`·`둘째 금요일`을 읽어 적용한다. 단서가 없으면 `만기일 D+1` 로 두고
`estimated=True`.

영업일 계산에는 주말 + **KRX 휴장일**(`kr_holidays.py` → `data/holidays.json`)을 제외한다.
KRX 정보데이터시스템의 휴장일 화면은 로그인 회원 전용(비로그인 호출은 `LOGOUT`)이라
`holidays` 패키지(한국 공휴일·음력·대체공휴일)로 만들고 **근로자의날(5/1)** 과
**연말 폐장일(12/31, 평일이면 휴장)** 을 더하고 **'노동절 대체 휴일'은 뺀다**(증시는 개장).
`py kr_holidays.py --verify` 가 네이버 KOSPI 실거래일과 대조하며, 2024-01-01~2026-08-31
구간 **불일치 0건**을 확인했다(자동 갱신 워크플로에도 검증 스텝을 넣어 로그로 남긴다).

⚠ 사후 지정되는 **임시공휴일은 예측할 수 없다**. 지정되면 `kr_holidays.EXTRA_HOLIDAYS` 에
넣고 다시 빌드한다. 화면에는 '예상 효력일'로 표기한다. 또 이 날짜는 **지수 변경 효력일**이고,
ETF 의 실제 매매는 통상 효력일 직전 거래일 종가에 몰린다.

## 외부 링크 (links.py)
운용사 내부코드(ISIN·FUND_CD·fId·uid…)를 한 번 해석해 `data/links.json` 에 캐시하고,
`build_data.py` 가 ETF 레코드에 `links` 로 붙인다. 캐시된 티커는 재조회하지 않는다.

| 운용사 | 상품 상세 URL |
|--------|----------------|
| TIGER | `investments.miraeasset.com/tigeretf/ko/product/search/detail/index.do?ksdFund={ISIN}` (`#section7` = 자산 구성) |
| KODEX | `samsungfund.com/etf/product/view.do?id={fId}` |
| RISE | `riseetf.co.kr/prod/finderDetail/{rise_code}` |
| SOL | `soletf.com/ko/fund/etf/{FUND_CD}` (`?tabIndex=3` = 구성종목(PDF)) |
| ACE | `aceetf.co.kr/fund/{fundCd}` |
| PLUS | `plusetf.co.kr/product/detail?n={n}` |
| HANARO | `hanaroetf.com/fund/{uid}` |
| KIWOOM | `kiwoometf.com/service/etf/KO02010200M?gcode={티커}` |

기초지수는 산출기관별로 연결한다. **FnGuide·MKF 계열**은 fnindex 지수 트리에서 지수코드를
찾아 `fnindex.co.kr/overview/info/{IDX_CD}` 개별 페이지로, **WISE** 계열은
`wiseindex.com/Index/Index#/{code}` 로 직접 연결한다(이름이 정확히 안 맞으면 한쪽이 다른
쪽을 포함하고 길이비 0.6 이상인 후보가 유일할 때만 채택 — 오연결보다 대표페이지가 낫다).
KRX·코스피/코스닥·iSelect(NH투자증권)·KEDI(한국경제)·MSCI·Akros 는 산출기관 대표 페이지로 보낸다.

## 과거 정기변경 이력 (rebal_history.py)
정기변경 예정 효력일 D(`rebal_dates` 규칙을 과거 달에 적용)의 전후 영업일 창(D-5~D+5, 일정이
자동추정이면 D+12)에서 운용사 PDF 를 **이분 탐색**으로 조회해 구성이 실제로 바뀐 날을 찾고,
바뀌기 직전(pre)·직후(post) PDF 를 종목별로 대조한다. 운용사마다 PDF 날짜 표기가 달라서다:
KODEX 는 효력일 전일(D-1) 날짜 PDF 에 이미 새 구성이 들어가고, TIGER·ACE·PLUS·KIWOOM 은 대개
D 날짜부터 바뀐다(2026-06 코스피200 정기변경으로 확인).

- **순매매 %p** = (post 수량 − pre 수량) × post 가격 ÷ post 주식평가액 × 100. PDF 비중은 주가만
  움직여도 변하므로 CU 보유수량 변화로 '실제로 사고판 양'만 잰다. 편출 종목은 pre 평가액을 나머지
  종목의 평균 가격변화로 옮겨 쓴다. **추정 금액** = 순매매 %p × 그날 순자산(KRX NAV × 상장좌수).
- 분할·무상증자(수량은 크게 변했는데 비중은 그대로)는 '주식수 조정', 코드만 바뀐 종목은 '코드 변경'으로
  매매에서 뺀다. CU 크기 변경(전 종목 같은 배율)도 걸러낸다.
- **cap 표시**: 현재 cap 규칙 기준으로, 상한을 넘었다가 깎인 종목은 '상한 초과분 매도',
  상한 근처까지 채운 종목은 '상한까지 매수'.
- 과거조회 범위: TIGER(2019~)·KODEX·ACE·PLUS·KIWOOM·HANARO·**SOL**(`/api/fund/pdfList?work_dt=`)은
  2024-01 이후 전부, **RISE 는 KB 사이트가 최근 ~60영업일만** 제공 → 그 이전은 이 저장소의 일별 스냅샷
  커밋 이력(git)으로 보완.
- 조회 결과는 `scripts/.rebal_cache/` 에 캐시(gitignore). `--rebuild` 는 캐시로 재계산만 한다.
- KODEX(samsungfund)는 레이트리밋이 세서 백필이 느리다 → Actions 가 매일 `--backfill --budget 12`
  로 12분씩 이어서 채운다. 상장 전 구간은 `floor` 로 기록해 다시 조회하지 않는다.

## 운용사 수집 주의 (2026-10 점검)
- **TIGER**: 미래에셋이 python-requests 의 TLS 지문을 끊는다 → `curl_cffi`(크롬 흉내) 세션으로 수집.
  그래도 **해외 IP(GitHub Actions)는 403**.
- **RISE**: 2026-09 riseetf.co.kr → **kbam.co.kr**(KB자산운용 통합) 이전. 목록 `api/products/etfs`
  (krx_cd→fund_cd), 전체 PDF 는 `.../holdings?download=xlsx&base_dt=`(JSON 은 상위 30종만).
  **해외 IP 접속 불가.**
- **HANARO**: `baseDate` 는 `YYYY.MM.DD` 형식이어야 과거조회가 된다(하이픈이면 최신으로 폴백).
- 위 두 운용사(TIGER·RISE) 때문에 2026-07-13·09-19 이후 구성종목이 멈춰 운용사 홈페이지 비중과
  어긋났었다. 지금은 Actions 가 `SKIP_MANAGERS=TIGER,RISE` 로 두 곳을 건너뛰고,
  **국내 PC 의 `scripts/local_refresh.py`**(Mac mini launchd, 아래 참고)가 따로 받아 push 한다.
  상세 화면은 구성종목 기준일이 KRX 기준일보다 4일 넘게 밀리면 경고를 띄운다.

## Mac mini 에서 TIGER·RISE 돌리기 (launchd)
국내 IP 의 상시 가동 Mac 에서 `scripts/local_refresh.py` 를 평일 21:00 에 돌린다.
```bash
git clone https://github.com/minguisstockgoat/passive-etf-dashboard.git ~/passive-etf-dashboard
cd ~/passive-etf-dashboard
python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements.txt
echo 'KRX_API_KEY=발급받은키' > .env          # gitignore 됨
chmod +x scripts/mac/run_local_refresh.sh
bash scripts/mac/run_local_refresh.sh          # 1회 수동 실행으로 push 까지 확인
sed "s#REPO_PATH#$HOME/passive-etf-dashboard#g" scripts/mac/com.minguis.passive-etf-local.plist   > ~/Library/LaunchAgents/com.minguis.passive-etf-local.plist
launchctl load ~/Library/LaunchAgents/com.minguis.passive-etf-local.plist
```
git push 인증(gh auth login 또는 SSH 키)이 돼 있어야 한다. 로그: `scripts/.local_refresh.log`, `scripts/.launchd.log`.

## 데이터 출처
- 시가총액·상장좌수·기초지수: **KRX 정보데이터시스템 OPEN API** (`etp/etf_bydd_trd`).
- 구성종목(PDF): **각 운용사 공식 공시** 엔드포인트(인증 불필요).
- 정기변경 일정: 지수 방법론(삼성증권 ETF 리밸런싱 자료 기준) 정리.
- 외부 링크: 각 운용사 공식 사이트 · fnindex / wiseindex / index.krx / kedindex / NH iSelect.
- 비중 cap: 지수 방법론/투자설명서 조사. `확인 요` 배지는 2차 출처 기반으로 원문 재확인 권장.

## 자동 갱신
`.github/workflows/refresh.yml`: 평일 20:10(KST) `refresh_all.py`(TIGER·RISE 제외) + `rebal_history.py`
실행 후 `data/` 커밋. 저장소 Secrets 에 `KRX_API_KEY` 등록 필요.
TIGER·RISE 는 국내 PC(Mac mini launchd)에서 `scripts/local_refresh.py`(로그 `scripts/.local_refresh.log`).

## 실시간 시총(갱신 버튼)
장중에는 네이버 실시간가 × 상장좌수로 시가총액을 추정(공개 CORS 프록시 경유).
프록시가 막히면 최신 KRX 스냅샷으로 자동 폴백. 안정적 실시간이 필요하면 전용
Cloudflare Worker 프록시에 `polling.finance.naver.com` 화이트리스트 추가 권장.

> 본 자료는 정보 제공 목적이며 투자 권유가 아닙니다. 매도규모는 단순 추정치입니다.

## 통합 운영 (2026-11-04)

운영 주소는 `https://minguisstockgoat.github.io/passive-etf-dashboard/` 하나입니다.
기존 ETF-Passive-Tracker는 자동 수집을 중단하고 통합 주소로 이동시킵니다.

- **일정·비중 제한**: 기존 ETF 목록, 예상 정기변경 효력일, cap 규칙, 과거 정기변경 이력 유지.
- **일간 구성 변화**: 운용사별 필터, 전체·관심 20종·최근 하루 변화·지연 자료 필터.
- **ETF 상세**: 이전/현재 비중·CU 수량·편입·편출·주식수 조정 추정과 원문 링크.
- 기존 관심 20종은 `data/watchlist.json`. 기존의 레버리지 ETF도 별도로 유지합니다.
- 일별 구성 이력은 `data/history/`에 ETF당 최근 32개 관측일을 보존합니다. 이전 트래커의 SQLite 원본은 원래 저장소에 보존합니다.

### 하나의 수집 작업

국내 Mac의 `com.wondaehan.etf-unified`가 평일 **08:50 / 20:40 KST**에
`scripts/run_daily.py --publish`를 실행합니다. 주말 실행은 없으며 휴장일에는 원천의 마지막 공시일을 유지합니다.
해외 IP 제한이 있는 TIGER·RISE도 이 작업에서 함께 수집합니다.
GitHub Actions는 소스 검증만 수행하며 데이터를 쓰지 않습니다. 기존 `local_refresh.py`와
옛 `refresh_all.py`는 운영 진입점이 아닙니다. 금요일 저녁에는 기존 정기변경 이력도 제한된 시간 안에 갱신합니다.

```bash
.venv/bin/python scripts/run_daily.py             # 수집·검사만
.venv/bin/python scripts/run_daily.py --publish   # 수집·검사·커밋·push
.venv/bin/python scripts/check_health.py          # 수집 실패·3거래일 이상 지연 감지
.venv/bin/python -m unittest discover -s tests -v
```

KRX 키는 환경변수 또는 로컬 `.env`, `~/.config/secrets/keys.env`, 기존
`~/short-dashboard/.env`의 KRX 키만 읽습니다. 키를 저장소에 커밋하지 않습니다.
실행 중복은 파일 잠금으로 막고 push는 3회 재시도합니다. 원격과 로컬이 갈라지면
자동 덮어쓰기·강제 push 없이 중단합니다. 성공한 수집분은 공개하되, 수집 실패나 오래된
원천이 있으면 작업 자체는 실패로 기록해 조용히 성공 처리하지 않습니다.

### 해석 주의

‘최신 관측’은 공시일이 현재로부터 0~1거래일 이내라는 뜻이며 실시간 보유내역을 뜻하지 않습니다.
2거래일 지연은 주의, 3거래일 이상은 실패입니다. 비교 간격이 1거래일이 아니거나
자료가 지연되면 최근 하루 변화에서 제외합니다. 단순 비중 변화에는 가격효과가 포함됩니다.
CU 수량도 분할·설정단위·코드 변경 영향을 받으므로 실제 매매 확정 표현을 쓰지 않습니다.
cap 초과 금액은 시가총액을 이용한 가정 금액이며 실제 강제 매도 하한이 아닙니다.

## 리밸런싱 영향 보고서 (2026-11-04)

`impact.html`에서 ETF를 고른 뒤 **리밸런싱 영향 보고서 생성**을 누른다.
목록의 정기변경 31일 이내 ETF와 모든 ETF 상세 화면에도 바로가기 버튼이 있다.
보고서는 브라우저에서 생성하며 API 키나 서버 실행 권한을 공개하지 않는다.

- 예상 순매매 = NAV × 상장좌수 × 목표/현재 비중 차이 × 미집행 비율.
- 최근 완료된 KRX 5거래일의 실제 거래대금 평균, 유동시총, 예상 주식 수를 비교한다.
- 기본값은 현금 비중을 유지한 **현 구성 유지·가중 조정 시나리오**다.
  일반 단일종목 상한은 현재 비중에서 초과분을 제한하고 남은 종목에 비례 배분한다.
  SOL 조선TOP3플러스는 현 TOP3/13종 유지, TOP3 25%씩·잔여 유동시총 가중을 적용한다.
  FnGuide 유동시총은 지수 제공사의 유동계수와 다른 대용치임을 명시한다.
- 예상 종목 교체는 자동 확정하지 않는다. 편출 목표 0%, 편입 종목 추가, 목표 비중과
  가정 근거를 입력하여 계산한다. 목표 비중 미확보는 영향 0이 아닌 판단 보류로 표시한다.
- 동일한 지수명·동일한 예상 변경일의 현물 ETF만 선택적으로 합산한다.
  각 ETF의 현금 비중과 현재 포지션을 따로 계산하며 전체 시장 수급으로 확대하지 않는다.
- 1/3/5거래일 집행, 100/75/50% 미집행 시나리오. 하루 참여율 5/20/50% 구간의
  압력 등급은 비교용 휴리스틱이며 예상 주가 등락률이나 검증된 가격 충격 모형이 아니다.
- PDF 인쇄, 외부 리소스 없이 열리는 HTML, ETF별 기여가 포함된 CSV 저장을 지원한다.

### 수집·오류 처리

`run_daily.py`는 기존 수집 후 `impact_data.py`를 실행한다. KRX 인증은 기존 로컬 경로를
그대로 사용한다. 최근 5개 공통 거래일 중 하나라도 누락되면 더 오래된 날로 대체하지 않고
직전 자료를 유지한다. 실패 상태는 `data/impact/status.json`에 별도로 기록하며 기존 ETF
수집 결과는 계속 배포한다. `market.json`에 자료 기준일·5개 날짜·종목별 유동 수집일을 기록한다.

FnGuide 유동주식수는 공개 Company Guide에서 수집하며 보통주 상장수/비율과 교차 확인한다.
공매도 프로젝트에 7일 이내 캐시가 있으면 읽기 전용으로 재사용한다. 매회 최대 120종의
누락/만료 자료를 보충한다. 캐시는 `scripts/.impact_cache/`이며 공개 배포에서 제외한다.
유동자료 30일 경과, 시세/구성 2거래일 초과, 5개 거래일 미확보, 파생형 ETF 등에는
해당 비교/등급을 보류한다. 수집일은 원천 주주변동 효력일을 뜻하지 않는다.

변경된 지수 방법론, 신규 구성 확정안, 임시 변경은 별도로 확인해야 한다.
일반 cap 표시는 정기변경 목표 비중 전체를 재현하지 않으며 매매 실행 지시가 아니다.
