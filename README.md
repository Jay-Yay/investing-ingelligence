# Investor Intelligence

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

# 전체 파이프라인 (collect -> analyze -> portfolio -> report)
uv run python -m investor_intel run-daily
```

`init` 실행 후 `config/.env.example`을 `.env`로 복사하고 실제 값을 채운다. `doctor`가 각
환경변수가 어떤 기능에 필요한지 알려준다.

## 환경변수

| 변수 | 필요한 기능 |
|---|---|
| `ANTHROPIC_API_KEY` | LLM 분석(`analyze`) 및 리포트 종합(`report`, `run-daily`) |
| `ANTHROPIC_MODEL` | 사용할 Claude 모델 ID (기본값 `claude-sonnet-5`) |
| `SEC_USER_AGENT` | SEC EDGAR 수집(13F, 미국 기업 공시) — 식별 가능한 문자열 필수 |
| `DART_API_KEY` | OpenDART 수집(한국 기업 공시) |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_SESSION` | (선택) Telethon 기반 비공개
채널 수집(`sources.yaml`의 `type: telegram_private`) — 공개 웹 미리보기 수집에는 불필요.
`uv sync --extra telethon` 후 `telethon-login` 명령으로 세션 생성 |
| `DAILY_LLM_BUDGET_USD` / `MONTHLY_LLM_BUDGET_USD` | LLM 비용 상한 (기본값 1.5 / 45.0 USD) |

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
  10_Sources/            # 소스별 원문 (Naver/Telegram/SEC/DART/13F/IB/Essays)
  30_Portfolio/
    portfolio.yaml             # 보유 종목 + 투자 가설 원장 (아래 "투자 가설 업데이트" 참고)
  40_Analysis/
    Claims/<종목>.md          # 포트폴리오 모니터가 매일 append하는 종목별 신호 로그
  50_Reports/Daily/       # 일일 리포트

data/index.sqlite3       # vault로부터 재생성 가능한 검색 인덱스 (git 커밋 안 함)
```

`vault/`와 `data/`는 `.gitignore`에 포함되어 있다 — 이 저장소는 도구(tool)이고, 실제 수집된
데이터는 사용자의 것이므로 이 코드 저장소 히스토리에 들어가지 않는다.

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
- **포트폴리오 모니터 (`run-daily` 내부):** 보유 종목별로 오늘 수집된 자료가 기존 투자
  가설을 얼마나 바꿨는지 판단해 강세/중립/약세(bullish/neutral/bearish 성격의
  `thesis_shift`)와 매수/보유/축소/매도 신호를 낸다. `vault/40_Analysis/Claims/<종목>.md`에
  날짜별로 누적 기록.
- **텐베거 후보 발굴 (`run-daily` 내부):** 미보유 종목 중 펀더멘털 변곡점 + 10배 시가총액
  역산 가능성 기준으로 스크리닝(100점 만점, 7개 항목).
- **자본배분 순위 (`run-daily` 내부):** 보유 종목 신호와 신규 후보를 하나의 순위표로 통합.
- **리포트:** 위 결과를 종합한 한국어 일일 리포트 자동 생성.

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
편집하면 다음 `run-daily`(크론 또는 수동 실행)부터 바로 반영된다 — 재배포·재시작 불필요.
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

## 아키텍처와 로드맵

전체 설계는 [`docs/superpowers/specs/2026-07-24-investor-intelligence-design.md`](docs/superpowers/specs/2026-07-24-investor-intelligence-design.md),
단계별 구현 계획은 [`docs/superpowers/plans/2026-07-24-00-roadmap.md`](docs/superpowers/plans/2026-07-24-00-roadmap.md)에
있다. 로드맵의 모든 단계(Core Foundation부터 최근 follow-up까지)가 구현되어 있으며, 각 단계의
정확한 범위와 남은 제약사항은 로드맵 문서의 "Known limitations"를 참고한다.

## 자동 실행

`.github/workflows/daily-collect.yml`이 매일 00:00 UTC(09:00 KST)에 `run-daily`를 실행하도록
스케줄되어 있다. GitHub 저장소 Secrets/Variables에 위 환경변수를 등록하면 동작한다. 단,
`vault`/`data`는 이 저장소에 커밋되지 않으므로 GitHub 호스팅 러너에서는 실행 결과가 다음 실행에
이어지지 않는다 — 영속적인 저장이 필요하면 self-hosted 러너에 영구 디스크를 마운트하거나 별도
저장소/스토리지로 동기화하는 단계를 추가해야 한다.

## 개발

```bash
uv run pytest          # 테스트 전체 실행
uv run ruff check .    # 린트
uv run mypy investor_intel  # 타입 체크
```

`.github/workflows/ci.yml`이 모든 push/PR에서 위 세 가지(테스트/린트/타입체크)를 자동 실행한다
— `daily-collect.yml`(운영용 스케줄 실행)과는 별개다.
