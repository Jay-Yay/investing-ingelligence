# TODO: 텔레그램 수집 telegram_private 전환 마무리

## 배경

공개 웹 스크랩(`t.me/s/<채널>`) 방식은 실행당 페이지 한도가 있어, collect 를
며칠 걸러 돌리면 고volume 채널(getfeed 하루 ~120건, quantum_ALGO ~35건)의
초과분이 유실되고 체크포인트가 최신 메세지로 점프해 그 구간을 다시 못 가져온다.
vault 실측상 이미지+캡션 없는 메세지가 파서에서 버려지는 것도 저volume 채널
(Jstockclass·Samsung_Global_AI_SW 하루 5~16건)의 수집량이 실제보다 적어 보이는
원인이다.

## 완료된 변경 (2026-09-04)

- `investor_intel/collectors/telegram.py:16` — `_MAX_PAGES` 10 → 30
  (웹 스크랩 폴백 경로의 페이지 한도 상향).
- `config/sources.yaml` — 텔레그램 소스 17개 전부 `type: telegram` →
  `type: telegram_private` 로 변경 (`type:` 한 줄만, URL·id·tags 그대로).
  대상: allbareun, BRILLER_Research, kimcharger, getfeed, dolbikong, skitteam,
  Jstockclass, Samsung_Global_AI_SW, kyobofnbcosmetic, yeonsour, akacommodity,
  quantum_ALGO, merITz_tech, shStrategy, china_kis, miraeoillee, KISemicon.
- 체크포인트(`collector_state`)는 `source_id` 가 안 바뀌고 `last_seen_id` 가
  양쪽 다 메세지 숫자 id 라서 증분 이어받기가 그대로 유효하다. 재수집 불필요.
- 미디어 메타데이터 캡처는 요청대로 **구현하지 않음**(텍스트만). Telethon 경로도
  `telethon_client.py` 에서 `raw_text` 없는 메세지는 계속 스킵한다.

## 발견된 문제 (2026-09-04, 실제 collect 후 data 브랜치 merge 중 확인)

### 0. telegram_private 콘텐츠가 기존 telegram(웹스크랩)보다 빈약함 — 첨부기사 미확장

`.env`에 자격증명 채운 뒤 로컬에서 `collect --sources telegram` 실행, 같은 날 GH Actions도
(아직 `main`에 이 파일의 `type: telegram_private` 변경이 안 올라가 있어) 구버전
`telegram`(공개 웹스크랩) 방식으로 같은 채널들을 수집 — 그 결과를 `data` 브랜치에서
merge하며 같은 메세지 id 159건이 add/add 충돌났고, 두 버전 내용을 비교해 드러남:

- 웹스크랩(`telegram`) 버전: 메세지 원문 + **첨부 링크 기사 전문까지 펼쳐서 저장**
  (`investor_intel/collectors/telegram_link_article.py`로 보임).
- Telethon(`telegram_private`) 버전: 메세지 원문 + "텔레그램 수집 시 유의사항" 안내문만.
  **기사 링크 확장이 아예 없음.**

병합 시 사용자 판단으로 충돌 159건은 전부 웹스크랩(원격) 버전을 채택함 — 즉 지금
vault에는 이 시점 기준 telegram_private로 새로 받은 콘텐츠 대신 구버전 콘텐츠가 남아있다.

- [ ] `telegram_private.py` (또는 `telethon_client.py`) 경로에도 `telegram_link_article.py`의
      기사 확장 로직을 연결할지 결정. 연결 안 하면 `type: telegram_private`로 완전히
      전환하는 순간 모든 채널이 기사 확장을 잃는다 — 이게 이 마이그레이션의 진짜 남은
      리스크임 (자격증명보다 이게 더 중요할 수 있음).
- [ ] 결정 전까지는 `config/sources.yaml`의 `type: telegram_private` 변경을 `main`에
      push하지 말 것 — push하는 순간 GH Actions/다른 Mac도 이 콘텐츠 손실을 그대로 겪는다.

## 남은 작업

### 1. Telethon 자격증명 채우기 — 완료 (2026-09-04, 로컬 Mac)

- [x] `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` — 사용자가 `.env`에 채움.
- [x] `TELEGRAM_SESSION` — 대화형 로그인(전화번호+코드)으로 발급, `.env`에 저장.
      세션 생성 스크립트는 임시로 만들어 쓰고 삭제함(재사용 필요하면 다시 작성).
- [x] `uv run --extra telethon python -m investor_intel collect --sources telegram`로
      17개 소스 정상 확인 (294건 저장). 단, 콘텐츠 품질 이슈는 위 "발견된 문제 0" 참고.

### 2. GH Actions / 다른 Mac 에도 자격증명 배포 — 위 "발견된 문제 0" 해결 전까지 보류

- [ ] `config/sources.yaml` 변경을 `main` 에 커밋·푸시하면 GH Actions·다른 Mac 도
      즉시 telegram_private 경로를 탄다. 그쪽들에도 Telethon 자격증명(Actions는
      repository secret, Mac은 `.env`)이 있어야 텔레그램 수집이 돈다. 없으면
      해당 러너에서 텔레그램 17개가 조용히 빠진 채로 수집이 진행된다.

### 3. 운영 리스크 점검 (전환 후 첫 며칠 로그 확인)

- [ ] 소스마다 `RealTelethonClient` 를 따로 만들고 `iter_messages` 마다
      connect/disconnect 한다(`telethon_client.py:33`). 17개 순차 → 로그인
      핸드셰이크 17회. FloodWait(특히 로그인/연결 단계)가 웹 스크랩보다 잦을 수
      있음. 현재 자동 대기는 message-fetch FloodWait 60초까지만 처리.
      → 잦으면 클라이언트 1개를 17개 소스가 공유하도록 리팩터 고려.
- [ ] `telegram_private.py:11` `_FETCH_LIMIT = 200` 유지 중. getfeed 는 매일
      돌리면 충분하나 2일 넘게 밀리면 초과분 유실. 밀림이 반복되면 상향 검토.

### 4. inbox 경로 정합성 (선택)

- [ ] `investor_intel/pipeline/inbox.py` 의 URL 붙여넣기 → 소스 추가 로직은 아직
      `type: "telegram"` 을 만든다(`tests/test_inbox.py:83,135,144`). 일회성 추가
      링크는 웹 스크랩으로도 충분하면 그대로 두고, 일관성을 원하면
      `telegram_private` 로 바꾸고 테스트도 수정.
