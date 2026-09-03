# Baillie Gifford & Co — 2026 Q2 13F에서 추론한 매크로·섹터 가설

`vault/20_Entities/Investors/ThielMacro/`와 같은 목적의 참고 아카이브다. 타인의 13F를
해부해 "이 사람은 무엇에 베팅했고, 그 베팅이 유효하려면 무엇이 사실이어야 하는가"를
고정해 둔다.

**출처(1차)**: [SEC EDGAR 13F-HR, CIK 0001088875, 2026-08-06 제출, 보고기준일 2026-06-30](https://www.sec.gov/Archives/edgar/data/1088875/000108887526000057/0001088875-26-000057-index.htm)
**직전 분기**: [13F-HR, 2026-05-08 제출, 기준일 2026-03-31](https://www.sec.gov/Archives/edgar/data/1088875/000108887526000037/0001088875-26-000037-index.htm)
**교차검증**: [Seeking Alpha — Tracking Baillie Gifford's 13F Portfolio Q2 2026](https://seekingalpha.com/article/4932583-tracking-baillie-giffords-13f-portfolio-q2-2026-update), [Yahoo — Baillie Gifford's Top Q2 2026 Move: Space Exploration Technologies at a 7.97% Portfolio Impact](https://finance.yahoo.com/markets/stocks/articles/baillie-giffords-top-q2-2026-201009830.html), [finews — SpaceX Creates a High-Class Problem for Baillie Gifford](https://www.finews.com/news/english-news/73275-spacex-baillie-gifford-scottish-mortgage-concentration-risk)
**작성일**: 2026-08-28 (KST)

---

## 0. 이 문서의 숫자를 읽을 때의 한계

- **금액·비중은 SEC 원문 정보표를 직접 파싱했다.** Baillie Gifford 필링은 원 달러 단위
  (2023년 이후 규칙)로 정상. 총액 $110.23B, SpaceX 주당 내재가 $170.9로 사모 마크와 정합.
- **이 13F는 Baillie Gifford의 미국 상장주식만이다.** 회사 전체 운용자산은 2026년 기준
  약 **£180~197B**([about us](https://www.bailliegifford.com/en/uk/individual-investors/about-us/),
  [Portfolio Adviser](https://portfolio-adviser.com/baillie-gifford-suffers-113bn-drop-in-assets-under-management/))로,
  상당 부분이 영국·유럽·글로벌·비상장 펀드다. **13F($110B)는 회사 AUM의 절반 이하**다.
- **273개 포지션의 초분산 포트폴리오.** 상위 종목의 비중 변화가 곧 하우스 뷰이며,
  꼬리 종목은 개별 펀드매니저 재량이 섞여 있다.
- **분기말 스냅샷 + 45일 시차.** 2026-06-30 기준.
- **AUM 대비 비중**: 아래는 ① **13F 총액 $110.23B 대비**, ② **회사 전체 AUM(≈$250B
  환산) 대비** 두 가지로 표기한다.

---

## 1. 포트폴리오 스냅샷 (2026-06-30, 미국 13F $110.23B / 273개 포지션 / 직전 분기 $97.89B·271개)

| # | 종목 | 평가액 | 13F 비중 | 직전 분기 대비 | 성격 |
| ---: | --- | ---: | ---: | --- | --- |
| 1 | **Space Exploration Technologies (SpaceX)** | **$8.78B** | **8.0%** | **신규** | 상업우주 — 6월 상장 후 13F 편입 |
| 2 | NVIDIA (NVDA) | $8.38B | 7.6% | +18% (증가) | AI 연산 |
| 3 | Amazon (AMZN) | $6.42B | 5.8% | +10% (주가), 주식수 축소 | 하이퍼스케일러·이커머스 |
| 4 | MercadoLibre (MELI) | $5.16B | 4.7% | −8% (축소) | 중남미 이커머스·핀테크 |
| 5 | Sea Ltd (SE) | $3.68B | 3.3% | +12% | 동남아 이커머스·게임 |
| 6 | Spotify (SPOT) | $3.64B | 3.3% | −9% (축소) | 스트리밍 |
| 7 | Cloudflare (NET) | $3.58B | 3.2% | +9% | 엣지 인프라 |
| 8 | AppLovin (APP) | $3.33B | 3.0% | +25% (증가) | 광고 기술 |
| 9 | Shopify (SHOP) | $3.24B | 2.9% | −6% (축소) | 이커머스 SaaS |
| 10 | Nu Holdings (NU) | $3.07B | 2.8% | −13% (축소) | 브라질 디지털은행 |
| — | Rocket Lab / Joby / Aurora / AeroVironment | ~$2.14B | 1.9% | 전부 유지·증가 | 우주·자율·방산 |
| — | Broadcom(+1,631%) / Astera Labs(+293%) / KLA(신규) | ~$0.9B | 0.8% | 증가·신규 | AI 반도체 후공정 |
| — | QXO(+213%) / RBC Bearings(+206%) / Comfort Systems(+36%) | ~$1.7B | 1.6% | 전부 증가 | 건자재·전동화·HVAC |

**주요 축소**: [Netflix −45%, Microsoft −29%, Meta −23%, Atlassian −58%, Wix −53%,
Autodesk −39%, Coupang −40%, PDD −30%](https://www.sec.gov/Archives/edgar/data/1088875/000108887526000057/0001088875-26-000057-index.htm)
— 고멀티플 소프트웨어와 일부 이머징 이커머스를 광범위하게 덜어냈다.

---

## 2. 추론된 가설

### H1. "'제2의 우주 시대'가 투자 가능한 자산군이 됐다 — SpaceX를 상장 직후 곧바로 최대 포지션으로"

**근거**
- [SpaceX(51,397,806주)를 신규 편입, 즉시 13F 1위(8.0%, $8.78B)](https://finance.yahoo.com/markets/stocks/articles/baillie-giffords-top-q2-2026-201009830.html).
  Baillie Gifford는 비상장 시절부터 SpaceX 최대 외부 주주 중 하나였고, [2026년 6월
  상장으로 그 지분이 13F에 처음 표시](https://www.finews.com/news/english-news/73275-spacex-baillie-gifford-scottish-mortgage-concentration-risk)됐다.
- 같은 테마 확장: Rocket Lab(유지), Joby Aviation(+6%), Aurora Innovation(+25%),
  AeroVironment, American Superconductor — 우주·자율비행·방산.
- [골드만삭스가 "Second Space Age"를 선언](https://www.moomoo.com/community/feed/is-spacex-the-clear-frontrunner-goldman-sachs-declares-a-second-117109713207302)한 것과 시점이 겹친다.

**규모**
- SpaceX 단독: **$8.78B**. 13F 비중 **8.0%** / 회사 AUM(≈$250B) 대비 **약 3.5%**.
- 우주·자율·방산 클러스터 합계(SpaceX + Rocket Lab + Joby + Aurora + AeroVironment):
  **약 $11.0B, 13F의 약 10%**.

**bull 해석**: Baillie Gifford는 원래 "소수의 예외적 성장 기업에 장기 집중"이 철학이고,
Tesla·Amazon·NVIDIA에서 그 방식으로 큰 수익을 냈다. SpaceX는 Starlink(위성인터넷
현금흐름) + 발사 독점 + Starship 옵션의 결합으로, 이들의 프레임에 정확히 부합.
상장으로 유동성이 생겼으니 공모 펀드도 담을 수 있게 됐다.

**bear 해석**: SpaceX는 상장 직후 밸류에이션이 사모 마지막 라운드 대비 크게 뛴 상태일
수 있고, Starlink를 뺀 발사 사업은 아직 이익 기여가 제한적이다. Baillie Gifford는
집중 포지션에서 크게 다친 전력이 있다([Scottish Mortgage의 과거 성장주 조정]).
"철학에 부합"이 "가격이 맞다"는 뜻은 아니다.

**이미 반영됐나**: 상장 직후라 기대가 이미 높다. Starship 상업화·Starlink 가입자
지표가 나와야 추가 리레이팅.

**지켜볼 포인트**
- Starlink 분기 가입자 수·ARPU (상장사면 공시 시작).
- Starship 궤도 시험·상업 발사 일정.
- 다음 13F(2026-11)에서 Baillie가 SpaceX를 추가 매수하는지 vs 집중 리스크로 축소하는지.
- Rocket Lab·Joby 등 위성·자율 클러스터의 동반 강세 여부(테마 확산 확인).

### H2. "고멀티플 소프트웨어에서 물러나 AI '연산 하드웨어'와 '물리적 경제'로 무게를 옮겼다"

**근거**
- 광범위한 소프트웨어 축소: [Netflix −45%, Microsoft −29%, Meta −23%, Atlassian −58%,
  Wix −53%, Autodesk −39%, Datadog −4%, Workday −17%, Paycom −34%](https://www.sec.gov/Archives/edgar/data/1088875/000108887526000057/0001088875-26-000057-index.htm).
- 동시에 반도체 하드웨어 확대: [NVIDIA +18%, Broadcom +1,631%, Astera Labs +293%,
  KLA 신규, Arm +69%, On Semiconductor +22%](https://seekingalpha.com/article/4932583-tracking-baillie-giffords-13f-portfolio-q2-2026-update).
- "물리적 경제" 신규·확대: QXO(건자재 유통) +213%, RBC Bearings +206%, Comfort
  Systems(데이터센터 기계설비) +36%, Watsco(HVAC 유통) +14%, Eaton +16%, Advanced
  Drainage +3%, WillScot +55%.

**규모**
- AI 반도체 하드웨어(NVDA + AVGO + Astera + KLA + Arm + ON + TSMC ADR): **약 $9.9B,
  13F의 약 9%**.
- 물리적 경제 컴파운더(QXO + RBC Bearings + Comfort Systems + Watsco + Eaton + ADS +
  WillScot): **약 $2.6B, 13F의 약 2.4%** — 개별로는 작지만 전부 증가 방향.
- 축소한 소프트웨어 묶음: 직전 분기 대비 대략 $3~4B 순감소.

**bull 해석**: "AI가 소프트웨어를 잠식할 수 있다"는 Aschenbrenner류 논지를 Baillie도
일부 수용해, 잠식 리스크가 있는 애플리케이션 SaaS를 줄이고 잠식 불가능한 층
(GPU·후공정·전력설비·건자재)으로 이동. 성장 철학은 유지하되 노출 지점을 바꾼 것.

**bear 해석**: 소프트웨어 축소가 AI 논지 때문이 아니라 단순 차익실현·리밸런싱일 수
있다([언론도 "gain harvesting"으로 표현](https://seekingalpha.com/article/4932583-tracking-baillie-giffords-13f-portfolio-q2-2026-update)).
반도체 하드웨어는 이미 컨센서스 최선호라 뒤늦은 추격일 위험. 물리적 경제 종목들은
비중이 작아 하우스 뷰라기보다 개별 매니저의 소규모 시도.

**이미 반영됐나**: NVDA·AVGO는 반영 다수. Astera·물리적 경제 종목은 덜.

**지켜볼 포인트**
- 다음 13F에서 소프트웨어 축소가 이어지는지 vs 되돌리는지 — 이어지면 "AI 잠식" 논지를
  진짜로 채택한 것.
- Comfort Systems·Watsco 등 데이터센터 기계설비주의 수주잔고 — AI capex의 실물 확인.

### H3. "중남미·동남아 디지털 소비주는 여전히 코어지만, 선별적으로 이익을 실현 중"

**근거**
- [MercadoLibre −8%, Nu Holdings −13%, Coupang −40%, PDD −30%, Sea Ltd +12%(예외),
  Grab +8%](https://www.sec.gov/Archives/edgar/data/1088875/000108887526000057/0001088875-26-000057-index.htm).
  대부분 축소지만 여전히 상위 10위 안에 MELI·Sea·Nu가 있다.
- 신규·확대: MakeMyTrip +40%(인도 여행), Kaspi.kz +32%(카자흐), Credicorp +9%(페루),
  Remitly +50%(송금).

**규모**
- 이머징 디지털 소비 코어(MELI + Sea + Nu + Coupang + PDD + Grab): **약 $16B, 13F의
  약 14.5%** — 축소했어도 여전히 최대 섹터 묶음 중 하나.
- 회사 AUM 대비: 약 6.5%.

**bull 해석**: 구조적 침투율 성장 스토리는 유효하고, 밸류에이션이 오른 종목만
덜어내는 정상적 관리. Sea를 오히려 늘린 것은 종목 선별이 살아있다는 뜻.

**bear 해석**: 광범위한 축소는 이머징 통화·성장 둔화·미국 관세에 대한 경계일 수 있다.
Coupang −40%, PDD −30%는 "선별적"이라기엔 큰 폭.

**이미 반영됐나**: 종목별로 상이. MELI·Nu는 고평가 논란 상존.

**지켜볼 포인트**
- 다음 분기 각 사 GMV·테이크레이트·핀테크 부문 수익성.
- 브라질·멕시코·인도네시아 금리와 통화.

---

## 3. Devil's Advocate — 이 포트폴리오를 그대로 따라가면 안 되는 이유

**따라갈 만한 근거**: 방향이 일관된다 — 우주(SpaceX)를 코어로 승격, AI를 소프트웨어
층에서 하드웨어 층으로 이동, 이머징 소비는 차익실현. 273종목이지만 상위 30종목이
포트폴리오의 대부분을 설명한다.

**따라가면 안 되는 이유**:
1. **13F는 회사 AUM의 절반 이하다.** Baillie Gifford의 진짜 그림은 영국·글로벌·비상장
   펀드에 있다. 미국 13F만으로 "하우스 뷰"를 단정하면 안 된다.
2. **SpaceX는 따라 살 수 없다.** 상장됐지만 유통물량·락업 구조를 모른 채 진입가만
   보고 추격하면 위험. Baillie의 평균 매입가는 사모 시절 원가라 손익 구조가 완전히 다르다.
3. **집중 리스크 전력.** 이 하우스는 성장주 집중에서 크게 다친 이력이 있다
   ([finews도 SpaceX 집중을 "high-class problem"으로 지적](https://www.finews.com/news/english-news/73275-spacex-baillie-gifford-scottish-mortgage-concentration-risk)).
4. **회전이 느리고 대형주 위주.** 알파 원천이 "10배 종목 조기 발굴"(Investment_Mandate
   최우선)과는 다른, 이미 큰 성장주의 장기 보유다.

**판단**: 이 문서의 실용적 가치는 ① **"AI 잠식"이 소프트웨어 투자자의 실제 행동으로
번지는지**(H2) 확인할 관측점, ② 우주가 테마로 성립하는지의 조기 신호(H1)다.
SpaceX 자체는 매수 후보가 아니라, 위성·발사 밸류체인(Rocket Lab 등)으로의 파급을
지켜보는 앵커로 쓴다.

---

## 4. 갱신 규칙

- **분기 13F(대략 1·5·8·10월 하순, Baillie는 제출이 다소 이르다)마다** 1절 표의
  상위 30종목을 갱신한다. 소프트웨어 축소/AI 하드웨어 확대의 **지속성**을 최우선으로 본다.
- 금액은 SEC 원문 정보표에서 재계산한다. vault 13F 마크다운의 legacy 값은 쓰지 않는다.
- 회사 전체 AUM 수치는 반기마다 Baillie Gifford 공식 사이트에서 갱신한다(13F에 없음).
- 최초 작성 2026-08-28. 기준일 2026-06-30.
