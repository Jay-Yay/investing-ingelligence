# Investor Intelligence

개인용 투자 정보 수집·분석·포트폴리오 의사결정 지원 시스템. 지정한 투자자(13F), 미국/한국 기업
공시, 네이버 블로그, 텔레그램 채널을 매일 수집해 원문을 Obsidian Vault에 보존하고, Claude로
핵심 주장/근거/반대 근거를 구조화 추출한 뒤, YAML로 관리하는 포트폴리오에 대한 영향을 분석해
한국어 일일 리포트를 생성한다.

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
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | (선택) Telethon 기반 비공개 채널 수집 — 공개 웹
미리보기 수집에는 불필요 |
| `DAILY_LLM_BUDGET_USD` / `MONTHLY_LLM_BUDGET_USD` | LLM 비용 상한 (기본값 1.5 / 45.0 USD) |

## 디렉터리 구조

```
config/
  sources.yaml         # 네이버 블로그, 텔레그램 채널
  investors.yaml       # 13F 추적 대상 (Stanley Druckenmiller 등)
  companies.yaml       # SEC 공시 추적 대상 (NBIS, BE, RDDT)
  dart_companies.yaml  # DART 공시 추적 대상 (한국 기업, 사용자가 채움)
  settings.yaml
  prompts/             # LLM 프롬프트 템플릿

vault/                  # Obsidian Vault — 원본 데이터의 source of truth
  10_Sources/           # 소스별 원문 (Naver/Telegram/SEC/DART/13F)
  30_Portfolio/          # portfolio.yaml + 투자논리(Thesis) 노트
  40_Analysis/           # 추출된 주장/모순/이벤트
  50_Reports/Daily/      # 일일 리포트
  00_System/Runbook.md   # 운영 절차 (아래 참고)

data/index.sqlite3       # vault로부터 재생성 가능한 검색 인덱스 (git 커밋 안 함)
```

`vault/`와 `data/`는 `.gitignore`에 포함되어 있다 — 이 저장소는 도구(tool)이고, 실제 수집된
데이터는 사용자의 것이므로 이 코드 저장소 히스토리에 들어가지 않는다.

## 아키텍처와 로드맵

전체 설계는 [`docs/superpowers/specs/2026-07-24-investor-intelligence-design.md`](docs/superpowers/specs/2026-07-24-investor-intelligence-design.md),
단계별 구현 계획은 [`docs/superpowers/plans/2026-07-24-00-roadmap.md`](docs/superpowers/plans/2026-07-24-00-roadmap.md)에
있다. 로드맵의 10개 단계(Core Foundation부터 문서 정리까지)가 모두 구현되어 있다.

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
