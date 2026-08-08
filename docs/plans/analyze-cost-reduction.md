# analyze/collect 토큰 비용 절감 구현 계획

작성일: 2026-08-06 / 대상 브랜치: main

이 문서는 **구현 지시서**다. 각 항목은 독립 커밋으로 처리하며, 순서대로 진행한다.
P0는 나머지 항목의 전제조건이므로 반드시 먼저 끝낸다.

---

## 측정된 현황 (구현 전 기준선)

| 항목 | 값 |
|---|---|
| vault 문서 | 17,544개 / 666 MB |
| sqlite `documents` 행 | 16,866 (id가 PRIMARY KEY → id당 1행) |
| analyze 처리 완료 | 440건 |
| 현재 analyze 창(최근 7일 + 보유종목 180일) 내 미처리 | 파일 2,347개 / 36.4 MB, **고유 id 1,754개 / 18.9 MB** |
| 미처리 분량 구성 | central_bank 19.6MB · IB 6.8MB · SEC 5.3MB · telegram 4.2MB · naver 0.6MB |
| 동일 id 중복 파일 | 271개 id / 초과 파일 678개 / 20.4 MB (central_bank 498, ib_insights 180) |
| LLM 실사용(ledger 41콜) | 입력 545k / 출력 65k 토큰, $2.61 — **출력이 비용의 37%** |

가격(2026-08 기준): `claude-sonnet-5` $3/$15 per MTok(2026-08-31까지 인트로 $2/$10),
`claude-haiku-4-5` $1/$5. Batch API는 전 구간 50% 할인. 프롬프트 캐시는 읽기 0.1배·쓰기 1.25배,
최소 캐시 프리픽스는 sonnet-5 1,024토큰 / haiku-4.5 4,096토큰.

---

## P0. `documents.file_path` 표기 불일치 수정 (선행 필수)

### 문제

`reindex()`는 vault 기준 상대경로를 저장하고(`sqlite_index.py:276`,
`str(path.relative_to(vault_path))` → `10_Sources/...`),
`persist_collect_result()`는 `write_document()`가 돌려준 경로를 그대로 저장한다
(`collect.py:113-116`, `vault_path`가 `./vault`이므로 → `vault/10_Sources/...`).

소비하는 쪽 가정이 제각각이다:

| 위치 | 가정 | 상태 |
|---|---|---|
| `analyze.py:250` `read_document(Path(file_path))` | 프로세스 cwd 기준 | **깨짐** |
| `regime.py:248` `vault_path / row["file_path"]` | vault 기준 상대 | 정상 |
| `stock_score.py:388` `_resolve_document_path()` | 둘 다 시도 | 우회 중 |

`run_daily()`는 매 실행 첫 단계로 `reindex_vault()`를 호출하므로(`orchestrator.py:220`)
DB 전체가 vault 기준 상대경로로 덮이고, 그 뒤 collect가 새로 저장한 문서만 cwd 기준으로
열리는 경로를 갖는다. 결과적으로 **직전 수집분 외의 백로그는 analyze에서 100% FileNotFoundError**
로 떨어지고 `errors`에만 쌓인다. 실측: 16,866행 중 그대로 열리는 건 504행뿐.

### 수정

1. `investor_intel/storage/obsidian_repo.py`에 공용 헬퍼를 추가한다.
   `stock_score.py:388`의 `_resolve_document_path`를 그대로 옮겨오고(주석 포함),
   `stock_score.py`는 새 위치를 import하도록 바꾼다.

   ```python
   def resolve_document_path(vault_path: Path, raw_file_path: str) -> Path | None: ...
   ```

2. **저장 표기를 vault 기준 상대경로로 통일한다.** `persist_collect_result()`에서
   `file_path=str(file_path.relative_to(vault_path))`로 저장. `analyze.py:188`의
   `_finalize()`도 동일하게 상대경로로 저장한다(현재 `str(path)` 절대/혼합).

3. `analyze.py:250`을 `resolve_document_path(vault_path, file_path)`로 바꾸고,
   `None`이면 기존처럼 `errors`에 남기되 메시지에 "vault에서 찾을 수 없음"을 명시한다.
   `analyze_pending_documents`는 이미 `vault_path`를 인자로 받으므로 시그니처 변경 없음.

4. `regime.py:248`도 같은 헬퍼로 교체(동작은 동일하되 절대경로 레거시 행도 처리).

### 테스트

- `tests/test_pipeline_analyze.py`: DB에 vault 기준 **상대경로**로 저장된 미처리 문서 1건을
  넣고 `analyze_pending_documents`가 그것을 실제로 처리하는지(=`processed == 1`, `errors == []`)
  검증하는 케이스 추가. 현재 코드에서 반드시 실패해야 한다(회귀 방지 앵커).
- 절대경로 레거시 행도 처리되는지 케이스 추가.
- `tests/test_sqlite_index.py`: `reindex` 후 `persist_collect_result` 저장 표기가 동일함을 검증.

### 주의

이 수정으로 그동안 막혀 있던 **1,754건 / 18.9MB 백로그가 한꺼번에 LLM으로 흘러간다.**
sonnet-5 단독 처리 시 입력만 ~$16, 하루 예산 $1.5(`settings.py`)를 12일 넘게 소진한다.
P1·P2를 같은 릴리스에 함께 넣어 실제 실행 전 비용을 낮춘다. 배포 전에는 반드시
`--dry-run` 성격의 확인(예: `analyze` 대상 건수/바이트만 출력)을 한 번 거친다.

---

## P1. analyze를 Message Batches API로 전환 (전 구간 50% 할인)

### 근거

analyze는 야간 크론에서 vault에 기록만 하므로 지연 민감도가 0이다. Batches API는
모든 토큰이 반값이고, 기존 기능(tools, tool_choice, 캐싱)을 그대로 지원한다.
대부분 1시간 내, 최대 24시간에 완료된다.

### 구현

1. `investor_intel/llm/client.py`에 배치 메서드를 추가한다. 기존
   `AnthropicClient.create_message`와 같은 레벨:

   ```python
   def create_batch(self, requests: list[dict]) -> str: ...        # → batch_id
   def retrieve_batch(self, batch_id: str) -> Any: ...             # processing_status 확인
   def batch_results(self, batch_id: str) -> Iterator[Any]: ...    # custom_id별 결과
   ```

   내부적으로 `self._client.messages.batches.create/retrieve/results`를 호출한다.
   `_AnthropicClientProtocol`에 `messages.batches`를 추가하되, 기존 테스트의 가짜 클라이언트가
   깨지지 않도록 **Protocol은 선택적으로** 두고 배치 경로에서만 접근한다.

2. `investor_intel/pipeline/analyze.py`에 배치 실행 경로를 추가한다.
   기존 동기 경로는 남기고, `use_batch_api: bool = False` 파라미터(기본 False)로 분기한다.

   - 지금의 `pending_small` 누적 로직(`_flush_pending_small`)은 그대로 두고,
     각 배치를 즉시 호출하는 대신 `Request(custom_id=..., params=...)`로 모아둔다.
   - `custom_id`는 배치 하나당 하나(`batch-{n}`)로 하고, 로컬에 `custom_id → [(doc, body), ...]`
     매핑을 유지한다. 대형 문서 개별 호출도 같은 방식으로 `custom_id="doc-{document_id}"`.
   - 전부 모은 뒤 `create_batch` 1회 → `retrieve_batch` 폴링(간격 60초, 상한 예: 30분,
     상한 초과 시 batch_id를 반환하고 종료 — 다음 실행에서 이어받을 수 있게) →
     `batch_results`로 수집 → 기존 `_finalize` 재사용.
   - 결과는 **순서 보장이 없다.** 반드시 `custom_id`로 매칭한다(위치 인덱싱 금지).
   - `result.result.type`이 `succeeded`가 아니면 해당 배치의 문서들은
     기존 개별 폴백 경로(`_process_single`)로 넘긴다.
   - 비용 기록: `record_usage`를 **50% 가격**으로 반영해야 하므로,
     `cost_tracker`에 `record_usage(..., discount: float = 1.0)`을 추가하거나
     `compute_cost_usd`에 배치 여부 인자를 넣는다. 어느 쪽이든 `llm_usage` 테이블에
     실제 청구액이 남아야 한다.

3. `run_daily`(`orchestrator.py:250`)와 CLI `analyze` 커맨드에서 배치 사용 여부를
   설정으로 노출한다: `AppSettings.analyze_use_batch_api: bool = True`.
   대화형으로 즉시 결과가 필요한 경우를 위해 CLI 플래그로 끌 수 있게 한다.

4. 배치가 진행 중일 때 `run_daily`의 후속 단계(포트폴리오 모니터 등)는 `claims_digest`가
   비어 있는 상태로 진행된다. 이는 기존에도 예산 소진 시 발생하던 동작과 같으므로
   허용하되, 리포트에 "이번 실행의 주장 추출은 배치 처리 중"을 표기한다.

### 테스트

- `tests/test_pipeline_analyze.py`: 가짜 배치 클라이언트로 (a) 정상 경로,
  (b) 결과가 뒤섞여 도착해도 `custom_id`로 올바르게 매칭되는지,
  (c) `errored` 결과가 개별 폴백으로 넘어가는지 검증.
- `tests/test_cost_tracker.py`: 배치 사용량이 정가의 50%로 기록되는지.

---

## P2. 대형 문서 라우팅 임계값 50,000 → 15,000

### 근거

`AppSettings.large_doc_char_threshold = 50_000`(`config/settings.py:15`)인데 실제 미처리
문서 평균 크기는 central_bank 29KB, ib_insights 29KB다. 즉 분량 대부분이 sonnet-5(3배 가격)로
간다. 고유 18.9MB 기준 입력비 추정(문자당 1/3.4 토큰 가정):

| 임계값 | sonnet | haiku | 입력비 |
|---|---|---|---|
| 50,000 (현재) | 10.8MB | 8.1MB | ~$11.9 |
| 20,000 | 6.0MB | 13.0MB | ~$9.1 |
| **15,000** | 5.0MB | 13.9MB | **~$8.5** |

주장 추출은 정해진 툴 스키마를 채우는 작업이라 haiku 품질 저하가 작다.

### 구현

1. `config/settings.py`: `large_doc_char_threshold: int = 15_000`.
2. 기본값 변경만으로 끝내지 말고, **이 값이 실제로 파이프라인까지 전달되는지 확인한다.**
   현재 `orchestrator.run_daily`는 `analyze_pending_documents`에 `large_doc_client`를
   **넘기지 않는다**(`orchestrator.py:250-253`) — 즉 `anthropic_large_doc_model` 설정이
   run_daily 경로에서 사실상 死코드다. `settings.anthropic_large_doc_model`로
   `AnthropicClient`를 하나 더 만들어 `large_doc_client=`와
   `large_doc_char_threshold=settings.large_doc_char_threshold`를 전달하도록 고친다.
   (**이것이 P2의 본체다. 임계값 숫자보다 이 배선 누락이 더 크다.**)
3. `docs/` 또는 `vault/00_System/Runbook.md`에 라우팅 규칙 한 줄 기록.

### 테스트

- `tests/test_pipeline_analyze.py`: 임계값 초과 문서가 `large_doc_client`로,
  이하 문서가 기본 client로 가는지 검증(기존 케이스가 있으면 임계값만 조정).
- `tests/test_run_daily.py`(또는 해당 오케스트레이터 테스트): `run_daily`가
  `large_doc_client`를 실제로 전달하는지 검증 — 현재 코드에서 실패해야 한다.

---

## P3. 동일 문서의 중복 파일 생성 차단

### 문제

`path_for_document()`(`obsidian_repo.py:58-64`)는 파일명을 `published_at` 날짜로 만든다.
`central_bank.py:216`은 `published_at=now`(회의록이 늦게 공개돼 recency 창에 걸리게 하려는
의도적 설계), ib_insights는 크롤 날짜를 쓴다. 따라서 **수집 실행마다 경로가 달라진다.**

`persist_collect_result`는 `find_duplicate()`로 기존 id를 찾아 재사용하지만
(`collect.py:99-111`), 곧바로 `write_document(vault_path, doc, body)`를 호출해 **새 날짜 경로에
파일을 또 쓴다.** `write_document`의 중복 방지(`obsidian_repo.py:92-95`)는 *같은 경로*가
이미 있을 때만 동작하므로 무력하다.

실측 결과: 동일 id 271개, 초과 파일 678개, 20.4MB. BOJ 의사록 하나가 4벌
(`2026-08-01/03/04/05-c44fa1365d410fca.md`, content_hash 동일).

LLM 비용에 직접 미치는 영향은 현재 크지 않다(DB가 id당 1행이라 analyze는 1번만 처리).
문제는 두 가지다:
- git `data` 브랜치와 디스크에 매일 누적되는 20MB+ 부담 (여러 머신 동기화 시 충돌 소지)
- `list_documents()`가 정렬 순회(`obsidian_repo.py:109`)라 reindex 시 **가장 최근 날짜 파일이
  DB 행을 차지한다.** 이미 처리한 문서를 다음 날 재수집하면 `llm_processed=false`인
  새 사본이 DB를 덮어써 **재분석 비용이 재발한다.** 현재 혼재 그룹이 20개(0.36MB)뿐인 이유는
  central_bank/IB가 P0 버그로 아직 한 번도 분석되지 않았기 때문이며, P0를 고치는 순간
  이 재발 경로가 열린다.

### 구현

1. `obsidian_repo.py`에 경로를 명시 지정하는 변형을 추가한다:
   ```python
   def write_document_at(path: Path, doc: SourceDocument, body: str) -> Path: ...
   ```
   기존 `write_document`는 `write_document_at(path_for_document(...), ...)`로 리팩터.

2. `persist_collect_result`(`collect.py:95-121`)를 다음 순서로 바꾼다:

   ```
   existing_id = find_duplicate(...)
   if existing_id is not None:
       doc = doc.model_copy(update={"id": existing_id})
       row = get_document_by_id(conn, existing_id)
       existing_path = resolve_document_path(vault_path, row["file_path"]) if row else None
       if existing_path is not None:
           if row["content_hash"] == doc.content_hash:
               continue          # 내용 동일 → 파일/DB 모두 건드리지 않고 스킵
           file_path = write_document_at(existing_path, doc, body)   # 내용 변경 → 제자리 갱신
       else:
           file_path = write_document(vault_path, doc, body)
   else:
       file_path = write_document(vault_path, doc, body)
   ```

   - 내용 동일 스킵 시 `count`는 증가시키지 않는다. `PersistResult`에 `skipped: int = 0`을
     추가해 관측 가능하게 한다(로그/리포트에 노출).
   - 내용이 바뀐 경우 `llm_processed`가 false로 리셋되는 것은 **의도된 동작**이다
     (내용이 달라졌으니 재분석 대상).

3. **기존 중복 정리 스크립트**를 `scripts/dedupe_vault.py`로 추가한다.
   - 같은 `id`를 가진 파일 그룹에서 **`llm_processed: true`인 사본을 우선 보존**,
     없으면 가장 오래된 `published_at` 사본을 보존, 나머지 삭제.
   - **기본 동작은 dry-run.** 삭제하려면 `--apply`를 명시해야 한다.
   - 실행 후 `reindex`가 필요하다는 안내를 출력한다.
   - 이 스크립트는 **에이전트가 실행하지 않는다.** 사용자가 직접 확인 후 돌린다.

4. (선택, 별도 판단 필요) `central_bank.py:216`의 `published_at=now`는
   analyze recency 창을 위한 의도적 설계이므로 **건드리지 않는다.**
   경로가 published_at에 묶인 구조 자체를 바꾸는 건 이 계획의 범위 밖이다.

### 테스트

- `tests/test_pipeline_collect.py`(없으면 신설): 같은 문서를 서로 다른 `published_at`으로
  두 번 수집해도 (a) 파일이 1개만 생기고, (b) 두 번째는 `skipped`로 집계되는지 검증.
- 내용이 바뀐 재수집은 기존 경로를 덮어쓰고 `llm_processed`가 false로 리셋되는지 검증.

---

## 범위 밖 (이번에 하지 않음)

- 프롬프트 캐싱: `config/prompts/extract_claims.md`가 588바이트라 툴 스키마를 합쳐도
  ~600–700토큰 → sonnet-5 최소 캐시 프리픽스 1,024토큰 미달로 **캐시가 걸리지 않는다.**
  캐싱이 실제로 유효한 대상은 `Investment_Mandate.md`(22.6KB, ~7k토큰)이지만,
  `_with_mandate`(`orchestrator.py:79-80`)가 mandate를 프롬프트 *뒤*에 붙여 공유 프리픽스가
  생기지 않는다. 별도 항목으로 분리.
- 출력 토큰 축소(추출 스키마에 claims 개수/근거 길이 상한): 별도 항목.
- collect 단계 web_search를 haiku로 내리고 `max_uses` 5→3: 별도 항목.
- `cost_tracker`가 web_search 서버툴 호출료($10/1000회)와 캐시 토큰을 계상하지 않는 문제: 별도 항목.
- 공백 정규화: 실측 절감 0.9%로 무의미. 하지 않는다.

---

## 작업 규칙

- **`investor_intel/collectors/telegram*.py`와 `tests/test_telegram*.py`는 건드리지 않는다**
  (작업 중인 미커밋 변경이 있음).
- 각 항목은 별도 커밋. 커밋 전 `uv run pytest`가 전부 통과해야 한다.
- 새 동작에는 반드시 테스트를 먼저 추가해 **현재 코드에서 실패하는 것을 확인한 뒤** 고친다.
- 실제 Anthropic API를 호출하지 않는다. 모든 테스트는 가짜 클라이언트를 쓴다.
- vault 파일을 삭제하지 않는다. 정리는 dry-run 스크립트 제공까지만.
