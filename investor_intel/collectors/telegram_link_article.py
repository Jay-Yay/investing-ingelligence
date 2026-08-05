from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import trafilatura

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.naver_html_parser import fetch_post_body
from investor_intel.collectors.text_extract import truncate

ARTICLE_MAX_CHARS = 20_000
MAX_ARTICLES_PER_MESSAGE = 3

_URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")
_TRAILING_PUNCTUATION = ".,;:!?)]}\"'"
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# 텔레그램 메시지에 흔히 붙는, 뉴스 "기사"가 아닌 링크(영상/소셜/퍼머링크) - 본문 추출 대상에서
# 제외한다. 이 목록에 없는 도메인은 전부 기사 후보로 시도한다(개별 언론사 화이트리스트를
# 유지하는 대신, trafilatura의 실패를 ArticleAttachment.error로 흡수하는 쪽을 택했다).
_EXCLUDED_DOMAINS = {
    "t.me",
    "telegram.me",
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "instagram.com",
    "www.instagram.com",
    "facebook.com",
    "www.facebook.com",
}

_NAVER_BLOG_DOMAINS = {"blog.naver.com", "m.blog.naver.com"}


@dataclass
class ArticleAttachment:
    url: str
    title: str | None = None
    body_text: str | None = None
    error: str | None = None


def _domain(url: str) -> str:
    return urlsplit(url).netloc.lower()


def extract_article_urls(text: str, limit: int = MAX_ARTICLES_PER_MESSAGE) -> list[str]:
    """메시지 본문에서 기사 링크 후보 URL을 순서대로, 중복 없이 뽑는다.

    유튜브/X(트위터)/인스타그램/페이스북/텔레그램 자체 링크처럼 "기사"가 아닌 것으로 알려진
    도메인은 제외한다. 한 메시지에 링크가 여러 개 섞인 스팸성 다이제스트 메시지가 있어
    `limit`으로 메시지당 시도 개수를 제한한다.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for raw in _URL_RE.findall(text):
        url = raw.rstrip(_TRAILING_PUNCTUATION)
        if url in seen or _domain(url) in _EXCLUDED_DOMAINS:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def _extract_naver_blog_ids(url: str) -> tuple[str, str] | None:
    # https://blog.naver.com/{blogId}/{logNo}[?query]
    path = urlsplit(url).path.strip("/")
    parts = path.split("/")
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    return parts[0], parts[1]


def _extract_title(html_text: str) -> str | None:
    match = _TITLE_RE.search(html_text)
    if not match:
        return None
    title = html.unescape(match.group(1)).strip()
    return title or None


def fetch_article(client: SimpleHttpClient, url: str) -> ArticleAttachment:
    """기사 URL 하나를 가져와 읽기용 본문을 추출한다.

    실패(봇 차단, 페이월, JS 렌더링 전용 페이지, 타임아웃 등)해도 예외를 올리지 않고
    `ArticleAttachment.error`에 담아 돌려준다 - 우리가 통제하지 않는 임의의 제3자 사이트를
    다루므로, 첨부 기사 하나의 실패가 텔레그램 메시지 저장 자체를 막아서는 안 된다.
    """
    try:
        naver_ids = _extract_naver_blog_ids(url) if _domain(url) in _NAVER_BLOG_DOMAINS else None
        if naver_ids is not None:
            blog_id, log_no = naver_ids
            body = fetch_post_body(client, blog_id, log_no)
            if not body.strip():
                return ArticleAttachment(url=url, error="네이버 블로그 본문을 추출하지 못했다")
            return ArticleAttachment(url=url, body_text=truncate(body, ARTICLE_MAX_CHARS))

        html_text = client.get_text(url)
        title = _extract_title(html_text)
        extracted = trafilatura.extract(html_text, include_comments=False, include_tables=False)
        if not extracted or not extracted.strip():
            return ArticleAttachment(
                url=url,
                title=title,
                error="기사 본문을 추출하지 못했다(요약만 있거나 JS 렌더링 페이지일 수 있음)",
            )
        return ArticleAttachment(
            url=url, title=title, body_text=truncate(extracted, ARTICLE_MAX_CHARS)
        )
    except Exception as exc:  # noqa: BLE001 - 임의의 외부 사이트 요청, 실패 사유를 그대로 보존
        return ArticleAttachment(url=url, error=str(exc))
