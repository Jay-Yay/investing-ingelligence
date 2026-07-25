# 네이버 블로그 원문 전체 저장 — 설계 문서

- 작성일: 2026-07-25
- 상태: 브레인스토밍 승인 완료

## 1. 배경 및 문제

`NaverBlogCollector._fetch_all_posts`는 `rss.blog.naver.com/{blogId}.xml`을 우선 사용하고,
RSS가 실패하거나(예외) 빈 목록을 반환할 때만 `PostView.naver` HTML을 직접 파싱하는 폴백
(`fetch_posts_via_html`)으로 넘어간다.

실제 저장된 vault 문서(`vault/10_Sources/Naver/engineerinvestor/**/*.md`)를 확인한 결과,
현재 운영 중인 `naver_engineerinvestor` 소스는 RSS가 항상 정상 응답하기 때문에 폴백이
발동하지 않고, 모든 글이 RSS의 `description` 필드(짧은 요약 + 썸네일 `<img>` 태그, 문장
중간에 `"......."`로 잘림, 일부 인코딩 깨짐)만 `## 원문` 섹션에 저장되어 있다. 즉 "원문
전체"가 아니라 "RSS 요약본"이 저장되는 회귀 상태다.

반대로 텔레그램(`TelegramCollector`, `t.me/s/{channel}` 공개 미리보기 파싱)은 조사 결과
이미 전체 메시지 텍스트를 저장하고 있음을 확인했다(저장된 장문 vault 문서, 그리고 라이브로
다시 크롤링한 채널 HTML 모두에서 잘림 표시(`Показать полностью`, `js-message_more` 등)
없이 전체 텍스트 확인). 사용자 확인 결과 이번 작업 범위는 **네이버 블로그만**이다.

## 2. 스코프 판단

기존 `NaverBlogCollector`/`naver_html_parser.py`/`naver_parser.py`를 조금 손보는 단일
기능. 별도 서브시스템 분리 불필요.

## 3. 설계

**핵심 아이디어**: RSS는 글 목록 발견(guid/link/title/published_at)에만 쓰고, 본문
(`description`)은 항상 `PostView.naver` 상세 페이지를 새로 파싱해서 채운다. HTML 폴백
경로도 동일한 상세 페이지 파싱을 거치므로, "저장되는 본문은 항상 상세 페이지에서 가져온
값"이라는 불변식 하나만 유지하면 된다.

### 3.1 `naver_html_parser.py`

현재 `fetch_posts_via_html`의 루프 내부에 있는 "상세 페이지 fetch + 파싱" 로직을
재사용 가능한 함수로 분리:

```python
def fetch_post_detail(client: SimpleHttpClient, blog_id: str, log_no: str) -> _PostDetail:
    detail_html = client.get_text(_DETAIL_URL.format(blog_id=blog_id, log_no=log_no))
    return parse_post_detail_html(detail_html)
```

`fetch_posts_via_html`은 이 함수를 호출하도록 리팩터링(동작 변화 없음, 순수 추출).

### 3.2 `naver_parser.py`

새 헬퍼:

```python
def extract_log_no(url: str) -> str:
    return url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
```

RSS의 `guid`(쿼리스트링 없는 `https://blog.naver.com/{blogId}/{logNo}` 형태) 또는
`link`(`?fromRss=true&trackingCode=rss` 쿼리스트링 포함)에서 모두 안전하게 log_no를
추출할 수 있어야 하므로 쿼리스트링을 먼저 제거한다.

### 3.3 `naver_blog.py`

`NaverBlogCollector.__init__`에서 `self._blog_id = extract_blog_id(source.url)`를 한 번
계산해 캐싱(현재 `_fetch_all_posts`에서 매번 재계산하던 것도 이 값을 재사용하도록 정리).

`_build_item`을 수정해 post마다 상세 페이지를 fetch하고 `description`을 교체:

```python
def _build_item(self, post: NaverPost) -> CollectItem:
    log_no = extract_log_no(post.guid or post.link)
    detail = fetch_post_detail(self._client, self._blog_id, log_no)
    full_post = replace(post, description=detail.body_text)
    body = render_naver_post_body(full_post, self._source, full_post.link)
    ... # 나머지는 기존과 동일, full_post 기준 필드 사용
```

- RSS 경로: 목록 발견용 요청 1회 + 글마다 상세 페이지 요청 1회 (기존 1회 → N+1회로 증가).
- HTML 폴백 경로: 목록 발견 시 이미 상세 페이지를 1회 fetch했지만, `_build_item`에서
  동일 URL을 다시 fetch한다(글마다 총 2회). 코드 단순성을 위해 감수하는 트레이드오프이며,
  폴백은 RSS 실패 시에만 발동하는 드문 경로라 영향이 작다.
- 개별 글의 상세 페이지 fetch/파싱 실패는 기존 `_collect()`의 per-item try/except가 그대로
  잡아서 해당 글만 `errors`에 기록하고 스킵한다. 나머지 글은 정상 처리되어 배치 전체가
  실패하지 않는다(기존 컨벤션과 동일).

### 3.4 `naver_document.py`

`NAVER_LIMITATIONS_NOTE`에서 다음 줄 제거(더 이상 사실이 아님):

```
- RSS에 요약만 제공되는 경우 전체 본문이 아닐 수 있다.
```

## 4. 테스트 영향

`tests/test_naver_blog.py`의 기존 RSS 경로 테스트들은 현재 RSS `description`을 그대로
기대하고 있을 것이므로, `PostView.naver` 상세 페이지 mock을 추가하고 기대값을 상세
페이지에서 파싱된 본문으로 갱신해야 한다. `tests/test_naver_html_parser.py`에는
`fetch_post_detail` 분리에 대한 단위 테스트를 추가한다. `tests/test_naver_parser.py`에는
`extract_log_no`(guid 형태/쿼리스트링 포함 link 형태 둘 다) 테스트를 추가한다.

## 5. 스코프 외

- 텔레그램: 조사 결과 이미 원문 전체를 저장 중이므로 변경 없음.
- RSS 자체의 인코딩 깨짐 이슈: 본문을 더 이상 RSS `description`에서 가져오지 않게 되므로
  자연히 해결되지만, RSS 파싱/디코딩 로직 자체를 별도로 손보지는 않는다.
