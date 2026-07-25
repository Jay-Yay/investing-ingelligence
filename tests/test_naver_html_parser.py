from pathlib import Path

import httpx
import respx

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.naver_html_parser import (
    fetch_post_body,
    fetch_post_detail,
    fetch_posts_via_html,
    parse_post_detail_html,
    parse_post_log_nos,
)

FIXTURES = Path(__file__).parent / "fixtures" / "naver"
_BLOG_ID = "engineerinvestor"
_LIST_URL = (
    "https://blog.naver.com/PostTitleListAsync.naver"
    f"?blogId={_BLOG_ID}&currentPage={{page}}&categoryNo=&parentCategoryNo=&countPerPage=30"
)
_DETAIL_URL = f"https://blog.naver.com/PostView.naver?blogId={_BLOG_ID}&logNo={{log_no}}"


def _list_json(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _post_view_html() -> str:
    return (FIXTURES / "post_view.html").read_text(encoding="utf-8")


def _post_view_relative_date_html() -> str:
    return (FIXTURES / "post_view_relative_date.html").read_text(encoding="utf-8")


def test_parse_post_log_nos_returns_all_ids() -> None:
    log_nos = parse_post_log_nos(_list_json("post_title_list_page1.json"))
    assert log_nos == ["224355263150", "224356037349"]


def test_parse_post_log_nos_handles_empty_list() -> None:
    assert parse_post_log_nos(_list_json("post_title_list_empty.json")) == []


def test_parse_post_detail_html_extracts_title_body_and_kst_datetime() -> None:
    detail = parse_post_detail_html(_post_view_html())

    assert detail.title == "구글 실적 후기"
    assert "매출과 CapEx가 동시에 증가했다" in detail.body_text
    assert "한 줄 요약" in detail.body_text
    assert detail.published_at.isoformat() == "2026-07-23T11:30:00+09:00"


@respx.mock
def test_fetch_post_detail_fetches_and_parses_single_post() -> None:
    respx.get(_DETAIL_URL.format(log_no="224355263150")).mock(
        return_value=httpx.Response(200, text=_post_view_html())
    )

    client = SimpleHttpClient()
    detail = fetch_post_detail(client, _BLOG_ID, "224355263150")
    client.close()

    assert detail.title == "구글 실적 후기"
    assert "매출과 CapEx가 동시에 증가했다" in detail.body_text


@respx.mock
def test_fetch_post_body_succeeds_even_when_publish_date_is_relative() -> None:
    # se_publishDate renders as a relative string ("N시간 전") for posts published within the
    # last day - parse_post_detail_html/fetch_post_detail can't parse that as a date, but
    # fetch_post_body only needs the body text and must not fail on it.
    respx.get(_DETAIL_URL.format(log_no="224356537553")).mock(
        return_value=httpx.Response(200, text=_post_view_relative_date_html())
    )

    client = SimpleHttpClient()
    body = fetch_post_body(client, _BLOG_ID, "224356537553")
    client.close()

    assert "발행 직후라 상대 시간으로 표시되는 글이다" in body


@respx.mock
def test_fetch_posts_via_html_stops_pagination_on_empty_page() -> None:
    respx.get(_LIST_URL.format(page=1)).mock(
        return_value=httpx.Response(200, text=_list_json("post_title_list_page1.json"))
    )
    respx.get(_LIST_URL.format(page=2)).mock(
        return_value=httpx.Response(200, text=_list_json("post_title_list_empty.json"))
    )
    respx.get(_DETAIL_URL.format(log_no="224355263150")).mock(
        return_value=httpx.Response(200, text=_post_view_html())
    )
    respx.get(_DETAIL_URL.format(log_no="224356037349")).mock(
        return_value=httpx.Response(200, text=_post_view_html())
    )

    client = SimpleHttpClient()
    posts = fetch_posts_via_html(client, _BLOG_ID)
    client.close()

    assert len(posts) == 2
    assert {p.guid for p in posts} == {"224355263150", "224356037349"}
    assert all(p.link.startswith("https://blog.naver.com/engineerinvestor/") for p in posts)
    assert all(p.title == "구글 실적 후기" for p in posts)


@respx.mock
def test_fetch_posts_via_html_stops_at_page_cap_without_empty_page() -> None:
    for page in range(1, 4):
        respx.get(_LIST_URL.format(page=page)).mock(
            return_value=httpx.Response(200, text=_list_json("post_title_list_page1.json"))
        )
    respx.get(_DETAIL_URL.format(log_no="224355263150")).mock(
        return_value=httpx.Response(200, text=_post_view_html())
    )
    respx.get(_DETAIL_URL.format(log_no="224356037349")).mock(
        return_value=httpx.Response(200, text=_post_view_html())
    )

    client = SimpleHttpClient()
    posts = fetch_posts_via_html(client, _BLOG_ID)
    client.close()

    # 3 pages x 2 posts/page = 6, even though pages never returned empty
    assert len(posts) == 6
