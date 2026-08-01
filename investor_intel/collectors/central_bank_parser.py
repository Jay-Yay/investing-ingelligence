from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin


def _abs_url(base: str, href: str) -> str:
    """href가 raw HTML 속성값이라 `&amp;` 등 엔티티가 살아있을 수 있으므로(BOK의
    fileDown.do?...&atchFileId=...) 절대경로로 합치기 전에 언이스케이프한다."""
    return urljoin(base, unescape(href))


@dataclass
class CentralBankArticle:
    """중앙은행 성명서/회의록 1건. `url`은 (마감된) 체크포인트 비교와 canonical_url로 쓰이는
    안정적 식별자 - HTML 상세페이지가 있으면 그 URL을, PDF만 있으면 PDF URL 자체를 담는다."""

    url: str
    title: str
    meeting_date: date
    pdf_url: str | None = None


def dedupe_sort_desc(articles: list[CentralBankArticle]) -> list[CentralBankArticle]:
    """최신순 정렬 + URL 중복 제거. 각 파서 함수가 단일 인덱스 페이지 결과에 적용하는 것은
    물론, central_bank.py가 여러 페이지(연도별/스니펫별)를 이어붙인 뒤에도 다시 적용해야
    한다 - 개별 페이지가 최신순이어도 페이지 자체를 이어붙이는 순서(연도 루프 방향, ECB
    data-snippets 목록 순서 등)가 뒤집히면 collect_incremental의 "체크포인트 이전까지만
    처리" 로직이 조용히 깨진다(오래된 항목을 checkpoint_id로 저장해 매번 전체를 새 항목으로
    오인하거나, 반대로 새 항목을 누락)."""
    seen: set[str] = set()
    result: list[CentralBankArticle] = []
    for article in sorted(articles, key=lambda a: a.meeting_date, reverse=True):
        if article.url in seen:
            continue
        seen.add(article.url)
        result.append(article)
    return result


# --- generic HTML container text extractor -------------------------------------
# Several banks publish the statement/minutes as a plain HTML page rather than a PDF - the full
# text sits inside one identifiable container (a `<div id="...">` or the page's single `<main>`).
# This walks the tag tree tracking depth of the *matching tag name only* (same idiom as
# naver_html_parser._PostViewParser) so nested same-name tags inside the container don't
# terminate capture early, and stops as soon as that container's own closing tag is seen.


class _ContainerTextParser(HTMLParser):
    def __init__(self, tag: str, attr: str | None, value: str | None) -> None:
        super().__init__(convert_charrefs=True)
        self._tag = tag
        self._attr = attr
        self._value = value
        self._tag_depth = 0
        self._container_depth: int | None = None
        self._captured = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == self._tag:
            self._tag_depth += 1
            # only ever open the *first* matching container - real pages often reuse a class
            # name for an unrelated element further down (e.g. BOJ's page footer also carries
            # `class="outline"`), and re-opening on that later match would append its nav/address
            # text onto the real body.
            if self._container_depth is None and not self._captured and self._matches(attrs):
                self._container_depth = self._tag_depth
                self._captured = True
        block_tags = ("p", "div", "li", "tr", "br", "h1", "h2", "h3")
        if self._container_depth is not None and tag in block_tags:
            self.parts.append("\n")

    def _matches(self, attrs: list[tuple[str, str | None]]) -> bool:
        if self._attr is None:
            return True
        value = dict(attrs).get(self._attr) or ""
        return self._value in value.split()

    def handle_endtag(self, tag: str) -> None:
        if tag == self._tag:
            if self._container_depth is not None and self._tag_depth == self._container_depth:
                self._container_depth = None
            self._tag_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._container_depth is not None:
            self.parts.append(data)


def extract_container_text(
    html: str, tag: str, attr: str | None = None, value: str | None = None
) -> str | None:
    parser = _ContainerTextParser(tag, attr, value)
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    text = text.strip()
    return text or None


# --- Fed (federalreserve.gov) ---------------------------------------------------
# One index page covers ~5yrs of history for both statements and minutes, fully static HTML:
# https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# Statements: /newsevents/pressreleases/monetary{YYYYMMDD}a.htm (the "a" suffix only - "b"/"c"
# same-day suffixes are other releases like discount-rate notices, not the FOMC statement).
# Minutes: /monetarypolicy/files/fomcminutes{YYYYMMDD}.pdf (direct PDF, ~3wks after the meeting).
#
# The calendar page occasionally schedules a standalone "Statement on Longer-Run Goals and
# Monetary Policy Strategy" notation vote (e.g. 2025-08-22) between regular meetings - its href
# matches the same monetary{YYYYMMDD}a.htm pattern despite not being a rate-decision statement.
# Matching hrefs by regex alone (as an earlier version of this parser did) silently mislabels
# that as an FOMC statement. Each meeting's real block instead labels its statement link with a
# `<strong>Statement:</strong>` prefix (the notation-vote block does not), so parsing is scoped
# per meeting block and requires that label immediately before the href.

FED_BASE_URL = "https://www.federalreserve.gov"
FED_CALENDAR_URL = f"{FED_BASE_URL}/monetarypolicy/fomccalendars.htm"

_FED_MEETING_BLOCK_START_RE = re.compile(r'<div class="[^"]*row fomc-meeting"[^>]*>')
_FED_STATEMENT_RE = re.compile(
    r'<strong>Statement:</strong>.*?href="(/newsevents/pressreleases/monetary(\d{8})a\.htm)"',
    re.S,
)
_FED_MINUTES_RE = re.compile(r'href="(/monetarypolicy/files/fomcminutes(\d{8})\.pdf)"')


def _fed_meeting_blocks(html: str) -> list[str]:
    starts = [m.start() for m in _FED_MEETING_BLOCK_START_RE.finditer(html)]
    return [
        html[start : starts[i + 1] if i + 1 < len(starts) else len(html)]
        for i, start in enumerate(starts)
    ]


def _parse_yyyymmdd(digits: str) -> date:
    return date(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]))


def parse_fed_statements_index(html: str) -> list[CentralBankArticle]:
    articles = []
    for block in _fed_meeting_blocks(html):
        match = _FED_STATEMENT_RE.search(block)
        if match is None:
            continue
        href, digits = match.group(1), match.group(2)
        meeting_date = _parse_yyyymmdd(digits)
        articles.append(
            CentralBankArticle(
                url=_abs_url(FED_BASE_URL, href),
                title=f"FOMC Statement ({meeting_date.isoformat()})",
                meeting_date=meeting_date,
            )
        )
    return dedupe_sort_desc(articles)


def parse_fed_minutes_index(html: str) -> list[CentralBankArticle]:
    articles = [
        CentralBankArticle(
            url=_abs_url(FED_BASE_URL, href),
            title=f"FOMC Minutes ({_parse_yyyymmdd(digits).isoformat()})",
            meeting_date=_parse_yyyymmdd(digits),
            pdf_url=_abs_url(FED_BASE_URL, href),
        )
        for href, digits in _FED_MINUTES_RE.findall(html)
    ]
    return dedupe_sort_desc(articles)


def extract_fed_statement_text(html: str) -> str | None:
    return extract_container_text(html, "div", "id", "article")


# --- ECB (ecb.europa.eu) ---------------------------------------------------------
# The listing pages are JS-driven, but the underlying per-year snippets they lazy-load are
# themselves static HTML (`data-snippets="../2026/html/index_include.en.html,..."` on the
# `<dl id="lazyload-container">`). Fetch the index once to discover snippet URLs, then fetch the
# current + previous year's snippet directly.

ECB_BASE_URL = "https://www.ecb.europa.eu"
ECB_STATEMENTS_INDEX_URL = (
    f"{ECB_BASE_URL}/press/press_conference/monetary-policy-statement/html/index.en.html"
)
ECB_ACCOUNTS_INDEX_URL = f"{ECB_BASE_URL}/press/accounts/html/index.en.html"

_ECB_SNIPPETS_RE = re.compile(r"data-snippets='([^']+)'")
_ECB_STATEMENT_LINK_RE = re.compile(
    r'href="([^"]*/monetary-policy-statement/\d{4}/html/ecb\.is(\d{6})~[0-9a-f]+\.en\.html)"'
)
_ECB_ACCOUNTS_LINK_RE = re.compile(
    r'href="([^"]*/accounts/\d{4}/html/ecb\.mg(\d{6})~[0-9a-f]+\.en\.html)"'
)


def parse_ecb_snippet_urls(index_html: str, index_url: str) -> list[str]:
    """`data-snippets`는 인덱스 페이지 기준 상대경로(`../2026/html/...`) 콤마 목록이다."""
    match = _ECB_SNIPPETS_RE.search(index_html)
    if match is None:
        return []
    return [_abs_url(index_url, part) for part in match.group(1).split(",") if part.strip()]


def _parse_ecb_yymmdd(digits: str) -> date:
    return date(2000 + int(digits[0:2]), int(digits[2:4]), int(digits[4:6]))


def parse_ecb_statements_snippet(html: str) -> list[CentralBankArticle]:
    articles = [
        CentralBankArticle(
            url=_abs_url(ECB_BASE_URL, href),
            title=f"ECB Monetary Policy Statement ({_parse_ecb_yymmdd(digits).isoformat()})",
            meeting_date=_parse_ecb_yymmdd(digits),
        )
        for href, digits in _ECB_STATEMENT_LINK_RE.findall(html)
    ]
    return dedupe_sort_desc(articles)


def parse_ecb_accounts_snippet(html: str) -> list[CentralBankArticle]:
    articles = [
        CentralBankArticle(
            url=_abs_url(ECB_BASE_URL, href),
            title=f"ECB Monetary Policy Accounts ({_parse_ecb_yymmdd(digits).isoformat()})",
            meeting_date=_parse_ecb_yymmdd(digits),
        )
        for href, digits in _ECB_ACCOUNTS_LINK_RE.findall(html)
    ]
    return dedupe_sort_desc(articles)


def extract_ecb_main_text(html: str) -> str | None:
    return extract_container_text(html, "main", None, None)


# --- BOE (bankofengland.co.uk) ---------------------------------------------------
# BOE publishes the summary + full minutes as a single combined document (unlike the other
# banks) at a predictable monthly URL. The `/monetary-policy` landing page links the current and
# previous editions; older editions are reachable from the same page's year archives, but
# incremental collection only needs the page to surface newly-published links.

BOE_BASE_URL = "https://www.bankofengland.co.uk"
BOE_INDEX_URL = f"{BOE_BASE_URL}/monetary-policy"

_BOE_LINK_RE = re.compile(
    r'href="(/monetary-policy-summary-and-minutes/(\d{4})/([a-z]+)-\d{4})"'
)
_BOE_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}  # fmt: skip


def parse_boe_index(html: str) -> list[CentralBankArticle]:
    articles = []
    for href, year_str, month_str in _BOE_LINK_RE.findall(html):
        month = _BOE_MONTHS.get(month_str.lower())
        if month is None:
            continue
        meeting_date = date(int(year_str), month, 1)
        articles.append(
            CentralBankArticle(
                url=_abs_url(BOE_BASE_URL, href),
                title=f"BOE Monetary Policy Summary and Minutes ({year_str}-{month:02d})",
                meeting_date=meeting_date,
            )
        )
    return dedupe_sort_desc(articles)


def extract_boe_content_text(html: str) -> str | None:
    return extract_container_text(html, "div", "id", "content")


# --- BOJ (boj.or.jp) -------------------------------------------------------------
# Statement/minutes filenames use a clean date-coded "k{YYMMDD}a.*"/"g{YYMMDD}.*" pattern, but
# BOJ switched from HTML pages (state_{year}/k...a.htm, minu_{year}/g....htm - the format for
# 2025 and all earlier years) to PDF-only (mpr_{year}/k...a.pdf, minu_{year}/g....pdf - seen
# starting March 2026) partway through 2026. Matching only ".pdf" would silently drop every
# statement/minutes released before that switch, so both extensions (and both folder names for
# statements, since the PDF-era files moved out of the state_{year} folder) are matched here.
# The "a" filename suffix specifically (not b/c/d) is what excludes same-day annexes (JGB
# purchase plans etc.) from the statements match - `state_{year}/index.htm` lists both eras.

BOJ_BASE_URL = "https://www.boj.or.jp"

_BOJ_STATEMENT_RE = re.compile(
    r'href="(/en/mopo/mpmdeci/(?:state|mpr)_\d{4}/k(\d{6})a\.(pdf|htm))"'
)
_BOJ_MINUTES_RE = re.compile(r'href="(/en/mopo/mpmsche_minu/minu_\d{4}/g(\d{6})\.(pdf|htm))"')


def _parse_boj_yymmdd(digits: str) -> date:
    return date(2000 + int(digits[0:2]), int(digits[2:4]), int(digits[4:6]))


def boj_statements_index_url(year: int) -> str:
    return f"{BOJ_BASE_URL}/en/mopo/mpmdeci/state_{year}/index.htm"


def boj_minutes_index_url(year: int) -> str:
    return f"{BOJ_BASE_URL}/en/mopo/mpmsche_minu/minu_{year}/index.htm"


def parse_boj_statements_index(html: str) -> list[CentralBankArticle]:
    articles = []
    for href, digits, ext in _BOJ_STATEMENT_RE.findall(html):
        meeting_date = _parse_boj_yymmdd(digits)
        url = _abs_url(BOJ_BASE_URL, href)
        articles.append(
            CentralBankArticle(
                url=url,
                title=f"BOJ Statement on Monetary Policy ({meeting_date.isoformat()})",
                meeting_date=meeting_date,
                pdf_url=url if ext == "pdf" else None,
            )
        )
    return dedupe_sort_desc(articles)


def parse_boj_minutes_index(html: str) -> list[CentralBankArticle]:
    articles = []
    for href, digits, ext in _BOJ_MINUTES_RE.findall(html):
        meeting_date = _parse_boj_yymmdd(digits)
        url = _abs_url(BOJ_BASE_URL, href)
        articles.append(
            CentralBankArticle(
                url=url,
                title=f"BOJ Minutes of the Monetary Policy Meeting ({meeting_date.isoformat()})",
                meeting_date=meeting_date,
                pdf_url=url if ext == "pdf" else None,
            )
        )
    return dedupe_sort_desc(articles)


def extract_boj_text(html: str) -> str | None:
    # both statement and minutes detail pages share the same CMS template - the real content
    # sits in the *first* `class="outline"` container (`outline mod_outer`); a second, unrelated
    # `class="outline"` div appears later inside the page footer, but depth-tracked capture stops
    # at the first container's own closing tag before ever reaching it.
    return extract_container_text(html, "div", "class", "outline")


# --- BOK (bok.or.kr) --------------------------------------------------------------
# One table per year (`listYear.do?menuNo=200755&mtgSe=A&pYear={year}`) with a row per meeting
# date; each row groups the 결정문(statement)/의사록(minutes) PDFs (and other unrelated
# attachments) under a shared `fileDown.do?...&atchFileId=...&fileSn=...` download link, keyed
# only by each link's `title="...file name...pdf"` attribute. This scans row-by-row (split on
# `<tr>`) rather than tracking full table structure, since the file-group markup is deeply and
# uniformly nested and a title-text match is more robust to markup churn than a selector chain.

BOK_BASE_URL = "https://www.bok.or.kr"


def bok_meetings_index_url(year: int) -> str:
    path = "/portal/singl/crncyPolicyDrcMtg/listYear.do"
    return f"{BOK_BASE_URL}{path}?menuNo=200755&mtgSe=A&pYear={year}"


_BOK_ROW_DATE_RE = re.compile(r'<th scope="row">(\d{1,2})월\s*(\d{1,2})일')
_BOK_FILE_LINK_RE = re.compile(
    r'href="(/portal/cmmn/file/fileDown\.do\?[^"]+)"\s+title="([^"]+\.pdf)"'
)


def _bok_first_matching_file(row_html: str, keyword: str) -> tuple[str, str] | None:
    for href, title in _BOK_FILE_LINK_RE.findall(row_html):
        if keyword in title:
            return href, title
    return None


def _split_bok_rows(html: str) -> list[str]:
    rows = re.split(r"(?=<tr>)", html)
    return [row for row in rows if '<th scope="row">' in row]


def parse_bok_statements_index(html: str, year: int) -> list[CentralBankArticle]:
    articles = []
    for row in _split_bok_rows(html):
        date_match = _BOK_ROW_DATE_RE.search(row)
        found = _bok_first_matching_file(row, "보도자료")
        if date_match is None or found is None:
            continue
        href, title = found
        meeting_date = date(year, int(date_match.group(1)), int(date_match.group(2)))
        articles.append(
            CentralBankArticle(
                url=_abs_url(BOK_BASE_URL, href),
                title=f"한국은행 통화정책방향 결정문 ({meeting_date.isoformat()})",
                meeting_date=meeting_date,
                pdf_url=_abs_url(BOK_BASE_URL, href),
            )
        )
    return dedupe_sort_desc(articles)


def parse_bok_minutes_index(html: str, year: int) -> list[CentralBankArticle]:
    articles = []
    for row in _split_bok_rows(html):
        date_match = _BOK_ROW_DATE_RE.search(row)
        found = _bok_first_matching_file(row, "의사록")
        if date_match is None or found is None:
            continue
        href, title = found
        meeting_date = date(year, int(date_match.group(1)), int(date_match.group(2)))
        articles.append(
            CentralBankArticle(
                url=_abs_url(BOK_BASE_URL, href),
                title=f"한국은행 금융통화위원회 의사록 ({meeting_date.isoformat()})",
                meeting_date=meeting_date,
                pdf_url=_abs_url(BOK_BASE_URL, href),
            )
        )
    return dedupe_sort_desc(articles)
