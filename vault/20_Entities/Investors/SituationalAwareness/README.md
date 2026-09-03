# Situational Awareness LP (Leopold Aschenbrenner) — 2026 Q2 13F에서 추론한 매크로·섹터 가설

`vault/20_Entities/Investors/ThielMacro/`와 같은 목적의 참고 아카이브다. 타인의 13F를
해부해 "이 사람은 무엇에 베팅했고, 그 베팅이 유효하려면 무엇이 사실이어야 하는가"를
고정해 둔다.

**출처(1차)**: [SEC EDGAR 13F-HR, CIK 0002045724, 2026-08-14 제출, 보고기준일 2026-06-30](https://www.sec.gov/Archives/edgar/data/2045724/000093583626000418/0000935836-26-000418-index.htm)
**직전 분기**: [13F-HR, 2026-05-18 제출, 기준일 2026-03-31](https://www.sec.gov/Archives/edgar/data/2045724/000204572426000008/0002045724-26-000008-index.htm)
**관련 에세이**: [situational-awareness.ai](https://situational-awareness.ai/) — 저자 본인의 AI 로드맵
**교차검증**: [Seeking Alpha — Situational Awareness massive bets on SanDisk, Micron](https://seekingalpha.com/news/4633584-situational-awareness-massive-bets-sandisk-micron), [AOL — 13F Reveals an $11 Billion AI Bet That Unraveled in Under a Month](https://www.aol.com/articles/situational-awareness-13f-reveals-11-214819000.html), [Globe and Mail](https://www.theglobeandmail.com/investing/markets/stocks/MU/pressreleases/3865299/leopold-aschenbrenners-situational-awareness-reveals-massive-micron-and-sandisk-bets-before-july-collapse/)
**작성일**: 2026-08-28 (KST)

---

## 0. 이 문서의 숫자를 읽을 때의 한계 (중요)

- **금액·비중은 SEC 원문 정보표를 직접 파싱했다.** 그런데 **이 필링의 상위 두 종목은
  주당 내재가가 시장가의 약 10배로 나온다**:
  - SanDisk: 2,495,344주 / 신고가치 $5.67B → **주당 $2,274** (실제 SNDK는 200달러대)
  - Micron: 4,828,786주 / 신고가치 $5.57B → **주당 $1,154** (실제 MU는 100달러대)
  나머지 종목(CoreWeave $99.5, Core Scientific $25.6, TSMC $477 등)은 시장가에 근접한다.
  즉 **SanDisk·Micron 두 행에 단위/집계 이상**이 있다. 언론도 필링 총액($20.2B)이 아니라
  [실질 순노출을 "약 $11B"로 보도](https://www.aol.com/articles/situational-awareness-13f-reveals-11-214819000.html)한다.
- **이 펀드는 필링 오류 전력이 있다.** 2024-12-31 최초 13F에서 보유가치를 1,000배
  부풀려 신고했다($254M을 $254B로). 아래 26Q2 총액과 상위 2종목 절대금액은
  **"신고된 값"으로만 취급**하고, 실질 규모는 그 절반 수준(~$10B)일 수 있다고 본다.
- **13F는 롱만 보여준다.** 직전 분기(26Q1)에는 NVDA·AVGO·ORCL·AMD·ASML·MU·TSMC에
  대한 **대규모 풋(put) 포지션**이 있었다(합계 신고가치 $8B+). 이 펀드는 공개적으로
  "AI 하드웨어 롱 + 소프트웨어 숏" 전략이라, 롱 바스켓만 보면 방향을 절반만 본다.
- **분기말 스냅샷 + 45일 시차.** 2026-06-30 기준. [언론 보도에 따르면 7월에 롱·숏
  양쪽이 동시에 역행](https://seekingalpha.com/news/4633584-situational-awareness-massive-bets-sandisk-micron)했다 —
  이 스냅샷은 사실상 고점에서 찍힌 사진이다.
- **AUM 대비 비중**: 아래는 **13F 신고 총액($20.2B, 신고 기준) 대비 비중**이다. 펀드는
  2024년 약 $1.5B로 출범했다고 알려져 있어, 신고 총액이 실제 자기자본이라면
  극단적 레버리지이거나, 신고가 부풀려진 것이다. **둘 중 무엇이든 이 괴리 자체가
  이 펀드의 핵심 리스크**다.

---

## 1. 포트폴리오 스냅샷 (2026-06-30, 신고 총액 $20.2B / 26개 포지션 / 직전 분기 $13.7B·42개)

| # | 종목 | 신고 평가액 | 비중 | 직전 분기 대비 | 성격 |
| ---: | --- | ---: | ---: | --- | --- |
| 1 | SanDisk (SNDK) | $5.67B* | 28.0% | +683% (대폭 증가) | NAND — AI 스토리지 |
| 2 | Micron (MU) | $5.57B* | 27.5% | 사실상 신규 | DRAM/HBM/NAND |
| 3 | Bloom Energy (BE) | $1.90B | 9.4% | +116% (증가) | 온사이트 발전(연료전지) |
| 4 | TSMC (TSM) | $1.27B | 6.2% | 사실상 신규(롱 전환) | 파운드리 |
| 5 | Nebius (NBIS) | $1.23B | 6.1% | 신규 | AI 클라우드(neocloud) |
| 6 | CoreWeave (CRWV) | $745M | 3.7% | +34% | AI 클라우드 |
| 7 | Core Scientific (CORZ) | $666M | 3.3% | +71% | 채굴→AI 데이터센터 전환 |
| 8 | STMicroelectronics (STM) | $584M | 2.9% | 신규 | 아날로그·전력 반도체 |
| 9 | Applied Digital (APLD) | $469M | 2.3% | +47% | AI 데이터센터 임대 |
| 10 | Riot Platforms (RIOT) | $468M | 2.3% | +229% | 채굴→AI 전환 |
| 11 | SharonAI (STAI) | $457M | 2.3% | +2,425% | GPU 클라우드 |
| 12 | IREN (IREN) | $433M | 2.1% | +8% | 채굴→AI 전환 |
| — | CleanSpark·Bitdeer·Hive·WhiteFiber | ~$335M | 1.7% | 전부 증가 | 채굴·AI 겸업 |
| — | Solaris·T1 Energy·Babcock&Wilcox·Keel Infra | ~$318M | 1.6% | Keel 신규 | 전력 인프라·장비 |

`*` 0절 참조 — SanDisk·Micron 절대금액은 주당 내재가가 시장가의 ~10배로, 단위 이상 의심.

**직전 분기(26Q1) 대비 전량 청산**: [NVDA 풋 $1.57B, VanEck ETF 풋 $2.04B, ORCL 풋
$1.07B, AVGO 풋 $1.01B, AMD 풋 $969M, MU 풋 $584M, TSMC 풋 $535M, ASML 풋 $494M,
Intel 풋 $159M](https://www.sec.gov/Archives/edgar/data/2045724/000204572426000008/0002045724-26-000008-index.htm) —
**풋(하방·헤지) 포지션 전량 제거**. 동시에 종목 수가 42→26으로 줄고 상위 5종목 집중도가
48.7%→77.3%로 급등.

---

## 2. 추론된 가설

### H1. "AI의 병목은 연산이 아니라 '메모리'라고 보고, DRAM/NAND 완제품에 포트폴리오의 절반 이상을 집중했다"

**근거**
- [SanDisk 28.0% + Micron 27.5% = 신고 기준 55.5%](https://www.sec.gov/Archives/edgar/data/2045724/000093583626000418/0000935836-26-000418-index.htm).
  Micron은 직전 분기 사실상 미보유(+94,926%)에서 2위로 급부상.
- 직전 분기에 걸었던 [메모리 풋(MU 풋 $584M)을 제거](https://www.sec.gov/Archives/edgar/data/2045724/000204572426000008/0002045724-26-000008-index.htm)하고
  같은 종목을 대량 롱으로 뒤집었다 — 방향 전환이 명확하다.
- 저자의 공개 로드맵([situational-awareness.ai](https://situational-awareness.ai/))은
  "AI 스케일링에는 물리적 인프라가 병목"이라는 논지고, 그중 메모리(HBM·고용량 NAND)를
  가장 타이트한 구간으로 지목해 왔다.

**규모**
- 메모리 2종목: **신고 기준 $11.24B, 13F의 55.5%**. 단위 이상을 감안해 절반으로 보정해도
  **~$5.6B, 여전히 최대 테마**.
- AUM 대비: 신고 총액 대비 55%. 이 펀드는 사실상 "메모리 사이클 레버리지 베팅"이다.

**bull 해석**: AI 학습·추론이 커질수록 HBM과 고용량 스토리지 수요는 GPU보다 더
비선형으로 늘고, 공급(3사 과점)은 증설에 2년이 걸린다. 이익이 가격에 비선형으로
연동되는 자산이라 사이클 초·중반에는 배당주처럼 안전하고 성장주처럼 오른다.
(내 포트폴리오의 삼성전자·SK하이닉스 논리와 동일 — [memory_model.md](../../../30_Portfolio/ValuationModels/memory_model.md) 참조.)

**bear 해석**: 메모리에서 PER은 피크에 최저다. 이 펀드가 55%를 실은 시점(6/30)이
바로 그 피크였을 수 있다 — [7월에 급락](https://qz.com/situational-awareness-13f-micron-sandisk-july-collapse-081826)한 것이
방증. 완제품 사이클은 3사 중 하나가 증설을 발표하는 순간 꺾인다. 헤지(풋)를 다 없앤
상태라 하방이 그대로 열려 있다. Druckenmiller는 같은 분기에 [Micron을 전량
매도](../Duquesne/README.md)했다 — 스마트머니끼리 정반대 베팅.

**이미 반영됐나**: 6/30 시점엔 메모리 강세가 상당 부분 반영. 7월 조정으로 일부 되돌림.
현 시점 판단하려면 최신가 재확인 필요.

**지켜볼 포인트**
- 매월 DRAM·NAND 계약가격 방향 (사이클의 정의). 하락 전환 = H1 반증.
- 삼성·SK하이닉스·Micron의 **증설·CAPEX 발표**. 하나라도 나오면 피크 앞당김.
- SanDisk·Micron 다음 분기 실적의 HBM/eSSD 믹스와 가이던스.
- 다음 13F(2026-11)에서 이 펀드가 메모리 비중을 유지·확대하는지, 아니면 이미
  빠졌는지 — 7월 급락 이후 첫 스냅샷이 결정적.

### H2. "메모리 다음의 병목은 '전력'이다 — 온사이트 발전과 데이터센터 전환주를 두 번째 축으로 깔았다"

**근거**
- [Bloom Energy 9.4%($1.90B), +116% 증가](https://www.sec.gov/Archives/edgar/data/2045724/000093583626000418/0000935836-26-000418-index.htm) —
  단일 종목 3위. 연료전지 온사이트 발전.
- 채굴→AI 전환 클러스터: [Core Scientific 3.3% + Riot 2.3% + Applied Digital 2.3% +
  IREN 2.1% + CleanSpark·Bitdeer·Hive·WhiteFiber](https://hedgefundalpha.com/news/q2-2026-13f-roundup/).
  이들의 공통 자산은 GPU가 아니라 **확보된 계약전력과 부지**다.
- Solaris Energy(모듈형 발전), T1 Energy, Babcock & Wilcox, Keel Infrastructure(신규) —
  전력 장비·인프라.

**규모**
- 전력·발전(BE + Solaris + T1 + B&W + Keel): **~$2.26B, 13F의 11.2%**.
- 채굴→AI 전환(CORZ + RIOT + APLD + IREN + CLSK + BTDR + HIVE + WhiteFiber): **~$2.60B,
  13F의 12.8%**.
- 두 축 합계 **~$4.9B, 13F의 24%** — 메모리 다음으로 큰 묶음.
- AUM 대비: 신고 총액의 약 4분의 1이 "AI의 전력 병목"에 연동.

**bull 해석**: 계산은 맞다 — AI 데이터센터 부하가 급증하는데 그리드 신규 연결은 3~5년
대기다. 그 갭을 메우는 것이 온사이트 발전(BE)과, 이미 전력계약을 쥔 채굴업체의 AI 전환.
내 포트폴리오의 BE 논리와 정확히 같다([BE_model.md](../../../30_Portfolio/ValuationModels/BE_model.md)).

**bear 해석**: 채굴 전환주는 "전력은 있는데 GPU·고객·자금이 없는" 상태가 많고, BE는
백로그 대비 밸류에이션이 이미 공격적이다. Druckenmiller는 같은 분기 Bloom Energy를
전량 매도했다 — 여기서도 스마트머니가 갈린다.

**이미 반영됐나**: BE·CoreWeave·Core Scientific은 상당 부분 반영. 소형 채굴 전환주
(WhiteFiber·Keel)는 덜.

**지켜볼 포인트**
- 각 채굴사의 **AI/HPC 임대 계약 공시**(GW·금액·고객). 대형 계약 확정 = H2 강화.
- BE 분기 총마진(34% 유지 여부)과 신규 대형 수주.
- 데이터센터 신규 전력계약 통계(EIA·유틸리티 IR)의 방향.

### H3. "26Q2에 헤지를 전부 걷어내고 순수 롱으로 전환했다 — AI 인프라 트레이드의 정점 신호"

**근거**
- 직전 분기(26Q1)의 [풋 포지션(NVDA·AVGO·ORCL·AMD·ASML·MU·TSMC·Intel·VanEck ETF,
  신고가치 합계 $8B 이상)이 26Q2에 전량 사라졌다](https://www.sec.gov/Archives/edgar/data/2045724/000093583626000418/0000935836-26-000418-index.htm).
- 동시에 종목 수 42→26, 상위 5종목 집중도 48.7%→77.3%.
- [언론은 이 펀드가 "AI 하드웨어 롱 + 소프트웨어 숏"이었고 7월에 양쪽이 동시에
  역행했다](https://seekingalpha.com/news/4633584-situational-awareness-massive-bets-sandisk-micron)고 보도.

**규모**
- 제거된 풋: 신고 기준 **$8B+** (13F 관점에서 롱 익스포저 방향으로 순전환).
- 남은 포트폴리오: 26개 종목 전부 롱, 상위 5종목이 77%.
- AUM 대비: 헤지 0%. 하방 방어 장치가 없는 상태.

**bull 해석**: 확신이 극에 달했다는 것 — 헤지 비용을 아끼고 전부 방향에 태웠다.
로드맵이 맞다면 이 집중이 최대 수익을 낸다.

**bear 해석**: **역발상 지표로 보면 최악의 신호다.** 한 펀드가 헤지를 다 걷고 단일
테마에 77%를 실은 시점은 흔히 그 테마의 고점이다. `macro_theses.yaml`의
`ai_capex_funding_bottleneck` 가설(AI 인프라 자금조달 병목)이 현실화되면 이 포트폴리오는
방어 수단 없이 그대로 노출된다. 실제로 7월 급락이 그 리허설이었을 수 있다.

**이미 반영됐나**: 이 신호의 함의(과열)는 7월 조정으로 일부 해소. 다음 13F가 이
펀드가 헤지를 다시 넣었는지 보여줄 것.

**지켜볼 포인트**
- 다음 13F(2026-11)에서 **풋 포지션이 재등장하는지** — 재등장 = 펀드도 과열을 인정.
- `hyperscaler_bond_bid_to_cover`(하이퍼스케일러 채권 응찰배율), `ai_revenue_capex_gap`
  등 `macro_theses.yaml` 지표. 병목이 심화되면 이 펀드가 가장 먼저 타격.
- 이 펀드의 월간·분기 수익률 보도(13F 밖 정보).

---

## 3. Devil's Advocate — 이 포트폴리오를 그대로 따라가면 안 되는 이유

**따라갈 만한 근거**: 논지가 선명하다 — "AI의 병목은 물리적 인프라(메모리 > 전력 >
연산)"라는 한 문장으로 26개 종목이 전부 설명된다. 저자는 그 분야를 오래 파온 사람이다.

**따라가면 안 되는 이유**:
1. **신고 숫자를 신뢰할 수 없다.** SanDisk·Micron 절대금액은 주당 내재가가 시장가의
   ~10배고, 이 펀드는 과거 1,000배 오신고 전력이 있다. 절대 규모·AUM 대비 비중을
   그대로 인용하면 안 된다.
2. **헤지가 안 보인다.** 26Q1엔 $8B+ 풋이 있었다. 26Q2 롱 바스켓만 보고 "풀 리스크온"
   으로 읽으면 반대편을 놓친다. 다음 분기에 풋이 돌아올 수 있다.
3. **타이밍이 최악에 가깝다.** [7월 급락](https://qz.com/situational-awareness-13f-micron-sandisk-july-collapse-081826)
   직전, 헤지 없이 단일 테마 77% 집중 — 이건 따라 들어갈 진입점이 아니라 경계할
   과열 신호다.
4. **내 포트폴리오와 정확히 겹친다.** 이 펀드의 메모리(H1)·전력(H2) 축은 내 보유
   삼성전자·SK하이닉스·BE·NBIS와 같은 베팅이다. 여기서 아이디어를 더 가져오면 분산이
   아니라 **집중도를 높이는 것**이다. 오히려 이 펀드의 **7월 급락은 내 메모리·BE
   포지션의 하방 시나리오 리허설**로 봐야 한다.

**판단**: 이 문서의 가치는 ① 내 메모리·전력 테제의 **강한 동조 사례이자 동시에 과열
경보**, ② `macro_theses.yaml`의 AI 자금조달 병목 가설이 현실화될 때 무엇이 먼저
깨지는지 보여주는 관측 대상이다. 매수 후보 목록으로는 쓰지 않는다.

---

## 4. 갱신 규칙

- **분기 13F(2·5·8·11월 중순)마다** 1절 표에 보유 변화를 추가한다. 특히
  **풋 포지션의 재등장 여부**와 **집중도 변화**를 최우선으로 본다.
- 금액은 SEC 원문에서 재계산하되, 주당 내재가가 시장가와 크게 어긋나는 행은 "신고 기준"
  이라고 명시하고 실질 규모를 별도로 추정한다.
- 7월 급락 이후 첫 스냅샷(2026-11 공시분)이 이 펀드 판정에 가장 중요하다.
- 최초 작성 2026-08-28. 기준일 2026-06-30.
