# 소스 Inbox 자동 등록 기능 — 설계 문서

- 작성일: 2026-07-25
- 상태: 브레인스토밍 승인 완료

## 1. 배경 및 목적

현재 새 수집 소스(네이버 블로그, 텔레그램 채널, SEC 상장사, DART 상장사, 13F 추적
투자자)를 추가하려면 각각 `config/sources.yaml`, `config/companies.yaml`,
`config/dart_companies.yaml`, `config/investors.yaml` 4개 파일에 직접 YAML 필드를
채워 넣어야 한다. id, CIK, 회사명 등 보일러플레이트가 많아 사용자가 "링크/문자열
값만 붙여넣으면 코드가 알아서 처리"하는 방식을 원함.

이 기능은 vault 안의 단일 마크다운 파일을 소스 등록 inbox로 쓰고, 신규 CLI 명령이
그 파일을 읽어 필요한 메타데이터(CIK, 회사명 등)를 가능한 한 자동 조회해 기존
config YAML들에 반영한다.

## 2. 스코프 판단

독립 서브시스템을 추가로 쪼갤 필요 없는 단일 기능. 기존 프로젝트의 config
로더/모델/DART 캐시/HTTP 클라이언트를 그대로 재사용하는 조립형 기능이라 단일
plan으로 구현 가능.

## 3. Inbox 파일

- 경로: `vault/00_System/inbox_sources.md`
- 형식: 마크다운 체크리스트, 한 줄 = 소스 하나

```
- [ ] naver: https://m.blog.naver.com/xxx
- [ ] telegram: https://t.me/s/xxx
- [ ] telegram_private: https://t.me/xxx
- [ ] sec: NBIS
- [ ] dart: 005930
- [ ] investor: 0002045724 | https://situational-awareness.ai/
```

규칙:
- `#`으로 시작하는 줄, 빈 줄은 무시
- 체크박스가 `- [x]`인 줄은 이미 처리된 것으로 간주하고 건너뜀
- `investor` 타입만 `|` 뒤에 선택적으로 `related_essay_url`을 붙일 수 있음
- 지원 타입: `naver`, `telegram`, `telegram_private`, `sec`, `dart`, `investor` 6종.
  그 외 타입 문자열은 파싱 실패로 처리하고 리포트에 표시(줄은 미체크 유지)

## 4. 파싱 & 자동 메타데이터 조회

신규 모듈 `investor_intel/pipeline/inbox.py`.

### 4.1 라인 파싱

```python
@dataclass
class InboxLine:
    line_no: int
    checked: bool
    type: str
    value: str
    extra: str | None  # investor의 essay URL 등
    raw: str           # 원본 줄 (파싱 실패 시 그대로 보존)
```

정규식: `^-\s\[( |x)\]\s*(\w+):\s*(.+)$`. 매치 실패 줄은 원본 그대로 두고
`ParseError`로 리포트.

### 4.2 타입별 resolver

공통 인터페이스: `resolve(value: str, extra: str | None) -> ResolvedEntry | ResolveFailure`

- **naver / telegram / telegram_private**
  - id: `f"{type}_{slug}"`, slug는 URL 마지막 path segment (`telegram`은 `/s/` 제거 후)
  - name: slug 그대로
  - 나머지 필드 기본값: `enabled: true, weight: 1.0, collection_mode: full, backfill_days: 365, tags: [type]`
  - 네트워크 조회 없음 (URL 자체가 필요한 정보 전부)

- **sec**
  - `https://www.sec.gov/files/company_tickers.json` (기존 `SimpleHttpClient` 재사용,
    `SEC_USER_AGENT` 필요)를 조회해 티커→CIK/회사명 매핑. 대량 정적 파일이라
    `data/sec_company_tickers.json`에 24시간 캐시.
  - CIK는 10자리 zero-pad 문자열로 저장
  - `filing_types: [10-K, 10-Q, 8-K]`, `is_foreign_private_issuer: false` 기본값
  - 리포트에 "외국민간발행인(20-F/6-K)이면 companies.yaml에서 직접 고치세요" 안내 추가

- **dart**
  - 기존 DART corp_code sqlite 캐시 재사용. `find_dart_corp_code`가 `corp_name`도
    반환하도록 확장 (`find_dart_company_by_stock_code(conn, stock_code) -> (corp_code, corp_name) | None`
    신규 함수 추가, 기존 함수는 그대로 둠)
  - 캐시가 비어 있으면 기존 `resolve_corp_code`와 동일하게 `DART_API_KEY`로 1회 새로고침
  - `report_types: [A, B]` 기본값

- **investor**
  - `https://data.sec.gov/submissions/CIK{cik:0>10}.json` 조회, `name` 필드 SEC HTTP 헤더는 `SimpleHttpClient` 재사용
  - `entityName` → `name`, `fund_name`에 동일 값
  - `id`: entityName을 소문자+언더스코어로 슬러그화
  - `related_essay_url`: `extra` 값 그대로 (없으면 null)

### 4.3 실패 처리

조회 실패(HTTP 에러, 티커/CIK 매칭 실패)는 해당 줄을 미체크 상태로 남기고
`ResolveFailure(reason)`으로 리포트. 다음 실행 시 자동 재시도됨.

## 5. 중복 판정 & YAML 반영

각 config 로더로 기존 항목을 읽어 식별키로 중복 체크:

| 타입 | 대상 파일 | 식별키 |
|---|---|---|
| naver/telegram/telegram_private | `sources.yaml` | `url` |
| sec | `companies.yaml` | `ticker` |
| dart | `dart_companies.yaml` | `ticker` |
| investor | `investors.yaml` | `cik` |

이미 존재하면 새로 추가하지 않고 줄만 체크 처리, 리포트에 "이미 존재 (skip)"로 표시.
신규면 pydantic 모델로 검증 후 YAML 리스트 끝에 append, `yaml.safe_dump`로 파일 재작성
(주석/포맷 보존보다 단순성 우선 — 기존 파일들도 사람이 직접 수정하는 짧은 리스트라
   전체 재작성해도 무방).

`dart_companies.yaml`에는 corp_code 생략 가능 안내 주석이 파일 최상단에 있음 —
safe_dump는 주석을 보존하지 않으므로, 이 파일만 고정 헤더 주석 문자열을 코드에
상수로 갖고 있다가 재작성 시 맨 위에 다시 붙인다. 다른 3개 파일은 주석이 없어
해당 없음.

## 6. CLI

`investor_intel/cli.py`에 신규 명령 추가:

```python
@app.command(name="sync-inbox")
def sync_inbox_cmd(
    config_dir: Annotated[Path, ...] = Path("./config"),
    vault_path: Annotated[Path, ...] = Path("./vault"),
) -> None:
```

동작:
1. `vault_path / "00_System" / "inbox_sources.md"` 읽기 (없으면 헤더만 있는 빈 파일 생성 후 안내)
2. 미체크 줄 각각 파싱 → resolve → 중복체크 → append/skip/fail 판정
3. 성공/skip 처리된 줄만 체크 표시로 갱신해 파일 다시 쓰기
4. 콘솔에 타입별 추가/스킵/실패 건수 + 실패 사유 목록 출력

## 7. 테스트

`tests/test_inbox.py`:
- 라인 파싱: 정상/체크됨/주석/빈줄/알 수 없는 타입/포맷 오류
- 각 타입 resolver: fake HTTP client로 성공/조회실패 케이스
- DART 신규 lookup 함수: sqlite fixture 대상 단위 테스트
- 중복 판정: 이미 존재하는 url/ticker/cik → skip
- `sync_inbox` 통합: tmp_path에 inbox.md + config yaml 세팅 → 실행 후 yaml 내용,
  inbox 체크 상태, 리포트 값 검증

## 8. 완료 조건

- `vault/00_System/inbox_sources.md`가 없으면 자동 생성됨
- 6개 타입 모두 최소 1개 성공 케이스 + 1개 실패 케이스 테스트 통과
- `uv run investor-intel sync-inbox` 실행 시 실제 네트워크 접근 없이 fake client로
  테스트 가능 (unit test는 진짜 SEC/DART API 호출 안 함)
- 기존 `collect`/`analyze` 등 다른 명령 동작에 영향 없음
