# 색인 유지 계층 (증분 색인 · 임베딩 캐시 · 건강 지표 · 재수집)

> 2026-08-25. `docs/ingest_layer.md`가 "원문 품질을 수집 시점에 확정한다"를 다뤘다면, 이
> 문서는 "그 원문이 실제로 검색 가능한 상태로 유지되게 한다"를 다룬다.

## 문제: 수집은 증분인데 색인은 전량이었다

`Bm25Index.build()`는 `DELETE FROM chunk_meta`로 시작했다. 문서 한 건이 늘어도 4,818건을
전부 다시 청킹·토크나이징·색인한다. 그리고 그 호출은 `scripts/`에서만 일어났다 —
`cli.py`와 `pipeline/`에서 `indexing`·`knowledge`를 참조하는 코드가 **0건**이었다.

결과는 예측 가능하다. 색인은 "가끔 손으로 돌리는 것"이 되고, 한 달 가까이 밀린 채 아무도
몰랐다. 그 사실을 관측할 지표조차 없었다.

## 1. 증분 색인 (`indexing/state.py`)

`index_state(doc_id, fingerprint, chunk_count, indexed_at, embedded_at, embed_model)`에
무엇이 색인됐는지 기록하고, 다음 실행에서 비교해 바뀐 것만 갈아끼운다.

### 지문을 무엇으로 잡는가

**concept 파일 원문 전체의 해시**다. 처음에는 원본 문서의 `content_hash`를 쓰려 했는데
그것으로는 부족하다. 색인되는 것은 본문만이 아니라 `description`(청크 문맥)과
`entities`(필터 컬럼)까지이고, `enrich-vault`로 종목 관계가 붙으면 본문 해시는 그대로인데
색인 내용은 달라진다. 그 경우를 놓치면 필터가 조용히 옛 값으로 남는다.

파일은 어차피 읽어야 하므로 파일 전체를 해시하는 추가 비용은 없다.

### 코드가 바뀌면

청킹 규칙이나 토크나이저가 바뀌면 파일 해시는 그대로인데 색인 결과는 달라져야 한다. 그래서
인덱스 단위로 `signature`(변형 이름 + `BUILDER_VERSION`)를 저장하고, 달라지면 증분이 아니라
**전량 재구축으로 떨어진다.** 청킹 규칙을 바꿨는데 옛 색인을 조용히 유지하는 것보다 안전하다.
규칙을 바꿀 때는 `state.BUILDER_VERSION`을 올린다.

### 실측 (concept 5,997건 / 청크 41,961개)

| 작업 | 소요 | 다시 색인한 청크 |
|---|---|---|
| 전량 재구축 (`index build`) | 9.2s | 41,961 |
| 증분, 변화 없음 (`index update`) | 3.2s | 0 |
| 증분, 1건 수정 + 1건 추가 + 1건 삭제 | 3.4s | 3 |

증분의 3.2초는 대부분 **번들 6,009개 파일을 읽어 해시하는 시간**이다. 색인 자체는 거의
0에 가깝다. mtime으로 더 줄일 수도 있지만 git 체크아웃에서 mtime이 전부 갱신되므로
신뢰할 수 없다 - 3초는 그 대가로 받아들일 만하다.

`test_incremental_result_matches_a_full_rebuild`가 증분 결과와 전량 재구축 결과가
`chunk_meta` 전체에서 동일함을 확인한다. 다르면 증분을 신뢰할 이유가 없다.

## 2. 청크 저장소 하나로 통일 (정합성 문제)

예전에는 BM25(`okf_pipeline`)와 벡터(`vector_pipeline`)가 **각각 번들을 파싱해 각각 청킹**했다.
같은 `IndexConfig`를 넘기고 있었으니 지금까지는 결과가 같았지만, 그건 우연이다. 설정이
어긋난 순간 `chunk_uid`가 달라지고, 그러면 RRF로 두 결과를 합칠 때 같은 조각이 서로 다른
것으로 취급된다.

`chunk_meta`에 두 컬럼을 더해 BM25 인덱스를 **정본 청크 저장소**로 만들었다.

- `ctx_text` — 청크에 붙인 문맥(concept의 `description`)의 토큰화 전 원문.
  `chunk_fts.ctx`는 토큰화된 형태라 되읽을 수 없다.
- `native_doc_id` — 원본 vault 문서의 id. 카탈로그와 조인해 "수집은 됐는데 색인 안 된
  문서가 몇 건인가"를 정확히 세는 데 쓴다.

벡터 인덱스는 이제 `build_vector_index_from_chunk_store()`로 그 청크를 그대로 쓴다.
번들 기반 경로(`build_vector_index`)는 평가용으로 남겨 두었다.

## 3. 임베딩 캐시 (`indexing/embed_cache.py`)

임베딩은 이 파이프라인에서 가장 비싼 단계다(로컬 모델이면 시간, API면 돈). 조각 본문이 같으면
벡터도 같으므로 다시 계산할 이유가 없다.

키는 `(임베딩할 문장의 해시, 모델 이름)`이다. `chunk_uid`가 아닌 이유는 청크 경계가 밀리는
경우 — 본문이 조금 길어지면 뒤쪽 청크가 전부 다른 uid를 받는다 — 에도 **내용이 같은 조각은
그대로 재사용**되어야 하기 때문이다. 문서 하나에 한 문장을 덧붙였을 때 그 문서의 모든 청크를
다시 인코딩하지 않는다.

`CachedEncoder`가 `Encoder` 프로토콜을 그대로 만족하므로 `VectorIndex.build()`는 변경이 없다.
행렬(.npy)은 행 번호로 접근하므로 부분 갱신이 까다로운데, **인코딩을 캐시하고 행렬 조립만
매번 다시 한다** — 조립은 인코딩 비용의 수천분의 1이다.

실측(조각 27,555개, HashEncoder 기준): 첫 실행 10.7s / 재실행 1.5s, 적중률 1.0. 실제
multilingual-e5 모델이면 인코딩이 전체 시간을 지배하므로 차이는 훨씬 커진다.

```bash
uv run python scripts/build_vector_index.py \
    --from-chunk-store data/search_index.sqlite3 \
    --cache data/embedding_cache.sqlite3
```

모델 이름을 키에 넣는 것은 모델을 바꾸면 벡터 공간 자체가 달라져 섞어 쓸 수 없기 때문이다.
같은 모델 이름으로 차원이 다른 벡터가 들어오면 캐시 미스로 취급한다 — 재사용하면 행렬 곱에서
조용히 깨진다.

## 4. 건강 지표와 게이트 (`indexing/health.py`)

`index status`가 세 질문에 답한다.

```
수집 문서 4,788건
  소스                        문서       본문미확보       인코딩손상      절단
  dart                   1,362       1,059         211     288
  ib_insights              324         173           0       0
  sec_filing               396         355           0      41
  ...
  합계                     4,788       1,587         211     329

검색 인덱스: 문서 5,997 / 청크 41,961 / 구성 V7/2026-08-25.1
  마지막 색인 2026-08-25T08:37:28+00:00
  마지막 수집 2026-07-30T03:47:19+00:00
  색인 안 된 문서 0건
  옛 형식 13F 스냅샷 198건 (금액·비중 신뢰 불가, 재수집 필요)
```

임계값을 주면 CI 게이트가 된다. 기본은 전부 꺼져 있어(`-1`) 조회용으로 쓸 수 있다.

```bash
uv run python -m investor_intel index status --max-corrupt 0 --max-not-indexed 0
```

**게이트가 정직하려면 `reindex`가 본문에서 품질을 직접 재야 한다.** frontmatter의
`readable_ratio`를 그대로 믿으면 `enrich-vault`를 돌리지 않은 vault에서 기본값 1.0만
들어 있어 "깨진 문서 0건"이라고 보고하고 게이트가 조용히 무력해진다. 그래서 `reindex`는
읽은 본문으로 다시 잰다.

CI의 `data-quality` 잡이 `data` 브랜치를 읽어 이 게이트를 돌린다. `continue-on-error: true`로
둔 것은 데이터 상태가 코드 변경과 무관하게 바뀌기 때문이다 — 눈에 보이게 하되 무관한 PR을
막지는 않는다.

## 5. 재수집 (`pipeline/refetch.py`)

수집기는 증분 체크포인트로 앞으로만 간다. 과거에 불완전하게 저장된 문서는 **collect를 다시
돌려도 손대지 않는다.** 이유 문구가 "not parsed in **this phase**"인 것에서 보이듯 대부분
본문 수집 기능이 붙기 전에 모은 문서다. 기능은 이미 있는데 되돌아갈 길이 없었다.

두 가지 전략을 쓴다.

| 전략 | 대상 | 방식 |
|---|---|---|
| 제자리 재수집 | DART | 접수번호로 원문을 다시 받아 그 파일에서 본문만 갈아끼운다 |
| 체크포인트 되감기 | 그 외 | 수집기 체크포인트를 지워 다음 `collect --backfill-days`가 과거를 다시 훑게 한다 |

**수집 로직을 복제하지 않는다.** SEC 공시는 원문 위치를 알아내려면 수집기의 필링 조회 로직
전체가 필요한데, 그걸 재수집 경로에 복제하면 둘 중 하나만 고쳐진 버그가 생긴다. 되감기는
이미 완전한 문서를 `persist_collect_result`의 content_hash 비교에서 건너뛰므로, 비용은
네트워크 요청뿐이다.

제자리 재수집은 **파일 경로와 문서 id를 그대로 둔다.** `write_document`가 파일명을
`published_at`으로 만들기 때문에 경로가 바뀌면 같은 문서의 사본이 하나 더 생긴다. 본문이
바뀌었으므로 `llm_processed`는 false로 되돌린다 — 기존 분석 결과는 낡았다.

```bash
uv run python -m investor_intel refetch --reason corrupt              # 무엇이 대상인지 (dry-run)
uv run python -m investor_intel refetch --reason corrupt --apply      # DART_API_KEY 필요
uv run python -m investor_intel refetch --reason stub --source-type sec_filing --apply
```

## 6. `run-daily` 연결

`collect` 직후 `update_search_index()`가 증분 갱신을 돌린다. 번들이 없으면(검색 계층을 안 쓰는
설정) 조용히 건너뛴다 — 수집 자체를 실패시킬 이유는 없다. 결과 한 줄이
`RunDailyResult.index_summary`로 올라와 리포트 로그에 남는다.

번들 생성 자체는 여기서 하지 않는다(vault 전체를 훑는 별도 단계다). 번들이 낡으면 그 사실이
`index status`의 "색인 안 된 문서" 수로 드러난다.

## 남은 것

- 번들 생성도 증분화 (지금은 `build_bundle`이 vault 전체를 훑어 번들을 통째로 다시 만든다)
- 실제 multilingual-e5 모델로 Hybrid Search 평가 — 캐시가 붙었으므로 이제 반복 실험이 싸다
- 평가셋 확대(사용자 질문 24건 → 100건 이상). 검색 품질의 상한을 재는 자가 여전히 24건이다
