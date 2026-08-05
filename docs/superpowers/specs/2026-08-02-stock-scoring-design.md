# 종목별 정량 스코어링 시스템 — 설계 문서

- 작성일: 2026-08-02
- 상태: 사용자 확정 요구사항(사용자 제공 스펙, 25개 섹션) + 저장소 기존 아키텍처 재사용 결합

## 1. 배경 및 목적

기존 `investor_intel`은 포트폴리오 모니터(`llm/portfolio_monitor.py`)가 보유 종목별로
자유형 LLM 판단(`signal`/`signal_strength`)을 매일 내리고, `regime/` 모듈이 시장 전체
매크로 국면을 결정론적으로 0-100 스코어링한다. 이번 확장은 그 사이 빈 자리 — **종목별
투자 매력도를 결정론적 규칙으로 채점**하는 계층 — 을 새로 만든다. LLM은 사실 추출·정성
판단·반론에만 쓰고, 최종 점수 산술은 항상 코드가 담당한다는 원칙은 `TenbaggerVerification`
(코드가 `total_score`를 재계산)과 동일하게 유지한다.

기본 대상 종목: SK하이닉스(000660.KS), 삼성전자(005930.KS) — `config/scoring/universe.yaml`에
등록, 종목 목록은 이 파일만 고치면 추가/변경된다(코드 변경 불필요).

## 2. 사용자 확정 요구사항 요약 (전체 프롬프트 25개 섹션 원문은 대화 로그 참고)

- 5계층: 수집(기존 collectors 재사용) → 정규화/Feature(`scoring/models.py` Feature) →
  결정론적 스코어링(`scoring/categories.py` 등) → LLM 정성분석/반론(`llm/evidence_collector.py`
  등 4역할) → 사후검증(`scoring/evaluation.py`).
- 대분류 가중치(공통): 매크로15/수요20/펀더멘털25/실적15/밸류10/가격10/리스크5.
  메모리 섹터 오버레이(`config/scoring/sector_memory.yaml`): 매크로10/수급25/펀더멘털25/
  실적15/밸류10/가격10/리스크5.
- 하드게이트가 발동하면 총점과 무관하게 신규 매수 신호 차단(`scoring/hard_gates.py`).
- 히스테리시스: 신규진입 72 / 유지 62 / 축소검토 55 / 매도검토 45, 대기 5거래일
  (`scoring/hysteresis.py`, `regime/signal_state.py`의 WATCH→CONFIRMED 패턴을 매매신호용으로
  재구성).
- Bear/Base/Bull 밸류에이션 시나리오(peak/current forward/normalized midcycle EPS × 배수) —
  `scoring/valuation_scenarios.py`. 목표주가(애널리스트)는 어떤 스코어링 입력에도 필드 자체가
  존재하지 않는다(타입 수준 강제, 테스트로 검증).
- 평균 매수가/현재 비중은 스코어링에 절대 들어가지 않는다 — `config/scoring/universe.yaml`은
  `portfolio.yaml`과 완전히 분리된 파일이며 `average_cost`/`quantity` 필드가 없다(테스트로
  검증).
- Champion/Challenger + 워크포워드 비교 + 최소표본(20건) 게이트(`scoring/evaluation.py`,
  `model_registry/`).
- point-in-time 조회(`scoring/snapshot.score_at_or_before`)로 미래정보 누출 방지.

## 3. 사용자와 합의한 3가지 설계 분기 (대화 중 AskUserQuestion으로 확정)

1. **LLM 예산**: 신규 LLM 4역할(Evidence Collector/Fundamental Analyst/Bear Case Critic/
   Model Reviewer)은 주간(`score run-weekly`)+이벤트 전용. 일간(`score compute`)은 완전히
   LLM-프리 — 가격/재무제표 성장률만 갱신하고 밸류에이션·EPS수정 카테고리는 가장 최근 주간
   스냅샷을 그대로 이어받는다(`scoring/snapshot.py`의 carry-forward 필드). 기존 하루 $1.5
   예산과 충돌하지 않는다.
2. **구조화 데이터 조달**: TrendForce/IBES 등 유료 산업·컨센서스 데이터는 전혀 연동하지
   않는다(확인됨, `regime/collectors/unavailable_stub.py`에 이미 동일하게 명시). 대신 이미
   매일 수집 중인 국내 IB 리포트(`naver-weekly-hot`/`naver_research`)에서 Evidence Collector가
   구조화 추출한다(`document_assets` 테이블 조인으로 종목별 최근 문서를 찾는다,
   `pipeline/stock_score.find_recent_documents_for_ticker`).
3. **구현 범위**: 25개 섹션 전체를 한 세션에서 순서대로 구현(설정+결정론적 스코어링 →
   LLM 4역할 → 하드게이트/히스테리시스/보고서 → Champion/Challenger+백테스트+테스트).

## 4. 알려진 한계 (완료 보고에서 그대로 재확인)

- 밸류에이션 시나리오(bear/base/bull EPS×배수 선정)는 사이클 국면 판단이 필요해 완전
  자동화하지 않았다 — `run-weekly`가 직전 시나리오를 이어받을 뿐, 새 시나리오 산출은 현재
  CLI에서 수동 입력을 전제로 한다.
- Champion/Challenger 워크포워드 비교는 프레임워크만 완성 — 스냅샷이 최소 20건 쌓이기
  전까지는 실제 비교가 항상 "표본 부족"으로 보류된다(정상 동작, 버그 아님).
- 벤치마크는 KOSPI/S&P500/NASDAQ100/PHLX_SEMICONDUCTOR만 Yahoo 무료 심볼로 지원 —
  KRX_SEMICONDUCTOR(코스피 반도체 지수)는 지원하지 않아 상대강도가 missing으로 남는다.
- Yahoo `fundamentals-timeseries`(crumb 인증 필요) 엔드포인트는 환경에 따라 429 rate limit이
  걸릴 수 있다 — 이 경우 재무제표 기반 feature(capex_growth 등)만 missing 처리되고 가격 기반
  카테고리는 정상 계산된다(우아한 성능저하, 크래시하지 않음 — 실제로 이 세션에서 확인됨).
- 통계적 유의성 검정(t-test 등)은 구현하지 않았다 — 최소표본 게이트와 경제적 유의성(초과수익
  차이 절대값 기준)만으로 1차 필터링하고, 정식 통계 검정은 사람이 승인 단계에서 추가로 한다.
