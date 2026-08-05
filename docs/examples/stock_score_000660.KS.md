> **참고 (Mock 아님)**: 이 리포트는 2026-08-03 `investor_intel score compute 000660.KS`를
> 실제로 실행해 나온 라이브 결과다 — 가격/거래량은 실제 Yahoo Finance 데이터, macro_liquidity는
> 이 저장소의 실제 `vault/60_MarketRegime/` 관측치다. 아직 `score run-weekly`를 한 번도
> 실행하지 않은 상태라 메모리 산업 지표·실적 전망·밸류에이션 카테고리는 정상적으로 missing으로
> 표시된다(버그가 아니라 "daily-only" 실행의 정확한 동작). 분기 재무제표 조회는 이 환경에서
> Yahoo crumb 엔드포인트가 429(rate limit)를 반환해 실패했다는 점도 그대로 남겨뒀다 — 실전
> 환경에서는 이 항목이 정상적으로 채워진다.
>
> **영역별 점수 배경 표기**: 각 카테고리 점수 아래 들여쓰기된 줄이 그 점수를 만든 근거(수치·
> 기간·출처 링크)다 - price_supply_demand/macro_liquidity처럼 별도 모듈이 직접 계산하는
> 카테고리는 LLM 호출 없이 이미 가진 수치를 그대로 요약한다(결정론적 생성). 긍정/부정 요인
> (섹션 6/7)도 마찬가지로 claim + 3-5줄 배경 + 출처 링크 구조를 따르지만, 이번 실행은
> `score compute`(daily-only)라 Fundamental Analyst가 호출되지 않아 비어 있다 - `score
> run-weekly`를 실행하면 채워진다.

---

# 000660.KS — 2026-08-03

## 1. 현재 판단

- 총점: 58.6
- 전일 대비: -4.5
- 1주 대비: N/A
- 1개월 대비: N/A
- 신뢰도: 0.15 (low)
- 현재 상태(신호): hold_watch
- 투자 가설 상태: maintained
- 하드 게이트: 없음

## 2. 영역별 점수

- memory_supply_demand_pricing: N/A (가중치 25, 커버리지 0%, 기여 feature 0개)
- company_fundamentals_hbm_competitiveness: N/A (가중치 25, 커버리지 0%, 기여 feature 0개)
- oversupply_and_other_risk: N/A (가중치 5, 커버리지 0%, 기여 feature 0개)
- earnings_outlook: N/A (가중치 15, 커버리지 0%, 기여 feature 0개)
- normalized_valuation: N/A (가중치 10, 커버리지 0%, 기여 feature 0개)
- price_supply_demand: 37.5 (가중치 10, 커버리지 100%, 기여 feature 1개)
  - 종가 1,567,000 (기준일 2026-08-03)
  - 200일 이동평균(1,181,288) 위에 위치
  - 20거래일 벤치마크 대비 상대수익률 -12.74%p
  - 52주 고점 대비 -47.54%
  - 출처: [Yahoo Finance](https://finance.yahoo.com/quote/000660.KS)
- macro_liquidity: 79.7 (가중치 10, 커버리지 100%, 기여 feature 1개)
  - ICE BofA US High Yield OAS: 2.84pct (2026-07-30)
  - Chicago Fed Adjusted National Financial Conditions Index: -0.56index (2026-07-24)
  - 시장 폭(Market Breadth): 66.3pct_above_200dma (2026-08-02)
  - VIX 기간구조: 0.778ratio (2026-07-31)
  - 고용 냉각 복합지표: -8.5pct_yoy (2026-07-25)
  - 출처: [FRED (Federal Reserve Bank of St. Louis)](https://fred.stlouisfed.org/series/BAMLH0A0HYM2)
  - 출처: [FRED (Federal Reserve Bank of St. Louis)](https://fred.stlouisfed.org/series/ANFCI)
  - 출처: [Wikipedia S&P 500 constituents + Yahoo Finance](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies)
  - 출처: [Yahoo Finance (Cboe VIX/VIX3M)](https://finance.yahoo.com/quote/%5EVIX)
  - 출처: [FRED (Federal Reserve Bank of St. Louis)](https://fred.stlouisfed.org/series/IC4WSA)

## 3. 새롭게 확인된 사실

(주간/이벤트 평가에서 Evidence Collector가 추출한 근거 - 출처/발표일 포함, run-weekly 로그 참고)

## 4. 이전 평가 대비 변경점

- 점수 변화: 1일 -4.5 / 1주 N/A / 1개월 N/A

## 5. 시장 기대 대비 평가

(Fundamental Analyst의 consensus_comparison 판단 - run-weekly에서만 갱신됨)

## 6. 긍정 요인

- 없음

## 7. 부정 요인

- 없음

## 8. 반대 논리

(Bear Case Critic 출력 - run-weekly에서만 갱신됨)

## 9. 시나리오

- 밸류에이션 시나리오 없음 (run-weekly 실행 후 채워짐)

## 10. 매매 판단

- 신호: hold_watch (신호 시작일: 2026-08-02)
- 추가 매수/비중 축소/무효화 조건은 아래 §11 참고

## 11. 다음 확인 지표

- 없음

## 12. 데이터 품질

- model_version: 1.0.0
- 누락된 핵심 데이터: 35건 (예: dram_contract_price_qoq, dram_spot_price_qoq, nand_contract_price_qoq, hbm_price_qoq, dram_bit_shipment_growth ...)
