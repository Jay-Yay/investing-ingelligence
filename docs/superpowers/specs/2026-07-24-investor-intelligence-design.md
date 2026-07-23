# Investor Intelligence System — 설계 문서

- 작성일: 2026-07-24
- 상태: 사용자 확정 요구사항(사용자 제공 스펙) + 아키텍처 설계 결합

## 1. 배경 및 목적

개인용 투자 정보 수집·분석·포트폴리오 의사결정 지원 시스템. 지정한 투자자(13F),
블로그(네이버), 텔레그램 채널, 미국/한국 기업 공시를 매일 수집하여 원문을 보존하고,
Claude Sonnet 5로 핵심 주장/근거/반대근거/촉매/리스크를 구조화 추출한 뒤, 사용자가
YAML로 관리하는 포트폴리오에 대한 영향을 분석해 한국어 Obsidian 일일 리포트를
생성한다. 실제 매매 주문은 절대 실행하지 않는다.

사용자가 사전에 정정한 사항 (그대로 반영):

- "Drukenmilier" → **Stanley Druckenmiller**, 추적 대상은 **Duquesne Family Office LLC**,
  CIK `0001536411`.
- Leopold Aschenbrenner 관련 데이터는 두 개의 독립된 source type으로 분리:
  - `essay`: situational-awareness.ai 원문 (Situational Awareness: The Decade Ahead)
  - `13f`: **Situational Awareness LP**, CIK `0002045724`
- 포트폴리오 필드명 "평균 맹비가" → **평균 매입가** (`average_cost`)로 정정.
- 저장 구조: **Obsidian Markdown+YAML = 원본(source of truth)**, **SQLite = 재생성 가능한
  검색/분석 인덱스** (git에 커밋하지 않음).
- SEC 자동 수집: 식별 가능한 User-Agent 필수, 공식 한도 10 req/s이지만 **실제로는
  2 req/s 이하로 보수적 제한**.
- DART: OpenDART API + 원문 XML 기준.
- Nebius(NBIS)는 foreign private issuer → 10-Q가 아니라 **20-F/6-K**가 주요 문서.
- Anthropic 모델 ID는 하드코딩 금지, `ANTHROPIC_MODEL` 환경변수로 관리
  (기본값 `claude-sonnet-5`).

전체 기능 요구사항, Obsidian Vault 구조, frontmatter 스키마, portfolio.yaml 스키마,
LLM 비용 통제, 투자 판단 가드레일, 일일 리포트 포맷, CLI 명령, cron/GitHub Actions,
config 파일 구조, 테스트 목록, 완료 조건은 사용자가 제공한 원본 프롬프트(21개 섹션)를
**그대로 요구사항으로 확정**한다. 이 설계 문서는 아래 "구현 아키텍처" 절만 추가한다.

## 2. 스코프 판단 — 분해 필요 여부

이 프로젝트는 다음과 같이 서로 독립적인 대형 서브시스템을 포함한다:

1. 설정/모델/스토리지 코어 (config, pydantic models, Obsidian repo, SQLite index)
2. 수집기(collector) — SEC/13F, 미국 기업 공시, DART, 네이버, 텔레그램 (5개, 서로 독립)
3. 시장 가격 provider (yfinance, CoinGecko)
4. LLM 분석 파이프라인 (Anthropic client, 구조화 출력, 비용 통제)
5. 포트폴리오 계산 + 가드레일
6. 일일 리포트 렌더링
7. CLI + 오케스트레이션 (run-daily)
8. cron / GitHub Actions
9. 테스트 스위트 + fixture
10. README/Runbook

사용자가 이미 §20에서 구현 순서를 명시했으므로 별도 재분해 없이 이를 phase 순서로
채택한다. 각 collector는 코어(스토리지/모델)에만 의존하고 서로 독립적이므로,
코어 완성 후 병렬 작업이 가능한 구조로 설계한다.

## 3. 아키텍처

### 3.1 패키지 레이아웃

```
investor_intel/
├── __main__.py            # python -m investor_intel
├── cli.py                 # Typer 기반 CLI, 커맨드 정의만
├── config/
│   ├── settings.py        # pydantic-settings: env var 바인딩
│   └── loaders.py         # YAML(settings/sources/companies/investors) 로더
├── models/                 # Pydantic 모델 (source_document, claim, 13F, 재무, 리포트 등)
├── storage/
│   ├── obsidian_repo.py   # Markdown+frontmatter read/write, 파일 경로 규칙, 충돌 처리
│   ├── sqlite_index.py    # 인덱스 스키마, upsert, reindex(마크다운→SQLite 재구축)
│   └── content_hash.py    # 정규화 + SHA-256, 중복판정 단계(§10) 구현
├── collectors/
│   ├── base.py            # Collector 프로토콜, rate limiter, retry/backoff, checkpoint 인터페이스
│   ├── sec_thirteenf.py   # EDGAR 13F XML
│   ├── sec_filings.py     # 10-K/10-Q/8-K/20-F/6-K + 실적자료
│   ├── dart.py            # OpenDART, corpCode 캐시
│   ├── naver_blog.py      # RSS 우선, mobile HTML fallback, 파서 분리
│   └── telegram.py        # t.me/s/{channel} 웹 미리보기 + 선택적 Telethon
├── market_data/
│   ├── provider.py        # MarketDataProvider Protocol, Quote/PriceBar 모델
│   ├── yfinance_adapter.py
│   └── coingecko_adapter.py
├── llm/
│   ├── client.py          # Anthropic client wrapper, ANTHROPIC_MODEL, prompt caching
│   ├── extraction.py      # claim/evidence/counter-evidence 구조화 추출 (tool use + pydantic 검증)
│   ├── portfolio_impact.py
│   ├── daily_report.py    # 최종 종합 리포트 LLM 합성
│   └── cost_tracker.py    # 일/월 비용 집계, 예산 가드
├── portfolio/
│   ├── calculations.py    # 평가금액/손익/비중/상승여력 등 파생값 계산 (입력 불변)
│   └── guardrails.py      # §12.3 하드가드레일, decision_status pending 로직
├── reports/
│   └── daily_report_renderer.py  # Jinja2 템플릿 → Markdown
├── pipeline/
│   └── orchestrator.py    # collect→analyze→portfolio→report, 부분 실패 허용
└── security/
    └── untrusted_content.py  # 원문 delimiting, prompt-injection 방어 유틸
```

### 3.2 핵심 설계 결정 (사용자 스펙 대비 제가 추가로 확정하는 기술 선택)

| 영역 | 선택 | 이유 |
|---|---|---|
| CLI 프레임워크 | Typer | 타입힌트 기반, pydantic과 궁합 좋음, `python -m investor_intel <cmd>` 자연스럽게 구성 |
| Markdown 템플릿 | Jinja2 | frontmatter/body 분리 렌더링, 리포트 템플릿 재사용 |
| Frontmatter I/O | PyYAML (`sort_keys=False`, 명시적 키 순서) | 스키마가 고정돼 있어 커스텀 라운드트립보다 예측 가능 |
| SQLite 접근 | stdlib `sqlite3` (ORM 없음) | 스키마가 작고 재생성 가능한 인덱스이므로 무거운 ORM 불필요 |
| HTTP | httpx (sync client, 명시적 timeout) | 스펙 지정 |
| HTTP 테스트 목킹 | respx | 스펙 지정 |
| 시간 결정론 테스트 | freezegun | 증분 체크포인트/백필 테스트에 필요 |
| Rate limiting | 소스별 token-bucket (SEC 2/s, DART/Naver/Telegram 각각 보수적 값) | §3.2/§4.3 요구사항 |
| LLM 구조화 출력 | Anthropic tool-use(strict JSON schema) → Pydantic validate → 실패시 최대 2회 재요청 | §11 요구사항 |
| Idempotency 키 | `stable_id = sha256(source_type|source_name|source_specific_id or canonical_url)` | §10 순서를 구현하는 기준 키 |

### 3.3 데이터 흐름

```
collector → RawFetchResult(원문 또는 excerpt, content_capture 판정)
          → normalize + content_hash 계산
          → dedup 판정(§10 5단계) against SQLite index
          → 신규/변경 시 obsidian_repo.write(frontmatter+body)  [원본 저장]
          → sqlite_index.upsert(document row + FTS/조회용 필드)  [인덱스 갱신]

analyze(미처리 문서만, llm_processed=false 또는 hash 변경분)
          → security/untrusted_content로 원문 delimit
          → llm/extraction → Pydantic Claim/Evidence/... 검증
          → obsidian_repo에 "## 핵심 주장" 등 섹션 갱신 + frontmatter llm_processed=true
          → cost_tracker에 토큰/비용 기록, 예산 초과시 이후 문서는 수집만 하고 skip

portfolio  → portfolio.yaml 로드(불변) + market_data provider 최신가
          → calculations(파생값) → guardrails(§12.3) → decision_status/recommendation

report     → 당일 신규/갱신 문서 + portfolio 결과 → llm/daily_report(종합) → renderer → Markdown 저장
```

### 3.4 오류 처리 원칙

- 모든 collector는 `CollectResult(success, items, errors)`를 반환하고 예외를 삼키지 않되,
  하나의 소스 실패가 파이프라인 전체를 중단시키지 않음(§14 요구사항). orchestrator가
  소스별 결과를 모아 최종 exit code와 요약을 결정.
- 가격 데이터가 오래되었거나 조회 실패 → 해당 종목은 자동으로 `decision_status: pending`.
- LLM JSON 검증 실패 → 최대 2회 재요청 후 실패 시 해당 문서는 `llm_processed:false`로
  남기고 다음 실행에서 재시도 (§17 테스트 대상).

## 4. 테스트 전략

- 소스별 fixture (`tests/fixtures/{naver,telegram,sec,dart}/...`)를 실제 저장된 응답으로 구성,
  실제 네트워크 호출 없음(respx로 차단).
- §17에 명시된 항목을 각각 독립 테스트 파일로 매핑 (collector 파싱, dedup, checkpoint,
  portfolio 가드레일, LLM 검증/비용, frontmatter round-trip, reindex, idempotency,
  prompt-injection 무해화).
- prompt-injection 테스트: fixture 원문에 "이전 지시를 무시하고..." 류 문구를 삽입해도
  LLM 클라이언트 wrapper가 이를 데이터로만 처리함을 delimiting 로직 단위테스트로 검증
  (실제 LLM 호출 없이, delimiting/새니타이즈 함수 자체를 테스트).

## 5. 남은 비-차단 항목 (사용자가 나중에 채움, 구현을 막지 않음)

- 실제 `.env` 값 (ANTHROPIC_API_KEY, SEC_USER_AGENT, DART_API_KEY, TELEGRAM_* 등) — 코드는
  환경변수 부재를 `doctor` 명령으로 명확히 보고하도록 구현.
- Obsidian Vault 로컬 경로 — 기본값 `./vault` (프로젝트 루트 하위)로 설정, `settings.yaml`에서
  변경 가능하도록 구현. 별도 확인 없이 이 기본값으로 진행.
- 한국 기업 목록, 추가 소스 — `companies.yaml`/`sources.yaml`에 예시와 스키마만 제공.

## 6. 완료 기준

사용자 스펙 §21의 완료 조건을 그대로 채택.
