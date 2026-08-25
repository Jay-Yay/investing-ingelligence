# 수집 시점 처리 계층 (`investor_intel/ingest/`)

> 2026-08-25. RAG 검색 계층을 붙여 놓고 보니, 검색 품질을 막고 있던 것은 색인이 아니라
> **원문 자체의 품질**이었다. 이 문서는 무엇이 왜 수집 시점으로 옮겨졌는지를 남긴다.

## 문제: 같은 판단이 하류에서 중복 재계산됐다

수집기는 원문을 마크다운으로 떨어뜨리는 것까지만 했고, 품질 판정·종목 관계 복원·보일러플레이트
제거를 전부 하류가 다시 했다.

| 판단 | 예전에 하던 곳 | 문제 |
|---|---|---|
| 본문을 믿을 수 있나 | `knowledge/builder.py` (번들 빌드 시 U+FFFD 비율 계산) | vault 원문에는 표시가 없어 소비자마다 다시 계산 |
| 어느 종목 얘기인가 | 같은 파일 (`CompanyRegistry.find_mentions`) | 수집기는 `companies: []`로 저장 → `document_assets` 0행 |
| 분석 주체 vs 분석 대상 | 같은 파일 (`ANALYST_HOUSE` 정규식) | frontmatter에 구분이 없음 |

번들을 만들지 않는 소비자 — `analyze` 단계, vault 마크다운을 직접 읽어 브리핑을 쓰는 경로 —
는 이 판단 결과를 볼 수 없었다. **깨진 문서를 근거로 인용할 수 있는 구조였다.**

## 설계 원칙: 측정값은 수집 시점, 판정은 소비 시점

frontmatter에 넣는 것은 **측정값**뿐이다.

```yaml
readable_ratio: 0.491     # 본문 중 읽을 수 있는 문자의 비율 (관측값)
truncated: true           # 40,000자 상한에 걸려 잘렸는지
original_chars: 132450    # 잘리기 전 원문 길이
entities:
  subject: kyobofnbcosmetic
  mentions: [kr-278470]
  analyst_house: [kr-030610]
  lexicon_version: dart-corp-codes:118535
```

"이 문서는 corrupt다"라는 **임계값 판정은 넣지 않는다.** 임계값(`CORRUPT_RATIO_THRESHOLD = 0.05`)은
바뀔 수 있고, 바뀔 때마다 4,818건을 재수집해야 한다면 그 필드는 유지될 수 없다. 판정이 필요한
소비자는 `ingest.quality.is_corrupt(doc.readable_ratio)`를 부른다 — 임계값이 한 곳에만 있다.

`lexicon_version`도 같은 이유로 있다. 종목 매칭은 사전(상장법인 명부)에 의존하므로, 사전이
바뀌면 결과도 바뀐다. 어떤 사전으로 뽑은 값인지 없으면 나중에 결과 차이를 설명할 수 없다.

## 함께 고친 수집 단계 버그

검색 계층을 얹기 전에는 드러나지 않던 것들이다. 셋 다 **인덱스는 틀린 원문을 정확하게
색인하고 있었다**는 같은 성질의 문제다.

### 1. DART 원문 인코딩 (corrupt 211건)

`dart_document_fetch.py`가 EUC-KR/CP949 XML을 `decode("utf-8", errors="replace")`로 읽어
한글 한 글자마다 U+FFFD 두 개를 박았다. 실측: 에이피알 2022-05-16 분기보고서는 본문의
50.9%가 치환문자였고, `�б⺸����`이 "분기보고서"였다.

고친 방식은 인코딩 **추정**이 아니라 후보를 `errors="strict"`로 시도하는 것이다. 순서는
XML 선언이 밝힌 인코딩 → UTF-8 → CP949 → UTF-16. UTF-8을 CP949보다 먼저 두는 이유는
CP949가 UTF-8 한글 바이트열도 (뜻이 깨진 채로) 성공적으로 디코딩하기 때문이다.

부수적으로 DART 자체 엔티티 `&cr;`이 `html.unescape` 대상이 아니어서 본문에 그대로 남아
있던 것도 처리했다.

### 2. 13F 정보표 집계 (표가 "잘린" 것처럼 보였던 이유)

`compute_holding_changes`가 `{h.cusip: h for h in holdings}`로 행을 묶어 **마지막 행만
남기고 나머지를 조용히 덮어썼다.** 13F는 같은 종목을 운용 재량 구분·공동 운용사·put/call별로
여러 행으로 나눠 보고하는 것이 정상이다.

실측(`2024-11-14-789b7e02cb9abcf1.md`):

| 항목 | 값 |
|---|---|
| frontmatter `companies` 항목 수 | 121 |
| 그중 distinct 종목 | 37 (BANK AMER 13행, LIBERTY MEDIA 13행, APPLE 12행 …) |
| 본문 표 행 수 | 44 |
| **표 비중 합계** | **21.42%** (같은 문서 머리글의 상위 5종목 집중도는 46.49%) |

한 종목의 여러 행 중 하나만 남으므로 "최대 비중 종목", "상위 5종목 쏠림" 답이 한 매니저
슬라이스만 본 값이 됐다. 이제 `(CUSIP, put_call)` 기준으로 합산하고, 합산된 행 수를
표에 `원문행수` 열로 함께 적어 원문과 대조할 수 있게 한다. put/call을 키에 포함시킨 것은
13F 유의사항이 "put/call 포지션은 보통주 보유와 혼합해서 해석하지 않는다"고 명시한 그대로다.

### 3. 13F 금액 단위 (2023-01-03 SEC 서식 개정)

SEC는 2023-01-03 이후 제출되는 Form 13F의 `<value>`를 **천 달러가 아닌 원 달러**로 받는다.
코드는 무조건 천 달러로 읽었다 → 같은 문서 머리글이 `총 보고 가치: 266,378,900,503천 달러`
(266조 달러)였다. 2014년 필링은 맞고 최근 필링은 1,000배 틀리므로, **연도가 섞인 시계열·랭킹
질의가 조용히 오답을 냈다.**

`parse_information_table_xml(xml, filing_date)`가 제출일로 단위를 정해 달러로 정규화한다.
모델 필드도 `value_usd_thousands` → `value_usd`로 바꿨다 — 이름이 단위를 잘못 말하고 있으면
같은 버그가 반복된다.

## 이미 수집된 문서는 어떻게 하나

`readable_ratio`·`truncated`·`entities`는 **본문만 있으면 다시 계산할 수 있다.** 재수집이
필요 없다.

```bash
uv run python -m investor_intel enrich-vault --vault-path <vault> --apply
```

본문과 `content_hash`는 건드리지 않는다(바꾸면 중복 판정이 모든 문서를 새 문서로 본다).
검증: 이 명령을 적용해도 BM25 인덱스 통계가 문서 4,788 / 청크 47,121 / 24,083,731자로
**완전히 동일**하다 — frontmatter만 바뀐다는 뜻이다.

반면 **재수집이 필요한 것**은 따로다. `enrich-vault`가 그 건수를 부산물로 보고한다.

| 항목 | 건수 | 필요한 조치 |
|---|---|---|
| 인코딩 깨짐 | 211 | DART 재수집 (디코딩 수정이 선행돼야 한다) |
| 본문 절단 | 329 | 상한 재검토 후 재수집 |
| 13F 금액·집계 오류 | 198 (전량) | SEC 재수집. 그전까지 `legacy_units` 플래그로 경고 |

13F 스냅샷은 재수집 전까지 값을 보정할 방법이 없다. 그래서 `snapshots.legacy_units`로
표시하고, `HoldingsTool`이 답을 내면서 "이 값은 신뢰할 수 없다"를 함께 반환한다. 근거가
부실하면 한계를 함께 알린다는 원칙의 적용이다.

## 부수적으로 고친 것

- **`document_assets` 0행.** `doc.assets`만 넣고 있었는데 그 필드를 채우는 수집기가 하나도
  없었다. 실제 관계는 `companies`와 본문에 있었다. 이제 셋 다 넣고, 분석 주체는
  `asset_type='analyst_house'`로 구분해 넣는다. `entities`가 없는 옛 문서도 `companies`
  폴백으로 재색인만 하면 티커 조회가 살아난다.
- **`find_mentions`의 재현성.** 후보를 `set`으로 순회해서 파이썬 문자열 해시 랜덤화
  (`PYTHONHASHSEED`)에 따라 실행마다 다른 종목이 살아남았다. 수집 시점에 확정해 frontmatter에
  적는 값이 실행마다 달라지면 안 되므로, 본문에 먼저 나온 순서로 고정했다.
- **수집기가 밝힌 종목이 있어도 본문 매칭을 생략하지 않는다.** IB 리서치 107건은 수집기가
  리포트의 주 종목 하나만 밝히지만 본문에는 여러 종목이 나온다. 확정된 종목을 앞에 두고
  본문 매칭 결과를 뒤에 붙인다(`merge_mentions`).
- **`scripts/build_knowledge_bundle.py`의 통계 키 오타.** `duplicate_doc_ids_skipped`를
  읽는데 `build_bundle`은 `duplicate_ids_skipped`를 돌려줘서 이 스크립트는 **항상**
  KeyError로 죽었다(번들 자체는 이미 다 만든 뒤였다).

## 검증 결과

원본 vault 사본에 적용하고 지식 번들을 다시 만든 결과:

```
concept 5,996건 · 링크 14,655 · 깨진 링크 0 · 필수 필드 위반 0
종목 관계: frontmatter에서 1,909건 (본문 재매칭 1건) · 분석 주체로 분리 709건
인코딩 손상 211건 · 재제출로 대체 14건
```

번들이 이제 frontmatter의 확정 값을 소비한다(1,909건 중 1건만 본문 재매칭). 같은 판정이
두 곳에서 따로 일어나지 않는다는 뜻이다.

## 남은 작업

`docs/rag_readiness_review.md`의 우선순위 중 이 변경으로 처리된 것은 1~3번이다. 남은 것:

4. `index_state` 테이블 + 증분 upsert (`Bm25Index.build()`가 지금은 전량 재구축뿐)
5. stub 역방향 refetch (`capture_mode != full` 1,534건 — SEC 355/396, DART 1,059/1,362)
6. 청크·임베딩 캐시 물질화
7. `index build|update|status` CLI + `run-daily` 연결 + CI 게이트
