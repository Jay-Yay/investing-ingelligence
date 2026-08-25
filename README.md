# Investor Intelligence

명령은 크게 둘로 나뉜다: **원문을 모으는 Collect**, **모은 원문으로 판단을 만드는 Analyze**.
옵션과 세부 동작은 각 절 또는 `uv run python -m investor_intel <명령> --help` 참고.

## Collect

| 명령 | 하는 일 |
|---|---|
| `collect` | 등록된 소스(SEC·DART·네이버·텔레그램·IB 등) 전체에서 새 글 수집 |
| `collect --backfill 365` | 새로 등록한 소스를 과거 N일치까지 소급 수집 |
| `web-research` | 보유 종목별 실시간 웹검색으로 등록 소스가 놓친 뉴스 보완 |
| `earnings-transcript` | SEC 8-K에 없는 실적발표 컨퍼런스콜을 웹서치로 보완 |
| `regime collect` | 시장 매크로 지표(신용스프레드·VIX·고용 등) 수집 |

## Analyze

| 명령 | 하는 일 |
|---|---|
| `analyze` | 수집된 문서에서 핵심 주장·근거·반대 근거 추출 |
| `portfolio` | 포트폴리오 평가금액·비중·가드레일 위반 계산 |
| `report` | 지금까지 쌓인 결과로 일일 리포트만 생성 |
| `run-daily` | collect → analyze → 포트폴리오 모니터 → 텐베거 발굴 → 리포트 전체 실행 |
| `verify-tenbagger NBIS 005930` | 텐베거(10배) 가설 중 정량 계산 가능한 부분만 검증 |
| `regime run-daily` | 시장 국면(과열·냉각·AI 사이클) 점수와 리포트 산출 |
| `regime analyze-ai` | 클라우드·AI 세그먼트 매출 등 국면 세부 항목을 LLM으로 보강 |
| `score compute 000660.KS` | 가격·재무제표만으로 종목 정량 점수 갱신 (일간) |
| `score run-weekly 000660.KS` | 실적 발표 등 이벤트에 맞춰 LLM 리서치까지 포함해 점수 갱신 |
| `score report 000660.KS` | 저장된 스냅샷으로 종목 리포트 렌더링 |

둘 중 어디에도 안 들어가는 최초 설정(`init`, `doctor`, `sync-inbox`)은 바로 아래 "빠른 시작"과
"소스·종목 추가"에 있다.

## 개요

개인용 투자 정보 수집·분석·포트폴리오 의사결정 지원 시스템. 지정한 투자자(13F), 미국/한국 기업
공시, 네이버 블로그, 텔레그램 채널, IB/자산운용사 인사이트 등을 매일 수집해 원문을 Obsidian
Vault에 보존하고, Claude로 핵심 주장/근거/반대 근거를 구조화 추출한 뒤, YAML로 관리하는
포트폴리오에 대한 영향(종목별 강세/약세 판단, 텐베거 후보 발굴, 자본배분 순위)을 분석해 한국어
일일 리포트를 생성한다.

**이 시스템은 실제 매매 주문을 절대 실행하지 않는다.** 수집·분석·리포트 생성만 수행하며, 모든
투자 판단은 사용자가 직접 내린다.

## 빠른 시작

```bash
# 의존성 설치 (uv 필요: https://docs.astral.sh/uv/)
uv sync --extra dev

# vault/config 디렉터리 구조와 예제 파일 생성 (기존 파일은 덮어쓰지 않음)
uv run python -m investor_intel init

# 환경변수, 설정 파일, vault 쓰기 권한 점검
uv run python -m investor_intel doctor

# 개별 단계 실행 (디버깅/수동 실행용)
uv run python -m investor_intel collect              # 모든 소스에서 수집
uv run python -m investor_intel analyze              # 미처리 문서 LLM 분석
uv run python -m investor_intel portfolio            # 포트폴리오 평가금액/가드레일 계산
uv run python -m investor_intel report               # 현재 상태로 리포트만 생성
uv run python -m investor_intel reindex              # vault 기준으로 SQLite 인덱스 재구축
uv run python -m investor_intel dedupe-vault         # 같은 문서 id의 중복 사본 정리 (--apply 없으면 dry-run)
uv run python -m investor_intel enrich-vault         # 기존 문서에 본문 품질·종목 관계 채우기 (--apply 없으면 dry-run)
uv run python -m investor_intel refetch              # 본문 불완전한 문서 재수집 (--apply 없으면 dry-run)

# 검색 인덱스 (OKF 번들 -> BM25 청크 인덱스)
uv run python scripts/build_knowledge_bundle.py --vault <vault>   # 지식 번들 생성 (선행 단계)
uv run python -m investor_intel index build          # 인덱스 전량 재구축
uv run python -m investor_intel index update         # 바뀐 문서만 증분 색인 (run-daily가 자동 실행)
uv run python -m investor_intel index status         # 수집·색인·품질 지표 (--max-corrupt 0으로 게이트)

# 매크로 가설 지표 트래킹 (config/macro_theses.yaml에 가설/지표 정의 필요)
uv run python -m investor_intel record-indicators <가설id> --data-file snapshot.json
uv run python -m investor_intel macro-status <가설id>       # 지표=행, 기록시점=열 표로 조회

# 전체 파이프라인 (collect -> analyze -> portfolio -> report)
uv run python -m investor_intel run-daily
```

`init` 실행 후 `config/.env.example`을 `.env`로 복사하고 실제 값을 채운다. `doctor`가 각
환경변수가 어떤 기능에 필요한지 알려준다.

## 환경변수

| 변수 | 필요한 기능 |
|---|---|
| `ANTHROPIC_API_KEY` | LLM 분석(`analyze`) 및 리포트 종합(`report`, `run-daily`) — **로컬에서만
필요, GitHub Actions에는 등록하지 않는다** (아래 "자동 실행" 참고) |
| `ANTHROPIC_MODEL` | 사용할 Claude 모델 ID (기본값 `claude-sonnet-5`) — 로컬 전용 |
| `SEC_USER_AGENT` | SEC EDGAR 수집(13F, 미국 기업 공시) — 식별 가능한 문자열 필수. GitHub
Actions Secret으로도 등록 |
| `DART_API_KEY` | OpenDART 수집(한국 기업 공시). GitHub Actions Secret으로도 등록 |
| `FRED_API_KEY` | 시장 국면 추적(`regime collect`)의 FRED 기반 지표(신용스프레드/ANFCI/
금리차/고용) — [무료 발급](https://fred.stlouisfed.org/docs/api/api_key.html). 없어도 나머지
지표(VIX 기간구조/시장 폭/레버리지·포지셔닝)는 수집된다. GitHub Actions Secret으로도 등록 |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_SESSION` | (선택) Telethon 기반 비공개
채널 수집(`sources.yaml`의 `type: telegram_private`) — 공개 웹 미리보기 수집에는 불필요.
`uv sync --extra telethon` 후 `telethon-login` 명령으로 세션 생성. 쓰는 경우 GitHub Actions
Secret으로도 등록 |
| `DAILY_LLM_BUDGET_USD` / `MONTHLY_LLM_BUDGET_USD` | LLM 비용 상한 (기본값 1.5 / 45.0 USD) —
로컬 전용 |

## 디렉터리 구조

```
config/
  sources.yaml         # 네이버 블로그, 텔레그램 채널, IB/자산운용사 인사이트, 네이버 리서치
  investors.yaml       # 13F 추적 대상 (Stanley Druckenmiller 등)
  companies.yaml       # SEC 공시 추적 대상 (NBIS, BE, RDDT)
  dart_companies.yaml  # DART 공시 추적 대상 (한국 기업; corp_code는 생략 가능 — 최초 실행 시
                       #   ticker/name으로 자동 조회 후 캐시됨)
  settings.yaml
  prompts/             # LLM 프롬프트 템플릿 (extract_claims/portfolio_monitor/
                       #   tenbagger_discovery/daily_report 등)

vault/                  # Obsidian Vault — 원본 데이터의 source of truth
  00_System/
    Runbook.md                # 운영 절차
    inbox_sources.md          # 소스/종목 추가용 체크리스트 (아래 "소스·종목 추가" 참고)
    Investment_Mandate.md     # 분석 관점(투자 원칙) — 세 LLM 단계 프롬프트에 자동으로 이어붙음
  10_Sources/            # 소스별 원문 (Naver/Telegram/SEC/DART/13F/IB/Essays/WebSearch)
  30_Portfolio/
    portfolio.yaml             # 보유 종목 + 투자 가설 원장 (아래 "투자 가설 업데이트" 참고)
  40_Analysis/
    Claims/<종목>.md          # 포트폴리오 모니터가 매일 append하는 종목별 신호 로그
  50_Reports/
    Daily/                     # 일일 리포트
    MarketRegime/<날짜>.{md,json}  # 시장 국면 추적 일일 리포트 (아래 "시장 국면 추적" 참고)
  60_MarketRegime/
    history/<indicator_id>.jsonl   # 지표별 일별 관측치 append-only 로그 (개정 이력 보존)
    processed/<날짜>.json          # 그날의 점수/국면/원본 관측치 스냅샷

data/index.sqlite3       # vault로부터 재생성 가능한 검색 인덱스 (git 커밋 안 함)
```

`vault/`와 `data/`는 `.gitignore`에 포함되어 있다 — 이 저장소는 도구(tool)이고, 실제 수집된
데이터는 사용자의 것이므로 `main` 브랜치 히스토리에는 들어가지 않는다. 단, GitHub Actions가
매일 수집한 결과는 이를 로컬로 옮기기 위해 전용 `data` 브랜치에 커밋된다 — 자세한 내용은 아래
"자동 실행"을 참고.

## 기능

- **수집:** SEC 13F, SEC 기업 공시(+ XBRL `companyfacts` 기반 매출/순이익/자산/부채 요약, 정기
  보고서(10-K/10-Q) 원문 전체 캡처, 8-K 실적발표 컨퍼런스콜 녹취록 첨부 시 자동 캡처),
  OpenDART 한국 기업 공시(corp_code 자동 해석, 사업/반기/분기보고서 원문 전체 캡처),
  네이버 블로그(RSS 우선, 실패 시 HTML 폴백), 텔레그램 공개 채널 미리보기(최대 10페이지
  페이지네이션), 텔레그램 비공개 채널(선택, Telethon 기반), 13F 추적 대상이 직접 발행한
  주주서한/에세이, 국내외 IB·자산운용사 공개 인사이트(Goldman Sachs/JPMorgan/BofA/Citi/
  BlackRock/Vanguard, 첨부 PDF 원문 추출 포함), 네이버 증권 종목분석 리포트(개별/주간
  인기 Top 10).
- **분석 (`analyze`):** Claude 기반 핵심 주장/근거/반대 근거/언급 자산 구조화 추출 — 추출
  결과는 각 문서의 "## 핵심 주장" 등 섹션에 자동 반영(splice)됨. LLM 비용은 실제 Anthropic
  토큰 사용량 기준으로 정확히 집계.
- **포트폴리오 (`portfolio`):** YAML 기반 포트폴리오의 평가금액/비중 계산(다통화 지원)과
  가드레일(최대 종목/섹터 비중, 레버리지·공매도·옵션 금지 등) 검사. LLM 불필요.
- **웹 검색 스크랩 (`web-research`, `run-daily` 내부):** 등록된 소스(네이버/텔레그램/공시 등)
  만으로는 놓치는 정보(해외 헤지펀드 13F/13G 공시, 외신 보도 등)를 보완하기 위해, 보유 종목별로
  Claude의 web_search 도구를 이용해 실시간 검색 결과를 스크랩한다. LLM 주장 추출/판단은 하지
  않는 단계(scrape only)라 `vault/10_Sources/WebSearch/<종목>/`에 원문만 저장되고, 다음 `analyze`
  실행부터 다른 소스와 동일하게 처리된다. `run-daily`에서는 이번 실행의 `analyze` 이후에 실행되므로
  당일 포트폴리오 모니터 판단에는 반영되지 않고 다음 실행부터 반영된다. ANTHROPIC_API_KEY가
  필요하므로 무인 `collect` 크론에는 포함되지 않는다.
- **포트폴리오 모니터 (`run-daily` 내부):** 보유 종목별로 오늘 수집된 자료가 기존 투자
  가설을 얼마나 바꿨는지 판단해 강세/중립/약세(bullish/neutral/bearish 성격의
  `thesis_shift`)와 매수/보유/축소/매도 신호를 낸다. `vault/40_Analysis/Claims/<종목>.md`에
  날짜별로 누적 기록.
- **텐베거 후보 발굴 (`run-daily` 내부):** 미보유 종목 중 펀더멘털 변곡점 + 10배 시가총액
  역산 가능성 기준으로 스크리닝(100점 만점, 7개 항목).
- **자본배분 순위 (`run-daily` 내부):** 보유 종목 신호와 신규 후보를 하나의 순위표로 통합.
- **리포트:** 위 결과를 종합한 한국어 일일 리포트 자동 생성.
- **시장 국면 추적 (`regime` 명령군):** 미국 매크로/신용/변동성/포지셔닝 지표를 매일 수집해
  `cooling_risk`/`overheating_risk`/`ai_cycle`/`data_confidence` 4개 점수와 시장 국면
  (HEALTHY_RISK_ON/OVERHEATED/STRESS 등)을 규칙 기반으로 계산한다. LLM을 쓰지 않아 무인 실행
  가능. 자세한 내용은 아래 "시장 국면 추적" 절 참고.

자세한 사용법은 아래 "소스·종목 추가", "투자 가설 업데이트", "가능한 분석" 절과
`vault/00_System/Runbook.md`를 참고한다.

## 소스·종목 추가

가장 간단한 방법은 `vault/00_System/inbox_sources.md`에 `- [ ] 타입: 값` 한 줄을 추가하고
다음을 실행하는 것이다.

```bash
uv run python -m investor_intel sync-inbox
```

티커/CIK/종목코드만 적으면 회사명 등 나머지 메타데이터는 SEC/DART 공개 API로 자동 조회되어
알맞은 `config/*.yaml`에 추가되고, 처리된 줄은 `- [x]`로 표시되어 재실행해도 중복 추가되지
않는다.

지원 타입:

| 타입 | 값 예시 | 설명 |
|---|---|---|
| `naver` | `https://m.blog.naver.com/블로그id` | 네이버 블로그 |
| `telegram` | `https://t.me/s/채널명` | 텔레그램 공개 채널(웹 미리보기) |
| `telegram_private` | `https://t.me/채널유저네임` | 텔레그램 비공개 채널 (Telethon 세션 필요) |
| `sec` | 티커 (예: `AAPL`) | 미국 기업 SEC 공시 |
| `dart` | 종목코드 (예: `005930`) | 한국 기업 DART 공시 |
| `investor` | `CIK \| 에세이URL(선택)` | 13F 추적 대상 |
| `gs_insights` / `jpm_insights` / `bofa_insights` / `citi_insights` / `blackrock_insights` / `vanguard_insights` | 자유 이름표 (예: `goldman-sachs`) | 각 사 공개 인사이트 페이지 (마케팅성 요약, 기관 전용 풀 리포트 아님) |
| `naver_research` | 자유 이름표 (예: `naver`) | 네이버 증권 종목분석 리포트(국내 증권사 발행, 첨부 PDF 원문 추출) |
| `naver_weekly_hot` | 자유 이름표 (예: `naver-hot`) | 네이버 증권 "요즘 많이 보는 리포트" 주간 Top 10 |
| `berkshire_letters` / `oaktree_memos` / `pershing_square_letters` | 자유 이름표 | 각 운용사가 직접 공개하는 주주서한/메모 원문 |

`sec` 타입은 `filing_types`를 미국 국내 상장사 기본값(10-K/10-Q/8-K)으로 채우므로, Nebius처럼
외국민간발행인(20-F/6-K)이면 `config/companies.yaml`에서 한 번 직접 고쳐야 한다. `*_insights`/
`naver_research`/`naver_weekly_hot`/`*_letters`/`*_memos` 타입은 페이지가 하나뿐이라 값은
URL이 아니라 자유롭게 붙일 이름표다. 지원하지 않는 소스(Morgan Stanley/State Street — 봇 차단,
Fidelity Learn — 날짜 없는 상시 콘텐츠 등)는 `inbox_sources.md`의 안내문에 사유가 적혀 있다.

직접 YAML을 편집해도 된다: 네이버/텔레그램/IB인사이트 → `config/sources.yaml`, SEC 공시 →
`config/companies.yaml`, 13F 투자자 → `config/investors.yaml`, DART 공시 →
`config/dart_companies.yaml`.

추가 후 아래처럼 신규 소스를 과거 데이터까지 백필할 수 있다(생략 시 증분 수집만 수행):

```bash
uv run python -m investor_intel collect --backfill 365
```

## 투자 가설 업데이트

### 보유 종목 (`vault/30_Portfolio/portfolio.yaml`)

`quantity`/`average_cost`를 실제 보유 현황으로 갱신한다. `constraints`(레버리지/공매도/옵션
허용 여부, 최대 종목/섹터 비중)를 벗어나는 포지션은 `portfolio` 명령 실행 시 가드레일
위반으로 표시된다.

포트폴리오 모니터가 "오늘 자료가 기존 가설을 얼마나 바꿨는가"를 판단하려면 비교 기준이
필요하다. 각 포지션에 다음을 채워둔다(비워두면 그 항목은 판단에서 빠진다 — 없는 값을
지어내지 않는다):

| 필드 | 내용 |
|---|---|
| `thesis` | 이 종목을 산 이유 (한두 문장) |
| `key_kpis` | 매일 확인할 지표 목록 (예: `["수주잔고", "가동률", "고객 집중도"]`) |
| `invalidation_condition` | 투자 가설이 무효화되는 조건 |
| `next_catalyst` | 다음으로 예상되는 촉매 |
| `fair_value_low` / `fair_value_high` | 적정가치 범위 |
| `max_position_weight` | 이 종목만의 비중 상한 (없으면 `constraints.max_single_position_weight` 전역값 적용) |

### 분석 관점 (`vault/00_System/Investment_Mandate.md`)

일일 리포트가 "무엇을 우선시할지"는 이 파일에 있다. 코드가 아니라 데이터이므로 직접
편집하면 다음 `analyze`/`report`/`run-daily` 실행부터 바로 반영된다 — 재배포·재시작 불필요.
현재 담긴 내용:

- 최우선 목표와 판단 원칙(뉴스 어조를 그대로 신호로 번역하지 않기, 언급량이 아니라
  펀더멘털 선행지표 우선, 최신성 가중, 소스 간 교차검증, 정보 부족 시 추정하지 않기 등)
- **종목군별 렌즈**: 같은 종목이라도 무엇을 봐야 하는지가 다르다(예: 반도체는 메모리
  사이클, 소비재는 브랜드 확장, 인프라는 수주잔고). 새 종목을 추가하면 이 표에 렌즈를
  한 줄 추가해두는 것이 좋다.
- **소스 신뢰도 등급** (A: 공시/실적발표 ~ E: 블로그/텔레그램/마케팅성 인사이트)
- 텐베거 스크리닝 기준(6개월~2년 내 2배 vs 3~7년 내 10배를 구분하는 판정 기준, 점수표)

### 프롬프트 자체 (`config/prompts/*.md`)

`extract_claims.md`(주장 추출), `portfolio_monitor.md`(종목별 판단), `tenbagger_discovery.md`
(신규 후보 발굴), `daily_report.md`(종합 브리핑)는 실행 시점에 실제로 로드되는 프롬프트
원본이다 — 추출/판단 로직 자체를 바꾸고 싶으면 이 파일들을 직접 고친다. 뒤의 세 개는
`Investment_Mandate.md`가 자동으로 이어붙는다.

## 가능한 분석

| 단계 | 실행 방법 | LLM 필요 | 결과물 |
|---|---|---|---|
| 주장 추출 | `analyze` | O | 각 원문 문서의 "## 핵심 주장/근거/반대 근거/언급 자산" 섹션 |
| 포트폴리오 평가/가드레일 | `portfolio` | X | 종목별 현재가/평가금액/비중, 가드레일 위반 목록 (콘솔 출력) |
| 포트폴리오 모니터 | `run-daily` (API 키 필요) | O | 보유 종목별 `thesis_shift`(강화/중립/약화), 매수·보유·축소·매도 신호(`signal`/`signal_strength`), 근거·반대근거·다음 확인조건 — `vault/40_Analysis/Claims/<종목>.md`에 날짜별 누적 |
| 텐베거 후보 발굴 | `run-daily` (API 키 필요) | O | 미보유 종목 중 100점 만점 스크리닝, 정식후보(80+)/관찰목록(65-79)/제외(65 미만) |
| 자본배분 순위 | `run-daily` 내부 | X (코드로 계산) | 보유 종목 + 신규 후보를 기대수익/하방위험/확신도 기준 하나의 순위표로 통합 |
| 일일 리포트 | `report`(가벼운 버전) 또는 `run-daily`(전체) | O(있으면) | `vault/50_Reports/Daily/<날짜>.md` — 오늘의 결론(5줄 이내)/추가 확인 과제 + 위 결과표 |

주의: 포트폴리오 모니터/텐베거 발굴/자본배분 순위는 **`run-daily` 파이프라인에서만** 계산된다.
독립 실행되는 `report` 명령은 포트폴리오 평가금액/가드레일과 짧은 프로즈 요약만 생성하는
더 가벼운 버전이라, 종목별 신호표·텐베거 후보표는 비어있는 채로("오늘 새로 판단된 보유 종목
신호 없음" 등) 나온다 — 이 두 단계를 다 보려면 `run-daily`를 실행해야 한다.
`ANTHROPIC_API_KEY`가 없으면 두 명령 모두 LLM 단계를 조용히 건너뛴다(억지 판단을 지어내지
않음).

## 시장 국면 추적 (Market Regime Tracker)

투자 추천 시스템이 아니라 시장 국면(과열/냉각/AI 사이클) 판단 시스템이다. 매수/매도 신호나
목표가는 만들지 않는다. **EPS 컨센서스 수정 폭만 여전히 스텁이다**(I/B/E/S 등 유료 데이터
필요, 무료 대체가 없어 계속 `unavailable`). 그 외 9개 지표는 전부 무료 데이터로 실제 계산된다
- 하이퍼스케일러 CapEx 효율/AI 반도체 실수요는 Yahoo Finance 분기 재무제표만으로 헤드라인
값을 계산하고(`regime collect`/`run-daily`, LLM 불필요), 클라우드/AI 세그먼트 매출처럼 필딩
구조화 데이터로 안 잡히는 세부 필드는 `regime analyze-ai`(LLM, 수동)가 있으면 보강한다 - 없어도
헤드라인 점수는 계산된다.

### 지표 (10개 중 9개 실제 계산, EPS만 스텁)

| 지표 | 출처 | 비고 |
|---|---|---|
| 하이일드 신용스프레드 | FRED `BAMLH0A0HYM2` | |
| Chicago Fed ANFCI | FRED `ANFCI` | |
| 10Y-3M 금리차 | FRED `T10Y3M` | |
| 고용 냉각 복합지표 | FRED `ICSA`/`IC4WSA`/`CCSA`/`SAHMREALTIME` | |
| VIX 기간구조 | Yahoo Finance `^VIX`/`^VIX3M` | |
| 시장 폭 | 위키피디아 S&P500 구성종목 표 + Yahoo Finance 가격 이력 | S&P500 공식 무료 API가
없어 위키피디아 구성종목 표로 대체(iShares IVV 보유종목 CSV를 우선 시도했으나 라이브
확인 결과 봇 차단으로 접근 불가) |
| 레버리지·포지셔닝 | CFTC "Traders in Financial Futures" | 선물(및 옵션) 시장 대형
트레이더 포지션의 일부일 뿐 시장 전체 롱/숏 비중이 아님. FINRA 마진통계는 봇 차단(HTTP 403,
라이브 확인)으로 자동 수집 불가 — 개인 레버리지 축은 제외 |
| 하이퍼스케일러 AI 투자 효율 | Yahoo Finance 분기 재무제표(CapEx/영업현금흐름) | value=TTM
CapEx/TTM 영업현금흐름(MSFT/GOOGL/AMZN/META/ORCL 중앙값). 클라우드/AI 세그먼트 매출 성장률·
CapEx 가이던스 방향은 `regime analyze-ai`(LLM)가 채운다 |
| AI 반도체 실수요 | Yahoo Finance 분기 재무제표(매출) | TSM/NVDA/AVGO/MU 매출 YoY 성장률
중앙값 - 스펙 원문의 TSMC "월간" 매출 요구사항은 분기 성장률로 근사(TSM은 20-F 발행사라 SEC에
월간 데이터가 없음). NVIDIA/Broadcom 데이터센터 세그먼트 성장률은 `regime analyze-ai`가 채운다 |
| S&P 500 EPS 전망치 수정 폭 | — | 무료 API 없음(I/B/E/S/Refinitiv 등 유료 필요) - 항상
`unavailable` |

### 사용법

```bash
uv run python -m investor_intel regime collect --vault-path ./vault      # 지표 수집 (history/ append, LLM 불필요)
uv run python -m investor_intel regime analyze-ai --vault-path ./vault   # 클라우드/AI 매출·가이던스 LLM 보강 (선택, 수동)
uv run python -m investor_intel regime score --vault-path ./vault        # 점수/국면 계산 (processed/ 저장)
uv run python -m investor_intel regime report --vault-path ./vault       # 리포트 렌더링 (50_Reports/MarketRegime/)
uv run python -m investor_intel regime run-daily --vault-path ./vault    # collect -> score -> report (analyze-ai 제외)
```

`collect`/`score`/`report`는 `--date YYYY-MM-DD`로 특정일을 지정할 수 있다(생략 시 오늘).
`collect`/`score`/`report`/`run-daily`는 LLM을 쓰지 않으므로
`.github/workflows/daily-collect.yml`에서 매일 무인 실행된다(아래 "자동 실행" 참고).
`analyze-ai`는 ANTHROPIC_API_KEY와 LLM 예산이 필요해 무인 크론에 포함하지 않는다 - 돌리고
싶으면 `regime collect` → `regime analyze-ai` → `regime score` → `regime report` 순서로
수동 실행한다(순서가 바뀌면 그날 리포트에 반영되지 않는다).

### 점수/국면

`cooling_risk_score`/`overheating_risk_score`/`ai_cycle_score`/`data_confidence_score`
4개(0~100)와 `market_regime`/`ai_regime` 국면을 계산한다. 지표가 누락되면 0점 처리하지 않고
가용 지표의 가중치를 비례 재조정하며, 커버리지가 70% 미만이면 `confidence_level`이 낮아지고
50% 미만이면 해당 국면이 `INDETERMINATE`가 된다 — 정확한 가중치·판정 규칙은
`investor_intel/regime/scoring.py`, `investor_intel/regime/regime_classifier.py`를 참고한다.

## 종목별 정량 스코어링 (Stock Scoring)

미래 주가를 예측하는 시스템이 아니다. 종목별 투자 매력도를 일관된 결정론적 규칙(0-100점)으로
평가하고, 투자 가설이 강화/훼손됐는지 조기에 발견하며, 매수/보유/축소/매도 판단의 근거를
제공한다. 최종 점수는 항상 코드가 구조화된 Feature로부터 계산하며, LLM은 사실 추출·정성
판단·반론에만 관여한다(`TenbaggerVerification`이 `total_score`를 코드로 재계산하는 것과 동일한
원칙). 실제 주문은 실행하지 않는다.

### 지원 종목·산업 추가 방법

`config/scoring/universe.yaml`에 종목을 추가한다(코드 변경 불필요). `sector` 필드가
`config/scoring/sector_<sector>.yaml`과 매칭되면 그 섹터 전용 가중치·Feature 목록을 쓰고,
없으면 `global_scoring.yaml`의 공통 기준을 쓴다. 기본 제공 섹터는 `memory`(SK하이닉스,
삼성전자)뿐이다 — GPU/전력/냉각/클라우드/네오클라우드 섹터는 아직 구체적인 Feature 스펙이
없어 만들지 않았다(동일한 스키마로 `sector_gpu.yaml` 등을 추가하면 로더가 그대로 인식한다).

이 레지스트리는 `vault/30_Portfolio/portfolio.yaml`(실제 보유·평균단가·비중)과 의도적으로
분리되어 있다 — 기업의 투자 매력도 점수는 매수원가와 무관해야 하기 때문에 `average_cost`/
`quantity` 필드 자체가 존재하지 않는다. 평균 매수가와 현재 비중은 오직 포지션 사이징(비중
확대/축소 판단)에만 쓰인다.

### 실행 방법

```bash
# 일간 - LLM을 쓰지 않는다 (가격/거래량/재무제표 성장률만 갱신, 무인 실행 가능)
uv run python -m investor_intel score compute 000660.KS

# 주간/이벤트 (실적 발표 등) - Evidence Collector/Fundamental Analyst/Bear Case Critic 실행
# 하루 LLM 예산과 충돌하지 않도록 daily 크론에는 배선하지 않는다 - 수동 또는 주 1회만 실행
uv run python -m investor_intel score run-weekly 000660.KS

# 저장된 스냅샷으로 12개 섹션 리포트 렌더링
uv run python -m investor_intel score report 000660.KS
```

### 스코어링 기준

대분류 가중치(합 100)는 `config/scoring/global_scoring.yaml`(공통) 또는
`config/scoring/sector_memory.yaml`(메모리 섹터)에서 관리한다:

| 카테고리 | 공통 가중치 | 메모리 섹터 가중치 |
|---|---|---|
| 매크로/유동성 | 15 | 10 |
| 최종수요/산업 (메모리: 수급·가격) | 20 | 25 |
| 기업 펀더멘털 (메모리: HBM 경쟁력) | 25 | 25 |
| 실적 전망치 | 15 | 15 |
| 밸류에이션 | 10 | 10 |
| 가격/수급 | 10 | 10 |
| 리스크 (메모리: 공급과잉 등) | 5 | 5 |

매크로 카테고리는 `regime` 모듈의 시장 전체 cooling_risk를 재사용한다(종목마다 다시 계산하지
않는다). 밸류에이션은 목표주가를 쓰지 않고 bear/base/bull 시나리오(peak/현재 forward/정상화
중기 EPS × 배수)로 계산한다. 신규 매수 신호는 총점(72점 이상 진입, 62점 이상 유지)뿐 아니라
신뢰도·연속 점수 상승·2차 확인 신호를 모두 충족해야 하며, 하드게이트(핵심 고객 상실, 2개
분기 연속 가이던스/컨센서스 하향 등)가 하나라도 발동하면 총점과 무관하게 차단된다. 신호
전환에는 5거래일 대기기간이 있어 단일 뉴스로 매수↔매도가 바로 뒤집히지 않는다. 정확한
계산은 `investor_intel/scoring/{categories,hard_gates,hysteresis,valuation_scenarios}.py`를
참고한다.

### 데이터 출처와 한계

- 가격/거래량/분기 재무제표(YoY 성장률)는 Yahoo Finance에서 실시간 조회한다(무료, 인증 불필요
  — 단 `fundamentals-timeseries` 엔드포인트는 환경에 따라 일시적으로 rate limit에 걸릴 수
  있으며, 이 경우 크래시하지 않고 해당 feature만 missing 처리된다).
- DRAM/NAND/HBM 계약가·bit shipment·고객 인증 등 산업 지표와 EPS 컨센서스 수정(상향/하향
  애널리스트 수)은 TrendForce/I·B·E·S 같은 유료 데이터를 전혀 쓰지 않는다 — 대신 이미 매일
  수집 중인 국내 IB 리포트(`naver-weekly-hot`/`naver_research`)에서 `score run-weekly`의
  Evidence Collector가 LLM으로 구조화 추출한다. 유료 컨센서스 패널보다 표본이 작고 노이즈가
  있다는 한계가 있다.
- 벤치마크는 KOSPI/S&P500/NASDAQ100/PHLX_SEMICONDUCTOR만 지원한다 — KRX 반도체 지수는 Yahoo
  무료 API에 심볼이 없어 지원하지 않으며, 이 경우 상대강도 지표가 missing으로 남는다.
- Champion/Challenger 워크포워드 비교(`investor_intel/scoring/evaluation.py`)는 최소 표본
  20건을 채우기 전까지 항상 "표본 부족"으로 비교를 보류한다 - 스냅샷이 몇 개월 쌓이기 전까지는
  정상적으로 작동하지 않는 것처럼 보일 수 있다(의도된 동작).
- 모델 버전 변경 방법: `model_registry/champion.yaml`이 현재 승인된 버전을 기록한다.
  Model Reviewer의 제안은 항상 `pending_human_approval` 상태로만 나오며, 실제로 반영하려면
  `model_registry/challengers/`에 후보 설정을 추가하고 `compare_champion_challenger()`로
  검증한 뒤 사람이 승인해 `config/scoring/*.yaml`을 교체하고 `champion.yaml`/`changelog.md`를
  갱신해야 한다 - 코드가 자동으로 승격하지 않는다.

예시 리포트: [`docs/examples/stock_score_000660.KS.md`](docs/examples/stock_score_000660.KS.md)
(2026-08-02 실제 라이브 데이터로 생성 — 주간 LLM 미실행 상태라 일부 카테고리가 missing인
"실제 daily 실행 결과"), [`docs/examples/stock_score_005930.KS_full_example.md`](docs/examples/stock_score_005930.KS_full_example.md)
(주간 실행 이후를 가정한 Mock 데이터 예시 — 파일 상단에 Example 표시).

## 아키텍처와 로드맵

전체 설계는 [`docs/superpowers/specs/2026-07-24-investor-intelligence-design.md`](docs/superpowers/specs/2026-07-24-investor-intelligence-design.md),
단계별 구현 계획은 [`docs/superpowers/plans/2026-07-24-00-roadmap.md`](docs/superpowers/plans/2026-07-24-00-roadmap.md)에
있다. 로드맵의 모든 단계(Core Foundation부터 최근 follow-up까지)가 구현되어 있으며, 각 단계의
정확한 범위와 남은 제약사항은 로드맵 문서의 "Known limitations"를 참고한다.

## 자동 실행

`.github/workflows/daily-collect.yml`이 매일 00:00 UTC(09:00 KST)에 **`collect`와 `regime
run-daily`만** 실행하도록 스케줄되어 있다 — 둘 다 LLM을 쓰지 않아 무인 실행이 안전하다.
`analyze`/`portfolio`/`report`(LLM 호출이 있는 단계)는 자동화하지 않고 로컬에서 Claude Code로
직접 돌린다 — 무인 크론이 LLM 토큰을 검토 없이 계속 소비하는 걸 막기 위함이다. `regime
run-daily`는 `continue-on-error`로 실행되어, 실패해도(예: `FRED_API_KEY` 미등록) `collect`
job 전체를 실패시키지 않는다.

GitHub Actions는 매 실행마다 이 저장소의 전용 `data` 브랜치를 `state/`에 체크아웃하고,
`state/vault`/`state/data`를 대상으로 `collect`를 실행한 뒤 결과를 그 브랜치에 다시 커밋한다
(`data` 브랜치가 아직 없으면 첫 실행 때 자동으로 생성됨). GitHub 호스팅 러너는 실행이 끝나면
파일시스템이 사라지므로, 이 브랜치가 실행 간 상태를 이어주는 유일한 영속 저장소다. 필요한
GitHub Secrets:

| Secret | 용도 |
|---|---|
| `SEC_USER_AGENT` | SEC EDGAR 수집 (필수 — 없으면 SEC/13F 수집이 건너뛰어짐) |
| `DART_API_KEY` | OpenDART 한국 기업 공시 수집 (없으면 DART 수집만 건너뛰어짐) |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_SESSION` | (선택) 텔레그램 비공개 채널
수집을 쓰는 경우에만 |

`ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL`/`DAILY_LLM_BUDGET_USD`/`MONTHLY_LLM_BUDGET_USD`는 이
워크플로에 등록할 필요가 없다 — `collect`는 LLM을 호출하지 않는다.

워크플로가 `data` 브랜치에 push할 수 있어야 하므로 저장소 Settings → Actions → General →
Workflow permissions에서 "Read and write permissions"가 켜져 있어야 한다(워크플로 파일에도
`permissions: contents: write`가 명시되어 있음).

### 로컬에서 분석 실행

자동 수집분을 로컬로 가져와 분석하려면:

```bash
git fetch origin data
git worktree add ../ii-data data   # 최초 1회. 이후엔 ../ii-data에서 git pull로 갱신

uv run python -m investor_intel analyze \
  --vault-path ../ii-data/vault --sqlite-path ../ii-data/data/index.sqlite3
uv run python -m investor_intel portfolio --vault-path ../ii-data/vault
uv run python -m investor_intel report --vault-path ../ii-data/vault
```

분석 결과(Claims/리포트, `llm_processed` 플래그)를 계속 보존하고 다음 실행에서 중복 분석을
피하려면, 분석 후 `../ii-data`에서 커밋 후 `data` 브랜치로 push해둔다.

self-hosted 러너로 전환하면(항상 켜져 있는 개인 서버/맥이 있는 경우) `data` 브랜치 우회 없이
영구 디스크에 바로 읽고 쓸 수 있다 — 필요해지면 `runs-on`을 self-hosted 러너 라벨로 바꾸면 된다.

## 개발

```bash
uv run pytest          # 테스트 전체 실행
uv run ruff check .    # 린트
uv run mypy investor_intel  # 타입 체크
```

`.github/workflows/ci.yml`이 모든 push/PR에서 위 세 가지(테스트/린트/타입체크)를 자동 실행한다
— `daily-collect.yml`(운영용 스케줄 실행)과는 별개다.
