# Pershing Square Capital Management (Bill Ackman) — 2026 Q1 13F에서 추론한 매크로·섹터 가설

`vault/20_Entities/Investors/ThielMacro/`와 같은 목적의 참고 아카이브다. 타인의 13F를
해부해 "이 사람은 무엇에 베팅했고, 그 베팅이 유효하려면 무엇이 사실이어야 하는가"를
고정해 둔다.

> ⚠️ **기준 시점 주의**: 이 문서는 **2026-03-31 기준 13F(2026-05-15 제출)** 를 근거로 한다.
> 작성 시점(2026-08-28)에 26Q2(6/30 기준) 13F는 아직 이 파이프라인에 수집되지 않았다.
> Pershing Square는 10~11종목의 매우 안정적인 포트폴리오라 분기 간 변화가 작아 26Q1
> 스냅샷으로도 가설 도출이 가능하지만, **아래 수치는 최소 5개월 지난 값**이며 26Q2
> 수집 시 갱신해야 한다.

**출처(1차)**: [SEC EDGAR 13F-HR, CIK 0001336528, 2026-05-15 제출, 보고기준일 2026-03-31](https://www.sec.gov/Archives/edgar/data/1336528/000117266126002336/0001172661-26-002336-index.htm)
**직전 분기**: [13F-HR, 2026-02-17 제출, 기준일 2025-12-31](https://www.sec.gov/Archives/edgar/data/1336528/000117266126001091/0001172661-26-001091-index.htm)
**교차검증**: [Seeking Alpha — Pershing Square discloses new stake in Microsoft in Q1](https://seekingalpha.com/news/4594141-bill-ackmans-pershing-square-discloses-new-stake-in-microsoft-in-q1), [Globe and Mail — Ackman Adds Microsoft While Slashing Alphabet](https://www.theglobeandmail.com/investing/markets/stocks/MSFT/pressreleases/1970443/bill-ackman-adds-microsoft-stake-while-slashing-alphabet-position-in-latest-pershing-square-13f/), [The Market Context — $13.7B Pershing Square Sells Alphabet and Adds Microsoft in AI Cloud Bet](https://themarketcontext.com/article/bill-ackmans-13-7b-pershing-square-sells-alphabet-and-adds-microsoft-in-ai-cloud-bet/), [Hedgeweek — Pershing Square down 11%, Ackman eyes management company IPO](https://www.hedgeweek.com/pershing-square-down-11-as-ackman-eyes-management-company-ipo/)
**작성일**: 2026-08-28 (KST)

---

## 0. 이 문서의 숫자를 읽을 때의 한계

- **금액·비중은 SEC 원문 정보표를 직접 파싱했다.** Pershing Square 필링은 원 달러 단위로
  정상. 총액 $13.71B, Amazon 주당 내재가 $208로 시장가와 정합.
- **13F는 미국 상장주식 롱만이다.** Pershing Square는 과거 대규모 매크로 헤지(금리
  스왑션, CDS)로 큰 수익을 낸 이력이 있고, 이런 포지션은 13F에 안 나온다.
- **초집중 포트폴리오(10~11종목).** 각 종목이 전략 그 자체다. 반대로 회전이 거의 없어
  한 분기 늦은 데이터의 정보 손실이 작다.
- **AUM 대비 비중**: Pershing Square 전체 운용자산은 2026년 초 기준 약 **$20B**
  ([Hedgeweek](https://www.hedgeweek.com/pershing-square-down-11-as-ackman-eyes-management-company-ipo/)),
  그중 상장 폐쇄형 펀드 Pershing Square Holdings(PSH)가 약 $13B. 13F 신고 총액 $13.71B는
  **회사 AUM의 약 69%**로, 미국 롱 주식이 이 회사 자산의 대부분이다(헤지·현금 제외).

---

## 1. 포트폴리오 스냅샷 (2026-03-31, 총 $13.71B / 11개 포지션 / 직전 분기 $15.53B·11개)

| # | 종목 | 평가액 | 13F 비중 | AUM($20B) 대비 | 직전 분기 대비 | 성격 |
| ---: | --- | ---: | ---: | ---: | --- | --- |
| 1 | Brookfield Corp (BN) | $2.42B | 17.6% | 12.1% | −14% (축소) | 대체투자·인프라·전력·부동산 |
| 2 | Amazon (AMZN) | $2.39B | 17.4% | 11.9% | +8% | 하이퍼스케일러·이커머스 |
| 3 | Uber (UBER) | $2.15B | 15.7% | 10.8% | −13% (축소) | 모빌리티 플랫폼 |
| 4 | **Microsoft (MSFT)** | **$2.09B** | **15.3%** | **10.5%** | **신규** | 하이퍼스케일러·AI |
| 5 | Restaurant Brands Intl (QSR) | $1.67B | 12.2% | 8.4% | +7% | QSR 프랜차이즈 |
| 6 | Meta Platforms (META) | $1.52B | 11.1% | 7.6% | −14% (축소) | 소셜·AI |
| 7 | Howard Hughes Holdings (HHH) | $1.19B | 8.7% | 6.0% | −21% (축소) | 마스터플랜 부동산 개발 |
| — | Seaport Entertainment (SEG) | $108M | 0.8% | 0.5% | +9% | 부동산·엔터(HHH 스핀오프) |
| — | Alphabet (GOOGL) | $89M | 0.7% | 0.4% | **−95% (거의 청산)** | — |
| — | Hertz (HTZ) | $70M | 0.5% | 0.4% | −10% | 렌터카 |

**직전 분기 대비 전량 매도**: [Hilton Worldwide($870M)](https://www.sec.gov/Archives/edgar/data/1336528/000117266126002336/0001172661-26-002336-index.htm).
상위 7종목이 포트폴리오의 약 98%.

---

## 2. 추론된 가설

### H1. "AI 익스포저를 애플리케이션·검색이 아니라 하이퍼스케일러 인프라로 좁혔다 — Microsoft 신규, Alphabet 사실상 청산"

**근거**
- [Microsoft를 신규 편입해 곧바로 4위(15.3%, $2.09B)](https://seekingalpha.com/news/4594141-bill-ackmans-pershing-square-discloses-new-stake-in-microsoft-in-q1).
  Pershing Square가 Microsoft를 담은 것은 처음이다.
- 동시에 [Alphabet을 약 680만 주에서 34만 주로 −95%+ 축소](https://www.theglobeandmail.com/investing/markets/stocks/MSFT/pressreleases/1970443/bill-ackman-adds-microsoft-stake-while-slashing-alphabet-position-in-latest-pershing-square-13f/) —
  사실상 청산. Meta도 −14% 축소.
- 언론은 이를 [$1.9B Alphabet ↔ $2.1B Microsoft "스왑"](https://themarketcontext.com/article/bill-ackmans-13-7b-pershing-square-sells-alphabet-and-adds-microsoft-in-ai-cloud-bet/)으로
  표현 — 빅테크 노출을 "검색+소셜"에서 "Azure+OpenAI+오피스 구독"으로 재편했다.

**규모**
- Microsoft: **$2.09B / 13F의 15.3% / AUM의 10.5%**.
- 빅테크 합계(MSFT + AMZN + META + GOOGL 잔여): **약 $6.1B, 13F의 44%** — 여전히
  포트폴리오의 최대 묶음이지만 구성이 바뀌었다.

**bull 해석**: Ackman의 프레임은 "예측 가능한 현금흐름 + 가격결정력 + 재투자 활주로가
긴 소수 기업". Microsoft는 오피스·Azure의 계약형 매출에 AI(Copilot·OpenAI)가 옵션으로
붙어, 검색 광고보다 예측가능성이 높다. Alphabet 청산은 "AI 검색 잠식" 리스크를
회피한 것으로 읽힌다.

**bear 해석**: Microsoft는 AI capex 부담이 가장 큰 하이퍼스케일러이고, PER도 낮지 않다.
Alphabet을 바닥 근처에서 던졌을 위험(검색 잠식 우려가 과장이라면 실수). 또한 이건
26Q1 데이터라, 26Q2에 다시 조정됐을 수 있다.

**이미 반영됐나**: Microsoft·Amazon은 대형주라 반영 다수. 신호로서는 "Ackman이
검색에서 인프라로 갈아탔다"는 방향성.

**지켜볼 포인트**
- 26Q2 13F(수집 시) — Microsoft를 유지·확대했는지, Alphabet을 완전 청산했는지.
- Microsoft Azure 성장률과 AI 매출 기여, capex/FCF 비율.
- Ackman의 공개 코멘터리(X, 투자자 서한) — 그는 포지션 논거를 공개하는 편.

### H2. "포트폴리오의 무게중심이 '실물자산·인프라'로 이동했다 — Brookfield를 최대 포지션으로"

**근거**
- [Brookfield Corp이 17.6%($2.42B)로 최대 포지션](https://www.sec.gov/Archives/edgar/data/1336528/000117266126002336/0001172661-26-002336-index.htm).
  −14% 축소했지만 여전히 1위 — 직전 분기엔 더 컸다는 뜻.
- Howard Hughes Holdings(마스터플랜 커뮤니티 부동산 개발) 8.7% + Seaport Entertainment
  (HHH 스핀오프 부동산) 0.8% 보유. [Ackman은 HHH를 "미니 버크셔"로 만들겠다고 공언](https://whalewisdom.com/filer/pershing-square-capital-management-l-p)해 왔다.
- 실물자산 성격 3종목(BN + HHH + SEG) 합계 27.1%.

**규모**
- Brookfield 단독: **$2.42B / 13F의 17.6% / AUM의 12.1%**.
- 실물자산·인프라 묶음(BN + HHH + SEG): **약 $3.72B, 13F의 27.1%, AUM의 약 18.6%**.

**bull 해석**: Brookfield는 전력·재생에너지·데이터센터·인프라 자산을 운용하는
대체투자사로, "AI 데이터센터 붐 → 전력·인프라 자본 수요"의 간접 플레이다. 금리가
정점을 지나면 실물자산 밸류에이션이 회복되고, Brookfield의 수수료 기반 이익은 계속
복리로 늘어난다. HHH는 Ackman이 직접 이사회를 통제하는 장기 컴파운더 프로젝트.

**bear 해석**: Brookfield를 −14% 축소했다는 것은 확신이 약해졌다는 신호일 수도 있다.
HHH는 수년째 "저평가"라는데 시장이 인정하지 않는 종목 — 밸류 트랩 위험. 부동산
개발은 금리·경기 민감도가 높다.

**이미 반영됐나**: Brookfield는 부분 반영. HHH는 시장이 계속 디스카운트 중(논쟁적).

**지켜볼 포인트**
- 26Q2 13F에서 Brookfield 축소가 이어지는지 vs 멈추는지.
- Brookfield의 데이터센터·전력 부문 AUM 성장과 수수료 수익.
- HHH의 NAV 갱신, Ackman의 추가 매수·자사주 발표.
- 장기금리(10년물) 방향 — 실물자산 밸류에이션의 직접 입력값.

### H3. "10~11종목·98% 집중을 유지한다 — 분산이 아니라 확신으로 리스크를 관리한다"

**근거**
- [11개 포지션, 상위 7종목이 약 98%](https://www.sec.gov/Archives/edgar/data/1336528/000117266126002336/0001172661-26-002336-index.htm).
  직전 분기도 11종목 — 종목 수가 늘지 않는다.
- 이번 분기 순매도(Hilton 청산, Brookfield·Uber·Meta·HHH 축소)로 총액이
  $15.53B→$13.71B로 줄었다. 신규는 Microsoft 하나.
- [2026년 상반기 펀드가 약 −11% 부진했다는 보도](https://www.hedgeweek.com/pershing-square-down-11-as-ackman-eyes-management-company-ipo/) —
  집중의 대가로 변동성을 감수하는 구조.

**규모**
- 단일 종목 최대 비중 17.6%(Brookfield). 상위 4종목(BN·AMZN·UBER·MSFT)이 **약 66%**.
- AUM 대비: 상위 4종목만으로 회사 자산의 **약 45%**.

**bull 해석**: Ackman의 알파 원천은 "소수 종목을 깊이 이해하고 필요하면 행동주의로
개입". 분산은 그 강점을 희석한다. 종목 수를 늘리지 않는 규율 자체가 스타일 일관성.

**bear 해석**: 상반기 −11%가 보여주듯, 집중은 한 종목이 틀리면 포트폴리오가 흔들린다.
헤지가 13F에 안 보이는 만큼, 매크로 충격에 대한 방어 장치를 외부에서 확인할 수 없다.

**이미 반영됐나**: 포지셔닝이지 종목 신호가 아니다.

**지켜볼 포인트**
- 26Q2·26Q3 13F에서 종목 수가 11개를 유지하는지.
- Pershing Square의 월간·분기 수익률(13F 밖 정보) 및 PSH 주가 대비 NAV 할인율.
- Ackman의 운용사(Pershing Square Inc) 상장 추진 — 성사 시 전략에 영향 가능.

---

## 3. Devil's Advocate — 이 포트폴리오를 그대로 따라가면 안 되는 이유

**따라갈 만한 근거**: 초집중·저회전이라 각 포지션의 논거가 명확하고, Ackman은 그
논거를 공개한다. Microsoft 신규·Alphabet 청산·Brookfield 우위라는 세 축이 선명하다.

**따라가면 안 되는 이유**:
1. **데이터가 최소 5개월 지났다.** 26Q1 기준이다. 저회전이라 큰 그림은 유효하겠지만,
   Microsoft 비중·Brookfield 방향은 26Q2에 이미 바뀌었을 수 있다. **26Q2 수집 시
   반드시 재검증.**
2. **13F는 매크로 헤지를 못 본다.** Pershing Square의 역사적 대박은 금리·크레딧 헤지
   에서 나왔다. 롱 바스켓만 보면 이 회사를 절반만 이해하는 것.
3. **집중의 대가.** 상반기 −11%. 같은 포지션을 따라 담으면 같은 변동성을 감수해야 한다.
4. **대형 우량주 위주.** Investment_Mandate의 "작은 시가총액 + 비선형 변곡점" 기준과는
   거리가 먼, 대형 컴파운더의 장기 보유다.

**판단**: 이 문서의 실용적 가치는 ① **빅테크 노출을 "검색·소셜 → 하이퍼스케일러
인프라"로 재편하는 흐름**(H1, Berkshire의 Alphabet 매수와는 정반대 방향이라 대조가
유용), ② **금리 정점 통과 시 실물자산·인프라 자본 수요**라는 매크로 뷰(H2)의 참고
사례다. 26Q2 13F가 수집되면 최우선으로 갱신한다.

---

## 4. 갱신 규칙

- **26Q2 13F(6/30 기준, 통상 8월 중순 제출)가 파이프라인에 수집되는 즉시** 1절 표와
  가설별 "지켜볼 포인트"를 전면 갱신하고, 이 문서 상단의 "기준 시점 주의" 경고를 해제한다.
- 이후 분기 13F(2·5·8·11월 중순)마다 갱신. 초집중 포트폴리오라 **종목 수·단일 최대
  비중·신규/청산**만 봐도 충분하다.
- 금액은 SEC 원문 정보표에서 재계산한다. vault 13F 마크다운의 legacy 값은 쓰지 않는다.
- 최초 작성 2026-08-28. 기준일 2026-03-31 (26Q1 — 잠정).
