> **Mock 데이터 예시**: 이 리포트는 `score run-weekly`까지 실행을 마친 뒤의 모습을 보여주기
> 위해 구성한 예시다. 밸류에이션 시나리오의 EPS/목표 배수, 긍정/부정 요인, 다음 확인 지표는
> 이 대화에서 실제로 읽은 2026-07-31 증권사 리포트 원문(교보/키움/DS/대신/한화/하나)의 실적
> 수치·서술을 참고해 구성했지만, HBM 시장점유율(28%)·재고월수 등 산업 세부 지표와 배수 선택은
> 예시를 위해 임의로 채운 값이다 — 실제 투자 판단에 쓰지 말 것. 실데이터 기반 예시는
> [`stock_score_000660.KS.md`](stock_score_000660.KS.md) 참고.
>
> **영역별 점수 배경 표기**: 각 카테고리 점수 아래 들여쓰기된 줄이 그 점수를 만든 근거(수치·
> 기간·출처 링크)다 - LLM 호출 없이 이미 확보된 Feature/시나리오 데이터를 그대로 요약하는
> 결정론적 생성 방식이다. 긍정/부정 요인(섹션 6/7)은 Fundamental Analyst가 claim(한 줄
> 요약) + rationale(3-5줄 배경) + source_url 세 가지를 채워 넣은 결과다 - 이 예시의 출처
> 링크는 실제 broker 사이트가 아니라 자리표시자(example.com)다.

---

# 005930.KS — 2026-08-02 (Example - 일부 값은 실제 데이터가 아닐 수 있음)

## 1. 현재 판단

- 총점: 84.7
- 전일 대비: N/A
- 1주 대비: N/A
- 1개월 대비: N/A
- 신뢰도: 0.65 (medium)
- 현재 상태(신호): strong_buy_candidate
- 투자 가설 상태: maintained
- 하드 게이트: 없음

## 2. 영역별 점수

- memory_supply_demand_pricing: 78.6 (가중치 25, 커버리지 22%, 기여 feature 5개)
  - dram_contract_price_qoq: 8.5% (2026Q2, [교보증권](https://example.com/kyobo-2026-07-31))
  - hbm_price_qoq: 4.2% (2026Q2, [키움증권](https://example.com/kiwoom-2026-07-31))
  - nand_contract_price_qoq: 6.1% (2026Q2, [DS투자증권](https://example.com/ds-2026-07-31))
  - dram_bit_demand_growth: 22.0% (2026Q2, [대신증권](https://example.com/daishin-2026-07-31))
  - hbm_bit_shipment_growth: 65.0% (2026Q2, [한화투자증권](https://example.com/hanwha-2026-07-31))
  - 출처: [교보증권](https://example.com/kyobo-2026-07-31)
  - 출처: [키움증권](https://example.com/kiwoom-2026-07-31)
  - 출처: [DS투자증권](https://example.com/ds-2026-07-31)
  - 출처: [대신증권](https://example.com/daishin-2026-07-31)
  - 출처: [한화투자증권](https://example.com/hanwha-2026-07-31)
- company_fundamentals_hbm_competitiveness: 100.0 (가중치 25, 커버리지 43%, 기여 feature 3개)
  - hbm4_qualification_status: 개선 (2026-07-31, [하나증권](https://example.com/hana-2026-07-31))
  - capex_growth: 18.3% (2026Q2, [Yahoo Finance fundamentals-timeseries](https://query2.finance.yahoo.com/))
  - free_cash_flow_growth: 12.0% (2026Q2, [Yahoo Finance fundamentals-timeseries](https://query2.finance.yahoo.com/))
  - 출처: [하나증권](https://example.com/hana-2026-07-31)
  - 출처: [Yahoo Finance fundamentals-timeseries](https://query2.finance.yahoo.com/)
- oversupply_and_other_risk: N/A (가중치 5, 커버리지 0%, 기여 feature 0개)
- earnings_outlook: 99.2 (가중치 15, 커버리지 100%, 기여 feature 1개)
  - 1개월 EPS 수정률: +9.4%
  - 애널리스트 상향/하향: 8건 상향 / 0건 하향
  - 가이던스/실적 서프라이즈: +18.2%
- normalized_valuation: 94.2 (가중치 10, 커버리지 100%, 기여 feature 1개)
  - 현재가 61,200 KRW vs 기준(base) 적정가 389,181 KRW
  - 기준 가정: 증권사 컨센서스(교보/키움/DS/대신/한화/하나 평균 목표가 역산)
  - 비관(bear) 적정가 183,144 KRW
  - 낙관(bull) 적정가 543,303 KRW
- price_supply_demand: 35.4 (가중치 10, 커버리지 100%, 기여 feature 1개)
  - 종가 61,200 (기준일 2026-08-02)
  - 200일 이동평균(72,400) 아래에 위치
  - 20거래일 벤치마크 대비 상대수익률 -6.10%p
  - 52주 고점 대비 -42.90%
  - 출처: [Yahoo Finance](https://finance.yahoo.com/quote/005930.KS)
- macro_liquidity: 79.7 (가중치 10, 커버리지 100%, 기여 feature 1개)
  - ICE BofA US High Yield OAS: 2.84pct (2026-07-30)
  - Chicago Fed Adjusted National Financial Conditions Index: -0.56index (2026-07-24)
  - 출처: [FRED (Federal Reserve Bank of St. Louis)](https://fred.stlouisfed.org/series/BAMLH0A0HYM2)
  - 출처: [FRED (Federal Reserve Bank of St. Louis)](https://fred.stlouisfed.org/series/ANFCI)

## 3. 새롭게 확인된 사실

(주간/이벤트 평가에서 Evidence Collector가 추출한 근거 - 출처/발표일 포함, run-weekly 로그 참고)

## 4. 이전 평가 대비 변경점

- 점수 변화: 1일 N/A / 1주 N/A / 1개월 N/A

## 5. 시장 기대 대비 평가

(Fundamental Analyst의 consensus_comparison 판단 - run-weekly에서만 갱신됨)

## 6. 긍정 요인

- **[2Q26 영업이익 89.5조원(QoQ +56%), 컨센서스 대폭 상회](https://example.com/kyobo-2026-07-31)**
  교보증권 2026-07-31 리포트 기준 컨센서스 영업이익 대비 약 15% 상회. HBM 출하량 증가와
  레거시 D램 가격 반등이 겹치며 마진이 예상보다 빠르게 개선됐다. 실적 발표 직후 국내 8개
  증권사가 일제히 목표주가를 상향해 컨센서스 자체가 재산정되는 국면이다.
- **[HBM4 인증 진행 및 국내 8개 증권사 목표주가 일제 상향](https://example.com/hana-2026-07-31)**
  하나증권 2026-07-31 리포트에 따르면 HBM4 1차 인증이 주요 고객사 대상으로 진행 중이며,
  통과 시 4Q26부터 매출 비중이 유의미하게 늘어난다. 인증 실패 시 경쟁사 대비 한 사이클
  뒤처질 위험이 있어 다음 확인 지표(§11)로 추적한다.
- **[5대 데이터센터 고객과 LTA 체결 완료, CAPA의 60~70%까지 확대 계획](https://example.com/kiwoom-2026-07-31)**
  키움증권 2026-07-31 리포트 기준 장기공급계약(LTA)으로 향후 2-3년 물량이 선확보됐다.
  다만 이 계약이 고정가 조건인지 스팟 연동 조건인지에 따라 가격 상승분의 실제 수혜 폭이
  달라진다는 점은 원문에 명시되지 않았다.

## 7. 부정 요인

- **[목표주가 괴리율이 최근 2년간 반복적으로 크게 벌어졌다 좁혀지는 패턴](https://example.com/daishin-2026-07-31)**
  대신증권 2026-07-31 리포트가 지적한 패턴으로, 컨센서스가 실적을 뒤따라가는 경향이 있어
  현재의 목표주가 상향이 이미 반영된 것인지 후행 지표인지 구분이 필요하다. 과거 두 차례
  유사 패턴에서 목표주가 상향 직후 단기 조정이 있었다.
- **[북미 AI Capex 둔화 우려 및 중국 CXMT 상장 이슈로 고점 대비 -42.9% 조정](https://example.com/ds-2026-07-31)**
  DS투자증권 2026-07-31 리포트 기준. 하이퍼스케일러 Capex 증가율 둔화 신호와 중국
  CXMT(창신메모리)의 증설/상장 이슈가 겹치며 밸류에이션 디레이팅이 발생했다. 실제 수요
  둔화인지 일시적 재고조정인지는 3Q26 가이던스로 확인 필요.

## 8. 반대 논리

(Bear Case Critic 출력 - run-weekly에서만 갱신됨)

## 9. 시나리오

- 낙관(bull): EPS 60,367(peak_earnings) × 9.0배 = 543,303 KRW
  - 가정: 2026-2027 HBM 슈퍼사이클 지속 + 대규모 주주환원
  - 무효화 조건: 공급 과잉 전환 또는 정책 리스크
- 기준(base): EPS 45,786(current_forward_earnings) × 8.5배 = 389,181 KRW
  - 가정: 증권사 컨센서스(교보/키움/DS/대신/한화/하나 평균 목표가 역산)
  - 무효화 조건: HBM4 수요 둔화 또는 경쟁 심화
- 비관(bear): EPS 45,786(current_forward_earnings) × 4.0배 = 183,144 KRW
  - 가정: 메모리 업황 급랭 시나리오
  - 무효화 조건: DRAM/NAND 가격 동반 급락 및 재고 급증

## 10. 매매 판단

- 신호: strong_buy_candidate (신호 시작일: 2026-08-02)
- 추가 매수/비중 축소/무효화 조건은 아래 §11 참고

## 11. 다음 확인 지표

- 2026-08 성과급 지급 규모 확정 및 대규모 자사주 매입/특별배당 발표
- 3Q26 실적 발표 - HBM4 매출 비중 확대 여부 확인
- (무효화 조건) 2개 분기 연속 회사 가이던스 하향
- (무효화 조건) HBM4 주요 고객 인증 실패 또는 경쟁사 대비 수율 격차 확대

## 12. 데이터 품질

- model_version: 1.0.0
- 누락된 핵심 데이터: 25건 (예: dram_spot_price_qoq, nand_contract_price_qoq, dram_bit_shipment_growth, dram_bit_demand_growth, dram_bit_supply_growth ...)
