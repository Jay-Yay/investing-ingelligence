# 거장 13F 종합 — 2026 Q2 기준 매크로·섹터 가설 (5개 펀드 교차 판독)

각 펀드 개별 분해는 하위 폴더에 있다:
[Duquesne(Druckenmiller)](Duquesne/README.md) ·
[Situational Awareness(Aschenbrenner)](SituationalAwareness/README.md) ·
[Berkshire(Buffett)](Berkshire/README.md) ·
[Baillie Gifford](BaillieGifford/README.md) ·
[Pershing Square(Ackman)](PershingSquare/README.md) ·
[Thiel Macro](ThielMacro/README.md)

**작성일**: 2026-08-28 (KST). **기준일**: Berkshire·Duquesne·SA LP·Baillie는 2026-06-30,
Pershing Square는 2026-03-31(26Q2 미수집), Thiel Macro는 2026-06-30(별도 분해 완료).

---

## 0. 방법과 한계

- **모든 금액·비중은 SEC EDGAR 13F 정보표 원문을 직접 파싱해 재계산**했다. vault의 13F
  마크다운(`vault/10_Sources/13F/`)은 2026-08-25 이전 수집분이라 `legacy_units` 문제
  (금액 표기 1,000배 오류·다중 슬라이스 병합)가 있어 쓰지 않았다.
- **필러별 단위 주의**: Duquesne는 `<value>`를 **천 달러**로 제출한다(2023년 이후에도) —
  ×1,000 보정했다. Berkshire·Baillie·Pershing·SA LP는 원 달러.
- **SA LP는 신고값을 신뢰할 수 없다**: 상위 2종목(SanDisk·Micron)의 주당 내재가가
  시장가의 ~10배다. 이 펀드는 과거 1,000배 오신고 전력이 있어([2024-12-31 최초 13F](https://www.aol.com/articles/situational-awareness-13f-reveals-11-214819000.html)),
  아래에서 SA LP 절대금액은 "신고 기준"으로만 표기하고 실질은 절반 수준(~$10B)일 수
  있다고 본다.
- **13F는 롱 미국 상장주식만이다.** 공매도·풋·통화·금리·국채·원자재·비상장·해외
  직상장·현금이 전부 빠진다. Druckenmiller와 Ackman은 매크로/헤지 트레이더라 **13F가
  특히 부분적인 그림**이다. Berkshire는 **현금($365.5B)**이 13F보다 크다.
- Investment_Mandate 소스 등급상 **13F는 D등급**(기대·포지셔닝 확인용). 신규 편입 1건으로
  매수 신호를 만들지 않는다. 이 문서는 "여러 펀드에서 독립적으로 같은 흐름이 나타나는가"
  (Mandate 판단원칙 5번, 소스 간 교차검증)를 보는 용도다.

---

## 1. 5개 펀드 한눈에

| 펀드 | 기준일 | 13F 총액 | 포지션 | 스타일 | 26Q2 핵심 액션 | 방어↔공격 |
| --- | --- | ---: | ---: | --- | --- | :---: |
| [Berkshire](Berkshire/README.md) | 6/30 | $299.3B | 29 | 대형 가치·장기 | Alphabet +$17B 신규 대량매수 / 에너지(CVX·OXY) 축소 / 현금 $365B 유지 | 방어 (현금 55%) |
| [Baillie Gifford](BaillieGifford/README.md) | 6/30 | $110.2B (美) | 273 | 성장 장기집중 | SpaceX 신규 즉시 1위 / 소프트웨어 광범위 축소 / AI는 하드웨어로 이동 | 중립 |
| [Duquesne](Duquesne/README.md) | 6/30 | $5.21B | 95 | 매크로·고회전 | AI 네트워킹·메모리완제품·연료전지 전량 매도 → 파운드리·장비·채굴전환·내수민감주 | 중립 (고회전) |
| [Pershing Square](PershingSquare/README.md) | 3/31* | $13.7B | 11 | 초집중 컴파운더 | Microsoft 신규 / Alphabet 사실상 청산 / Brookfield 최대 유지 | 중립 (헤지 불가시) |
| [Situational Awareness](SituationalAwareness/README.md) | 6/30 | $20.2B* | 26 | AI 테마 집중·레버리지 | 메모리(SanDisk·Micron) 55% / 풋 헤지 전량 제거 / 집중도 77% | 극공격 (헤지 0%) |

`*` Pershing은 26Q1 기준(26Q2 미수집), SA LP 총액은 신고 기준.

---

## 2. 여러 거장이 독립적으로 수렴하는 가설

### 합의 A. "AI의 다음 병목은 연산이 아니라 전력이다" — 5개 펀드 중 4개가 어떤 형태로든 노출

**누가**
- [Thiel Macro](ThielMacro/README.md): 포트폴리오의 **53.7%가 발전·유틸·SMR**, 에너지
  전체 71.8%. 사실상 단일 테마.
- [Situational Awareness](SituationalAwareness/README.md): Bloom Energy 9.4% + 전력
  인프라·채굴→AI전환 클러스터 = **신고 기준 약 24%** ($4.9B).
- [Duquesne](Duquesne/README.md): Bitdeer·Hut 8·Riot·IREN(채굴→AI 데이터센터 전환)
  전부 신규 = 13F의 2.4%. Cleveland-Cliffs·Southern Copper(전력망 소재) 증가.
- [Baillie Gifford](BaillieGifford/README.md): Comfort Systems(+36%, 데이터센터
  기계설비) $421M + Eaton(+16%) $255M + Vistra 신규 $119M + EQT(+16%, 가스) $291M.
- [Pershing Square](PershingSquare/README.md): Brookfield **17.6%($2.42B)** — 전력·
  재생에너지·데이터센터 자산 운용사(간접 노출).

**규모(전력 테마 절대 노출, 근사)**: Thiel ~$300M · SA LP ~$4.9B(신고) · Baillie ~$1.1B ·
Duquesne ~$0.13B · Pershing Brookfield $2.42B(부분 프록시). **다섯 명 중 넷이 "AI가 쓸
전기"에 자본을 배치**했다.

**가설**: 데이터센터 부하 급증 vs 그리드 신규 연결 3~5년 대기 → 그 갭을 메우는
온사이트 발전(BE)·기존 전력계약 보유 채굴업체의 AI 전환·전력 기계설비·가스 발전 연료가
재평가된다. (내 포트폴리오의 [BE](../../30_Portfolio/ValuationModels/BE_model.md)·NBIS
논리와 동일.)

**Devil's advocate**: ① 노출 방식이 제각각이다(규제 유틸 vs 머천트 발전 vs 연료전지 vs
채굴 전환 vs 알트에셋). "전력"이라는 단어만 같지 리스크·수익 프로파일은 정반대다.
② [Thiel의 전력주는 6/30 이후 −3~−12% 먼저 빠졌고](ThielMacro/README.md),
[SA LP의 AI 바스켓은 7월에 급락](https://qz.com/situational-awareness-13f-micron-sandisk-july-collapse-081826)했다 —
합의가 곧 고점의 징후일 수 있다. ③ Druckenmiller는 같은 분기 **Bloom Energy를 전량
매도**했다 — 전력 테마 안에서도 "온사이트 발전 장비"는 버렸다.

**지켜볼 포인트**: 데이터센터 신규 전력계약 통계(EIA·유틸 IR) 방향 / 전력주 지수
(유틸리티 XLU 대 S&P 상대강도) / 다음 13F에서 이 넷이 전력 노출을 유지·확대하는지.

---

### 합의 B. "AI 익스포저를 애플리케이션·소프트웨어에서 실리콘·인프라 층으로 내린다"

**누가**
- [Baillie Gifford](BaillieGifford/README.md): Netflix −45%, Microsoft −29%, Meta −23%,
  Atlassian −58%, Wix −53%, Autodesk −39% 축소 ↔ NVIDIA +18%, **Broadcom +1,631%**,
  Astera Labs +293%, KLA 신규.
- [Situational Awareness](SituationalAwareness/README.md): 26Q1엔 소프트웨어·반도체
  **풋(숏)** 보유 → 26Q2엔 메모리·파운드리 롱으로 전환. 전략 자체가 "하드웨어 롱 +
  소프트웨어 숏".
- [Duquesne](Duquesne/README.md): AI 네트워킹·광부품(Broadcom·Lumentum·Coherent) 전량
  매도 → 파운드리·아날로그·장비(TSMC +68%, STMicro +157%, AMD·Lam·Entegris·Rambus 신규).
- [Pershing Square](PershingSquare/README.md): Alphabet −95%(검색 잠식 회피) → Microsoft
  신규(계약형 클라우드·오피스).

**규모**: Baillie의 AI 반도체 하드웨어 묶음 ~$9.9B(13F의 9%) · Duquesne의 파운드리·장비
$619M(11.9%) · SA LP의 메모리+파운드리 신고 기준 $13B+.

**가설**: "생성형 AI가 애플리케이션 SaaS의 해자를 잠식할 수 있다"는 우려가 성장주
투자자의 실제 매매로 번지고 있다. 잠식 불가능한 층(GPU·후공정·소재·전력)이 상대적
안전지대로 재평가된다.

**Devil's advocate**: ① 반도체 하드웨어는 이미 컨센서스 최선호주 — 뒤늦은 추격일 위험.
② Baillie·Duquesne의 소프트웨어 축소가 "AI 잠식 논지 채택"이 아니라 단순 차익실현
(gain harvesting)일 수 있다. ③ [Berkshire는 정반대로 Alphabet(검색)을 $17B 대량
매수](https://www.cnbc.com/2026/08/15/berkshire-adds-17-billion-to-alphabet-stake.html)했다 —
"검색이 잠식된다"는 전제에 스마트머니가 갈린다(합의 A/B와 §3의 대립).

**지켜볼 포인트**: 고멀티플 SaaS 지수(예: WCLD)의 상대 약세 지속 여부 / 소프트웨어
기업 분기 실적의 순매출유지율(NRR) 방향 / 다음 13F에서 소프트웨어 축소가 이어지는지.

---

### 합의 C. "반도체 안에서 파운드리·후공정·장비로 무게중심 이동" — Druckenmiller·SA LP가 같은 분기에 독립적으로

**누가 / 규모**
- [Duquesne](Duquesne/README.md): TSMC 증가($282M), STMicro 대폭 증가($232M),
  AMD·Lam Research·Entegris·Rambus 신규. 파운드리·아날로그·장비 롱 **$619M, 13F의 11.9%**.
  동시에 메모리 완제품(Micron)·네트워킹(Broadcom) 전량 매도.
- [Situational Awareness](SituationalAwareness/README.md): TSMC를 **풋에서 롱으로 전환**
  ($1.27B), STMicro 신규($584M).

**가설**: 시장은 "AI = GPU·네트워킹"에 프리미엄을 다 줬지만, 그 칩을 실제로 찍어내는
파운드리·후공정·소재·아날로그는 덜 리레이팅됐다 → 같은 테마 내 상대가치 거래.

**Devil's advocate**: 파운드리·장비는 반도체 사이클 후반부에 먼저 꺾이는 자산이다.
"덜 반영됐다"가 아니라 "다음에 꺾인다"에 잘못 베팅한 것일 수 있다. TSMC·AMD는 이미
최선호주.

**지켜볼 포인트**: SOX 내 장비주(AMAT·LRCX·KLAC) 대 팹리스(NVDA·AVGO) 상대강도 /
2026년 10월 TSMC 3분기 실적 가이던스.

---

### 합의 D. "채굴 인프라의 AI 데이터센터 전환" — Druckenmiller·SA LP·(Thiel 인접)

**누가**: [Duquesne](Duquesne/README.md) Bitdeer·Hut 8·Riot·IREN 전부 신규(13F의 2.4%,
$126M) · [SA LP](SituationalAwareness/README.md) Core Scientific·Riot·Applied Digital·IREN
= 신고 기준 ~$2.6B(12.8%).

**가설**: 이미 확보된 계약전력·부지를 쥔 채굴업체가 그 전력을 AI/HPC 임대로 돌리면
비트코인 가격과 무관한 현금흐름이 생긴다. 시장은 아직 "채굴주"로만 평가 → 재평가 여지.

**Devil's advocate**: 전환 성공 사례가 소수고, 전력 확보와 AI 임대 계약은 별개다.
GPU 조달·고객 신용·자금조달 리스크가 겹친다. Druckenmiller의 비중이 작다는 것(각
0.1~1.2%)은 그도 확신이 아니라 옵션으로 취급한다는 뜻.

**지켜볼 포인트**: 각 사의 AI/HPC 임대 계약 공시(GW·금액·고객명). 대형 계약 하나가
확정되면 이 가설이 맞는 방향.

---

### 합의 E(약함). "미국 연착륙·금리 완화에 베팅한 내수 경기민감주"

**누가**: [Duquesne](Duquesne/README.md) 주택건설(D.R. Horton·Champion·Cavco) 신규 +
항공(United +347%, Delta 신규) · [Berkshire](Berkshire/README.md) Delta +103% ·
[Baillie](BaillieGifford/README.md) 건자재·전동화(QXO +213%, RBC Bearings +206%).

**가설**: 금리 정점 통과 → 이연된 주택 수요·자본지출이 풀린다.

**Devil's advocate (중요)**: `config/macro_theses.yaml`의 `fed_rate_path` 지표는 **반대로
간다** — [2026-07-29 FOMC에서 3명 위원이 즉시 인상 지지, 30년물 금리 2007년 이후
최고](../../../config/macro_theses.yaml). 인하가 지연되면 이 바스켓이 가장 먼저
되돌림당한다. 6/30 이후 이미 손실 구간일 수 있다. **합의 E는 프로젝트 매크로 뷰와
정면 충돌** — 9월 FOMC가 판정한다.

---

## 3. 갈라지는 지점 — 이게 더 중요한 신호다

| 쟁점 | 한쪽 | 반대쪽 | 함의 |
| --- | --- | --- | --- |
| **메모리 완제품 사이클** | SA LP: SanDisk·Micron 55% 집중(신규 대량) | Druckenmiller: Micron·Broadcom **전량 매도** | 사이클 위치에 대한 정면 대립. 내 [삼성·SK하이닉스](../../30_Portfolio/ValuationModels/memory_model.md) 포지션의 핵심 쟁점 |
| **검색(Alphabet)** | Berkshire: +$17B 대량 매수 | Pershing: −95% 청산 / Baillie: Class A는 +79% 늘리되 MSFT는 축소 | "AI가 검색을 잠식하는가"에 대한 불일치 |
| **하이퍼스케일러 선택** | Pershing: Microsoft 신규 / Berkshire: Alphabet / Baillie: NVDA·AMZN | — | 빅테크 안에서도 베팅 대상이 갈린다(단일 종목 컨센서스 없음) |
| **방어 vs 공격** | Berkshire: 현금 55%, 코어 불변 | SA LP: 헤지 0%, 집중 77% | 같은 시점에 정반대 포지셔닝 — 시장 레짐 판단이 갈린다 |
| **연료전지 온사이트 발전** | SA LP: Bloom Energy 9.4%(증가) | Druckenmiller: Bloom Energy 전량 매도 | 전력 테마 안에서도 "장비" 채택에 이견 |
| **우주** | Baillie: SpaceX 즉시 1위(8%) | 나머지 4개 펀드: 사실상 없음 | 아직 단일 펀드 테마 — 합의 아님 |

**읽는 법**: 합의(§2)는 "테마에 기관 자금이 유입됐다"는 확인이지만, **대립(§3)은
"이 사이클의 어느 지점인가"에 대한 스마트머니의 불확실성**을 드러낸다. 특히 메모리
완제품과 방어/공격 축은 내 포트폴리오와 직접 연결된다.

---

## 4. 종합 매크로 그림과 확인·반증 지표

**한 문장**: 다섯 거장의 26Q2 포지셔닝은 **"AI 자본지출은 계속되지만, 그 수혜가
GPU·소프트웨어에서 → 전력·파운드리·후공정·인프라로 내려간다"**는 방향으로 대체로
수렴한다. 단, ① 지금이 그 트레이드의 초입인지 고점인지, ② 미국 금리가 완화로 가는지에
대해서는 정면으로 갈린다.

**이미 반영됐나**: 전력·반도체 인프라는 6/30 시점에 상당 부분 반영됐고, [7월에 AI
바스켓이 한 차례 조정](https://seekingalpha.com/news/4633584-situational-awareness-massive-bets-sandisk-micron)받았다.
"덜 반영된" 구간은 후공정·소재·아날로그·소형 전력 인프라 쪽.

**확인 지표(가설이 맞는 방향)**
- 유틸리티 지수(XLU)·반도체 장비주가 S&P·팹리스를 아웃퍼폼 시작
- 데이터센터 신규 전력계약·PPA 공시 증가(EIA·유틸 IR)
- 다음 13F(2026-11 중순)에서 전력·파운드리·후공정 노출이 **여러 펀드에서 동시에 확대**
- Comfort Systems·Eaton·Vertiv 등 데이터센터 기계설비주 수주잔고 증가

**반증 지표(가설이 틀리는 방향)**
- 삼성·SK하이닉스·Micron 중 하나라도 **증설·CAPEX 확대 발표** → 메모리 피크 앞당김
- 하이퍼스케일러 회사채 응찰배율 1배 근접(`macro_theses.yaml` `hyperscaler_bond_bid_to_cover`)
  → AI 자금조달 병목 현실화, 인프라 트레이드 조정
- 9월 FOMC 추가 매파 서프라이즈 → 합의 E(내수 민감주) 붕괴, 실물자산 밸류에이션 압박
- 다음 13F에서 SA LP가 풋 헤지를 다시 넣거나 메모리를 축소 → 펀드 스스로 과열 인정

---

## 5. 내 포트폴리오에 대한 함의

- **전력(BE·NBIS 인접)**: 다섯 중 넷이 같은 테마에 노출 — 테마 자체는 검증됨(합의 A).
  그러나 이건 내 [BE](../../30_Portfolio/ValuationModels/BE_model.md)·NBIS 노출을 늘릴
  근거가 아니라 **집중도가 이미 높다는 경고**다. Druckenmiller의 BE 전량 매도와 Thiel
  전력주의 6/30 이후 약세를 하방 시나리오로 본다.
- **메모리(삼성·SK하이닉스)**: §3의 최대 쟁점. SA LP는 55% 올인, Druckenmiller는 완전
  이탈. 내 [memory_model.md](../../30_Portfolio/ValuationModels/memory_model.md)의
  "피크가 몇 분기 더 가는가" 질문에 대해 스마트머니도 답이 갈린다 → 계약가격·증설 발표를
  기존보다 더 촘촘히 감시.
- **RDDT**: Baillie가 Reddit +27% 늘렸다([BaillieGifford](BaillieGifford/README.md)) —
  약한 우호 신호(D등급). 단독 근거로 쓰지 않는다.
- **소비재(달바·에이피알)**: 이 5개 펀드에 직접 대응물 없음. Baillie의 e.l.f. Beauty
  (+20%)·Oddity(+12%)·SharkNinja(+42%) 정도가 인접 — K-뷰티 특정 신호는 아님.

---

## 6. 갱신 규칙

- **분기 13F(2·5·8·11월 중순)마다** §1 표와 §2 합의·§3 대립을 갱신한다. 핵심은
  "합의가 여러 분기에 걸쳐 확대되는가"(강화) vs "한 분기 만에 흩어지는가"(노이즈).
- **26Q2 Pershing Square가 수집되면** [PershingSquare/README.md](PershingSquare/README.md)를
  먼저 갱신하고 이 문서 §1의 `*` 주석을 해제한다.
- **7월 급락 이후 첫 스냅샷(2026-11 공시분)**이 이번 종합의 실질 사후검증이다 — 특히
  SA LP가 메모리·헤지를 어떻게 바꿨는지.
- 금액은 항상 SEC 원문 정보표에서 재계산한다(Duquesne는 ×1,000, SA LP 상위 2종목은
  "신고 기준" 표기). vault 13F 마크다운의 legacy 값은 쓰지 않는다.
- 최초 작성 2026-08-28.
