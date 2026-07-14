# 국내 상장 패시브 ETF 대시보드

시가총액 **9,000억원 이상** 국내주식형 패시브 ETF(32종)의 **정기변경 일정 · 시가총액 ·
구성종목(PDF) · 비중 cap 규제**를 한 화면에 정리하는 GitHub Pages 정적 대시보드.

## 화면
- **초기화면(index.html)** — 시가총액 순 테이블(ETF명 · 정기변경 일정 · 시가총액 · 운용사).
  필터: ① 섹터·테마 여부 ② 시가총액 범위 ③ 정기변경 월 ④ 운용사. 상단 **실시간 갱신** 버튼.
- **개별 ETF(etf.html?ticker=)** — 기초지수 · 정기변경일 · 비중 cap 규칙(확인/확인 요 배지) 요약,
  cap 초과 시 **※주의 매도규모**(= 시가총액 × 초과 %p), 하단 **구성종목(PDF)** 표(초과 종목 강조).

## 데이터 파이프라인 (scripts/)
| 파일 | 역할 |
|------|------|
| `etf_meta.py` | 대상 32종 큐레이션(정기변경 일정·분류·월) |
| `cap_rules.py` | ETF별 비중 cap 규칙(지수 방법론/투자설명서 조사 반영) |
| `krx_fetch.py` | KRX OPEN API(ETF 일별매매정보) — 시총·상장좌수·기초지수 |
| `fetchers.py` | 운용사별 구성종목(PDF) 수집기 (KODEX·TIGER·RISE·SOL·ACE·PLUS·KIWOOM·HANARO) |
| `fetch_holdings.py` | 위 fetcher로 `data/holdings/{ticker}.json` 생성 |
| `caps.py` | cap 초과 판정 + 매도규모 계산 |
| `build_data.py` | 스냅샷+메타+cap → `data/etfs.json` |
| `refresh_all.py` | 전체 갱신(수집→빌드) |

### 로컬 실행
```bash
# KRX_API_KEY 환경변수 필요 (KRX 데이터 마켓플레이스 OPEN API 인증키)
cd scripts
py refresh_all.py            # 전체 갱신
# 미리보기
py -m http.server 8860 --directory ..   # http://localhost:8860
```

## 데이터 출처
- 시가총액·상장좌수·기초지수: **KRX 정보데이터시스템 OPEN API** (`etp/etf_bydd_trd`).
- 구성종목(PDF): **각 운용사 공식 공시** 엔드포인트(인증 불필요).
- 정기변경 일정: 지수 방법론(삼성증권 ETF 리밸런싱 자료 기준) 정리.
- 비중 cap: 지수 방법론/투자설명서 조사. `확인 요` 배지는 2차 출처 기반으로 원문 재확인 권장.

## 자동 갱신
`.github/workflows/refresh.yml` — 평일 16:10(KST) `refresh_all.py` 실행 후 `data/` 커밋.
저장소 Secrets 에 `KRX_API_KEY` 등록 필요.

## 실시간 시총(갱신 버튼)
장중에는 네이버 실시간가 × 상장좌수로 시가총액을 추정(공개 CORS 프록시 경유).
프록시가 막히면 최신 KRX 스냅샷으로 자동 폴백. 안정적 실시간이 필요하면 전용
Cloudflare Worker 프록시에 `polling.finance.naver.com` 화이트리스트 추가 권장.

> 본 자료는 정보 제공 목적이며 투자 권유가 아닙니다. 매도규모는 단순 추정치입니다.
