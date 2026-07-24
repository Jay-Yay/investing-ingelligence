from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.naver_parser import NaverPost

_KST = ZoneInfo("Asia/Seoul")
_HTML_FALLBACK_MAX_PAGES = 3
_COUNT_PER_PAGE = 30
_LIST_URL = (
    "https://blog.naver.com/PostTitleListAsync.naver"
    "?blogId={blog_id}&currentPage={page}&categoryNo=&parentCategoryNo="
    f"&countPerPage={_COUNT_PER_PAGE}"
)
_DETAIL_URL = "https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"


@dataclass
class _PostDetail:
    title: str
    body_text: str
    published_at: datetime


def parse_post_log_nos(json_text: str) -> list[str]:
    data = json.loads(json_text)
    return [post["logNo"] for post in data.get("postList", [])]


@dataclass
class _PendingParagraph:
    parts: list[str] = field(default_factory=list)


class _PostViewParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._div_depth = 0
        self._title_div_depth: int | None = None
        self._main_div_depth: int | None = None
        self._publish_date_span_depth: int | None = None
        self._span_depth = 0

        self.title_parts: list[str] = []
        self.body_paragraphs: list[str] = []
        self.publish_date_text: str = ""

        self._active_paragraph: _PendingParagraph | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = (attrs_dict.get("class") or "").split()

        if tag == "div":
            self._div_depth += 1
            if "se-title-text" in classes:
                self._title_div_depth = self._div_depth
            if "se-main-container" in classes:
                self._main_div_depth = self._div_depth
        elif tag == "span":
            self._span_depth += 1
            if "se_publishDate" in classes:
                self._publish_date_span_depth = self._span_depth
        elif tag == "p" and "se-text-paragraph" in classes:
            in_title = self._title_div_depth is not None
            in_body = self._main_div_depth is not None
            if in_title or in_body:
                self._active_paragraph = _PendingParagraph()

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            if self._title_div_depth is not None and self._div_depth == self._title_div_depth:
                self._title_div_depth = None
            if self._main_div_depth is not None and self._div_depth == self._main_div_depth:
                self._main_div_depth = None
            self._div_depth -= 1
        elif tag == "span":
            if (
                self._publish_date_span_depth is not None
                and self._span_depth == self._publish_date_span_depth
            ):
                self._publish_date_span_depth = None
            self._span_depth -= 1
        elif tag == "p" and self._active_paragraph is not None:
            text = "".join(self._active_paragraph.parts).strip()
            if text:
                if self._title_div_depth is not None:
                    self.title_parts.append(text)
                else:
                    self.body_paragraphs.append(text)
            self._active_paragraph = None

    def handle_data(self, data: str) -> None:
        if self._publish_date_span_depth is not None:
            self.publish_date_text += data
        if self._active_paragraph is not None:
            self._active_paragraph.parts.append(data)


def parse_post_detail_html(html_text: str) -> _PostDetail:
    parser = _PostViewParser()
    parser.feed(html_text)

    published_at = datetime.strptime(
        parser.publish_date_text.strip(), "%Y. %m. %d. %H:%M"
    ).replace(tzinfo=_KST)

    return _PostDetail(
        title="".join(parser.title_parts),
        body_text="\n\n".join(parser.body_paragraphs),
        published_at=published_at,
    )


def fetch_posts_via_html(client: SimpleHttpClient, blog_id: str) -> list[NaverPost]:
    log_nos: list[str] = []
    for page in range(1, _HTML_FALLBACK_MAX_PAGES + 1):
        list_json = client.get_text(_LIST_URL.format(blog_id=blog_id, page=page))
        page_log_nos = parse_post_log_nos(list_json)
        if not page_log_nos:
            break
        log_nos.extend(page_log_nos)

    posts: list[NaverPost] = []
    for log_no in log_nos:
        detail_html = client.get_text(_DETAIL_URL.format(blog_id=blog_id, log_no=log_no))
        detail = parse_post_detail_html(detail_html)
        link = f"https://blog.naver.com/{blog_id}/{log_no}"
        posts.append(
            NaverPost(
                guid=log_no,
                title=detail.title,
                link=link,
                description=detail.body_text,
                published_at=detail.published_at,
            )
        )
    return posts
