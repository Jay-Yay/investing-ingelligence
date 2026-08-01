# Runbook

## 일일 실행

- 자동 (수집만): `.github/workflows/daily-collect.yml`이 매일 00:00 UTC(09:00 KST)에
  `collect`만 실행하고, 결과를 전용 `data` 브랜치에 커밋한다. LLM을 쓰는 analyze/portfolio/
  report는 무인 크론에서 돌리지 않는다 — 로컬에서 Claude Code로 직접 실행한다.
- 수동 전체 파이프라인: `uv run python -m investor_intel run-daily`
- **로컬에서 여러 머신 쓸 때 권장**: 위 명령 대신 `scripts/sync-run.sh run-daily`(또는
  `collect`/`analyze`/`web-research` 등 아무 서브커맨드나) — pull → 실행 → commit/push를
  하나로 묶어준다. 아래 "여러 머신에서 동시에 실행하는 경우"의 "먼저 pull, 실행 후 즉시
  push" 원칙을 사람이 순서를 안 까먹어도 되게 자동화한 것.

`run-daily`는 collect -> analyze -> portfolio -> report 순서로 실행되며, 한 단계 안에서 한
소스/문서가 실패해도 나머지는 계속 진행한다(부분 실패 허용). 종료 코드가 0이 아니면
`collect_errors`/`analyze_errors`가 출력에 포함되어 있으니 확인한다.

**여러 머신에서 동시에 실행하는 경우**: GitHub Actions(collect 전용) + 로컬 머신 여러 대가
모두 같은 `data` 브랜치에 vault를 커밋/푸시할 수 있다. 원문 스크랩 문서(`10_Sources/*`)는
결정적 ID(`compute_stable_id`)로 저장되므로 같은 문서를 여러 곳에서 수집해도 대부분 같은
파일 경로로 수렴해 git merge 시 충돌 없이 합쳐진다. 다만 `web_research`(보유 종목 웹 검색
스크랩)는 하루 단위 ID라서 같은 날 두 머신에서 각각 실행하면 같은 경로에 서로 다른 검색
결과가 붙어 merge 충돌이 날 수 있다 — 로컬에서 `run-daily`/`web-research`를 돌리기 전에
`git pull`(또는 `data` 브랜치 최신화)을 먼저 해서 그날 다른 머신이 이미 스크랩했는지
반영하면(다음 문단 참고) 이 충돌과 중복 LLM 호출 둘 다 줄어든다.

`40_Analysis/Claims/<종목>.md`(포트폴리오 모니터 시그널 로그)는 날짜(`## YYYY-MM-DD`) 단위로
append되므로 다른 날 판단은 자동으로 별도 기록이 되지만, **같은 날 두 머신이 각각
포트폴리오 모니터를 돌리면 그날 섹션 내용이 실제로 다를 수 있어 진짜 git 충돌이 난다** —
이건 둘 다 유효한 "그날의 판단"이라 자동 병합이 아니라 사람이 어느 쪽을 그날의 공식
기록으로 남길지 골라야 한다. 포트폴리오 모니터는 하루 1회, 한 머신에서만 공식 실행하는
것을 권장한다. `scripts/sync-run.sh`는 pull이 fast-forward 안 되면(= 위 같은 진짜 충돌이
남아있으면) 실행 자체를 중단하고 수동 해결을 안내한다 — 강제 병합을 시도하지 않는다.

## DART/SEC 정기보고서 원문 + 컨퍼런스콜

- **정기보고서**: DART 사업보고서/반기보고서/분기보고서, SEC 10-K/10-Q는 이제 원문(최대
  4만자, 초과분은 링크 참고)까지 캡처된다(`content_capture.mode: full`). 제목에
  `[연간보고서]`/`[반기보고서]`/`[분기보고서]` 접두어가 붙는다. 태그만 제거한 단순 변환이라
  표 구조가 완벽히 보존되진 않는다 — 정확한 수치가 필요하면 원문 링크를 확인한다.
- **8-K 컨퍼런스콜**: SEC 필링 중 실제로 실적발표 통화 녹취록을 Exhibit로 첨부하는 곳은
  일부(대략 20~30%)뿐이다. 첨부된 경우에만 감지해서 원문을 캡처하고 제목에
  `[컨퍼런스콜]`을 붙인다. 나머지 8-K는 기존과 동일하게 메타데이터만 캡처된다.
- **나머지 갭(웹서치 보완)**: 위 20~30%가 못 잡는 나머지 8-K(그리고 8-K 자체가 없는 20-F/6-K
  외국민간발행인 100%)는 `uv run python -m investor_intel earnings-transcript`가 회사별로
  `web_search`로 보완 검색한다(`investor_intel/pipeline/earnings_transcript.py`). 이미 SEC
  쪽에서 그 분기 녹취록을 찾았으면 건너뛴다. 저작권/비용 문제로 **전문(verbatim)은 캡처하지
  않고 경영진 발언 핵심 요지 + Q&A 핵심 문답의 구조적 요약만** 담는다 — 제목에
  `[컨퍼런스콜-웹서치]`가 붙고 `content_capture.mode: excerpt`로 표시된다. `web-research`와
  동일한 이유(LLM 토큰 비용)로 무인 collect 크론에는 포함되지 않고, `run-daily` 안에서
  analyze 이후 자동 실행되거나 이 명령으로 수동 실행한다.
- **한국 기업 컨퍼런스콜**: DART에는 컨퍼런스콜 녹취록을 올리는 공시 유형 자체가 없고, KIND
  IR자료실은 회사마다 업로드 여부/형식이 제각각이라 일관된 자동 수집 대상이 아니다. StockPlus,
  한경컨센서스 같은 매체가 컨퍼런스콜 스크립트를 기사로 싣기도 하지만 그건 그 매체의 저작물이라
  (네이버 증권 리서치 리포트와 같은 이유로) 대량 스크래핑 대상으로 삼지 않는다. 위 웹서치
  보완 컬렉터도 SEC(`config/companies.yaml`) 대상 전용이라 한국 상장사(`dart_companies.yaml`)에는
  적용되지 않는다. 필요하면 종목별로 회사 IR 페이지를 개별 소스로 수동 추가하는 방법을 고려할
  수 있다(아직 구현 안 됨).

## 중앙은행 금리결정문/의사록

미/일/한/EU/영 5개국은 `config/sources.yaml`의 `fed_*`/`ecb_*`/`boe_*`/`boj_*`/`bok_*` 소스로
각 은행 공식 사이트를 직접 스크래핑한다(LLM 비용 없음 - 무인 collect 크론에도 포함).
`10_Sources/CentralBank/<은행>/`에 저장되며 제목에 `[은행 성명서]`/`[은행 의사록]`이 붙는다.
성명서/의사록은 은행마다 공개 시차가 있어(Fed 3주, BOJ ~1개월, BOK ~2주, ECB accounts 4주)
별도 소스로 각자 수집한다 - 단 BOE는 결정 당일 하나의 문서(Monetary Policy Summary and
minutes)로 묶어 내므로 소스 하나(`boe_summary_minutes`)뿐이다. `published_at`은 실제 회의일이
아니라 수집 시각으로 기록한다(회의록이 회의일로부터 몇 주 뒤 공개되므로, 회의일을 쓰면 위
"LLM 비용 예산"의 "최근 7일" analyze 창에 안 걸려 조용히 누락된다) - 실제 회의일은
`reporting_period` 프런트매터를 참고한다.

중국(PBOC)은 서구식 회의록 자체를 공개하지 않고(분기 통화정책위 공보만 있음) `pbc.gov.cn`
robots.txt가 크롤러를 차단해 직접 스크래핑도 불가능하다 - 나머지 5개국과 달리 `web_search`
기반으로 `run-daily` 안에서 analyze 이후 자동 실행된다(LLM 토큰 비용 발생, 무인 크론에는
미포함, earnings-transcript-web과 동일한 이유). 분기(3개월)에 한 번만 시도하며, 전문 대신
구조적 요약만 캡처한다.

## `doctor`가 문제를 보고할 때

`uv run python -m investor_intel doctor` 로 환경변수/설정 파일/vault 쓰기 권한을 점검한다.
`MISSING` 항목이 있으면:

- `SEC_USER_AGENT`, `VAULT_WRITE` — 필수. 이 둘이 없으면 `doctor`가 종료 코드 1을 반환한다.
- `ANTHROPIC_API_KEY` — 없으면 `analyze`/`report`의 LLM 단계가 자동으로 건너뛰어지고
  (`run-daily`도 마찬가지) 대신 안내 메시지가 `analyze_errors`에 남는다. 수집 자체는 계속된다.
- `DART_API_KEY` — 없으면 `dart_companies.yaml`이 존재해도 DART 수집만 건너뛴다.
- `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`/`TELEGRAM_SESSION` — 공개 채널 웹 미리보기 수집에는
  불필요. `sources.yaml`에 `type: telegram_private` 항목이 있고 이 셋이 모두 설정된 경우에만
  Telethon 기반 비공개 채널 수집이 활성화된다. 세션 문자열은
  `uv run python -m investor_intel telethon-login --api-id ... --api-hash ...`로 1회성
  대화형 로그인 후 생성한다(`uv sync --extra telethon` 먼저 필요).

## LLM 비용 예산

`DAILY_LLM_BUDGET_USD`/`MONTHLY_LLM_BUDGET_USD`(기본 1.5 / 45.0 USD)를 넘으면 `analyze` 단계가
남은 문서 분석을 멈추고 종료한다(오류가 아니라 정상적인 중단). 처리되지 못한 문서는
`llm_processed: false`로 남아 다음 실행에서 이어서 분석된다. 비용은 SQLite의 `llm_usage`
테이블에 기록되며, Anthropic API 응답의 실제 토큰 사용량(`response.usage`, 재시도 포함 누적)을
기준으로 정확히 계산된다.

`analyze`는 미분석 문서 전체를 대상으로 하지 않는다 — 수십 년치 히스토리컬 백필(예: 1999년
DART 공시)까지 매번 큐에 올리면 하루 예산이 오래된 문서 처리에 다 소진되기 때문이다
(`find_unprocessed_document_paths`, `investor_intel/pipeline/analyze.py`). 대신 두 창(window)의
합집합만 분석 대상이 된다: (1) 발행일이 최근 7일 이내인 모든 문서, (2) 포트폴리오 보유 종목에
한해 — DART/SEC 공시·보유 종목 웹 검색 스크랩은 `source_name`에 티커가 그대로 담기므로 이
셋만 해당 — 180일 이내인 문서. 이 창 밖의 오래된 백로그는 `llm_processed: false`로 영구히
분석되지 않고 남는다(의도된 동작 — 필요하면 `analyze` 함수 인자로 `recent_days`/
`ticker_followup_days`를 넘겨 조정).

## SQLite 인덱스는 커밋하지 않는다 (로컬 전용 캐시)

`data/index.sqlite3`는 vault의 Markdown+frontmatter로부터 재생성 가능한 캐시일 뿐이라 git으로
추적하지 않는다(`data` 브랜치에 `.gitignore` 처리됨). 바이너리 파일이라 여러 머신이 같은
브랜치에 커밋하면 merge가 안 되기 때문 — 예전에는 이 파일도 커밋해서 GitHub Actions와 로컬
머신이 같은 날 둘 다 `data` 브랜치에 푸시하면 반드시 충돌이 났다.

대신 `collect`/`analyze`/`web-research`/`run-daily` 실행 시작 시 vault를 기준으로 자동
재인덱싱된다(`sqlite_index.reindex()`가 매 실행 앞단에 붙어 있음) — 그래서 방금 `git pull`로
받아온 vault 내용이 있으면 그것까지 반영된 상태로 dedup 판단이 이뤄진다. 인덱스가 손상되거나
비어 있어도 별도 조치 없이 다음 실행에서 자동 복구되며, 수동으로 즉시 재구축하고 싶으면:

```bash
uv run python -m investor_intel reindex
```

**단, `documents`/`document_assets` 테이블만 vault에서 재생성된다.** 같은 sqlite 파일 안의
`collector_state`(수집 체크포인트), `llm_usage`/`cost_ledger`(일일/월간 LLM 예산 추적),
`dart_corp_codes`(DART corpCode 캐시) 테이블은 vault에서 유도할 수 없는 머신별 로컬 상태라
동기화되지 않는다 — 머신을 바꾸거나 로컬 sqlite를 지우면 이 상태는 초기화된다(체크포인트가
없으면 그냥 최근 항목을 다시 훑고 문서 단위 dedup으로 걸러지므로 안전하고, DART corpCode
캐시는 공개 API에서 재조회될 뿐이다). 예산 추적은 머신별로 따로 집계된다는 뜻이므로,
여러 머신에서 같은 날 `analyze`/`web-research`를 돌리면 실제 총 지출이 `DAILY_LLM_BUDGET_USD`
설정값보다 머신 대수만큼 더 커질 수 있다는 점은 감안한다.

## 새 소스/기업/투자자 추가

가장 간단한 방법은 `vault/00_System/inbox_sources.md`에 `- [ ] 타입: 값` 한 줄을 추가하고
`uv run python -m investor_intel sync-inbox`를 실행하는 것이다. 티커/CIK/종목코드만 적으면
회사명 등 나머지 메타데이터는 SEC/DART 공개 API로 자동 조회되어 알맞은 config/*.yaml에
추가되고, 처리된 줄은 `- [x]`로 표시되어 재실행해도 중복 추가되지 않는다. `sec` 타입은
filing_types를 국내 상장사 기본값(10-K/10-Q/8-K)으로 채우므로, Nebius처럼 외국민간발행인
(20-F/6-K)이면 `companies.yaml`에서 한 번 직접 고쳐야 한다.

직접 YAML을 편집해도 된다:

- 네이버 블로그, 텔레그램 채널 -> `config/sources.yaml` (`init`이 생성한 예제 항목 형식을
  그대로 따른다)
- 미국 기업 SEC 공시 -> `config/companies.yaml`
- 13F 추적 투자자 -> `config/investors.yaml`
- 한국 기업 DART 공시 -> `config/dart_companies.yaml` (`corp_code`는 생략 가능 - 최초 수집 시
  ticker/name으로 자동 조회 후 캐시된다)

추가 후 `uv run python -m investor_intel collect --backfill 365` 로 신규 소스를 과거 데이터까지
백필할 수 있다(생략 시 증분 수집만 수행).

**티커(SEC/DART) 추가일 때는 `--sources sec_filing,dart`로 범위를 제한할 것.** `collect`는
기본적으로 config에 설정된 모든 소스를 함께 돈다 - 티커 하나 추가하려고 무제한 `collect
--backfill 365`를 돌리면 companies.yaml/dart_companies.yaml뿐 아니라 Naver 블로그·Telegram
채널처럼 티커와 무관한 고정 구독 소스까지 1년치 전부 재수집하게 되어 시간이 크게 늘고(수십
분~시간 단위) 중간에 끊길 위험도 커진다. 예:

```
uv run python -m investor_intel collect --backfill 365 --sources sec_filing,dart
```

Naver/Telegram 등 다른 소스를 새로 추가했을 때만 전체 범위 백필이 필요하다.

## 분석 관점(투자 원칙) 커스터마이징

일일 리포트가 "무엇을 우선시할지"는 `vault/00_System/Investment_Mandate.md`에 있다. 이
파일은 코드가 아니라 데이터이므로, 직접 편집하면 다음 `run-daily`(크론 또는 수동 실행)부터
바로 반영된다 — 재배포나 재시작이 필요 없다. 예: "최근 호재 뉴스에 가중치를 더 두고 싶다",
"아직 안 알려진 초기 단계 종목을 우선 찾아달라" 같은 지침을 여기에 문장으로 적으면 된다.

`config/prompts/*.md`(extract_claims/daily_report 등)도 마찬가지로 실행 시점에 실제로
로드되는 프롬프트 원본이다 — 추출/종합 단계의 세부 지시를 바꾸고 싶으면 이 파일들을 직접
고친다.

## 포트폴리오 갱신

`vault/30_Portfolio/portfolio.yaml`을 직접 편집한다. `quantity`/`average_cost`를 실제 보유
현황으로 갱신하고, 종목별 `thesis`(투자논리)를 채워두면 이후 리포트 서술의 맥락이 된다.
`constraints`(레버리지/공매도/옵션 허용 여부, 최대 종목/섹터 비중)를 벗어나는 포지션은 `portfolio`
명령 실행 시 가드레일 위반으로 표시된다.

### 투자 가설 원장 작성

포트폴리오 모니터가 "오늘 자료가 기존 가설을 얼마나 바꿨는가"를 판단하려면 비교 기준이
있어야 한다. `portfolio.yaml`의 각 포지션에 다음을 채워둔다 (비워두면 그 항목은 판단에서
빠진다 — 없는 값을 지어내지 않는다):

- `thesis`: 이 종목을 산 이유 (한두 문장)
- `key_kpis`: 매일 확인할 지표 목록 (예: `["수주잔고", "가동률", "고객 집중도"]`)
- `invalidation_condition`: 투자 가설이 무효화되는 조건
- `next_catalyst`: 다음으로 예상되는 촉매
- `fair_value_low`/`fair_value_high`: 적정가치 범위
- `max_position_weight`: 이 종목만의 비중 상한 (없으면 `constraints.max_single_position_weight`
  전역값 적용)

## 신호 로그

`vault/40_Analysis/Claims/<종목>.md`에 포트폴리오 모니터가 매일 판단(신호/강도/근거)을
날짜별로 append한다. 다음날 실행이 마지막 섹션을 "전일까지의 핵심 판단"으로 읽어들이므로,
같은 뉴스에 매일 반복 반응하지 않고 판단의 연속성이 생긴다. 직접 수정하지 않는 것을
권장한다.
