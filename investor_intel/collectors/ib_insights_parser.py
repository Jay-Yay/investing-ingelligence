from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser


@dataclass
class IBArticle:
    title: str
    url: str
    published_at: date | None
    summary: str | None
    pdf_url: str | None = None
    author: str | None = None


def _absolutize(href: str, base_url: str) -> str:
    return href if href.startswith("http") else f"{base_url}{href}"


def _dedupe_by_url(articles: list[IBArticle]) -> list[IBArticle]:
    seen: set[str] = set()
    result: list[IBArticle] = []
    for article in articles:
        if article.url in seen:
            continue
        seen.add(article.url)
        result.append(article)
    return result


# --- Goldman Sachs (goldmansachs.com/insights) --------------------------------
# Cards are `<a data-gs-uitk-component="card" href="...">` wrapping a
# `<h4 data-gs-uitk-component="card-title">` with the visible title text.
# The listing exposes no reliably parseable per-card publish date, so
# published_at is left None (collector falls back to the collection date).


class _GSInsightsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._a_depth = 0
        self._card_a_depth: int | None = None
        self._card_href: str | None = None
        self._h4_depth = 0
        self._title_h4_depth: int | None = None
        self._title_parts: list[str] = []

        self.articles: list[IBArticle] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "a":
            self._a_depth += 1
            href = attrs_dict.get("href")
            if (
                self._card_a_depth is None
                and attrs_dict.get("data-gs-uitk-component") == "card"
                and href
            ):
                self._card_a_depth = self._a_depth
                self._card_href = href
                self._title_parts = []
        elif tag == "h4":
            self._h4_depth += 1
            if (
                self._card_a_depth is not None
                and self._title_h4_depth is None
                and attrs_dict.get("data-gs-uitk-component") == "card-title"
            ):
                self._title_h4_depth = self._h4_depth

    def handle_endtag(self, tag: str) -> None:
        if tag == "h4":
            if self._title_h4_depth is not None and self._h4_depth == self._title_h4_depth:
                self._title_h4_depth = None
            self._h4_depth -= 1
        elif tag == "a":
            if self._card_a_depth is not None and self._a_depth == self._card_a_depth:
                title = "".join(self._title_parts).strip()
                if title and self._card_href:
                    self.articles.append(
                        IBArticle(title=title, url=self._card_href, published_at=None, summary=None)
                    )
                self._card_a_depth = None
                self._card_href = None
            self._a_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._title_h4_depth is not None:
            self._title_parts.append(data)


def parse_gs_insights_index(
    html_text: str, base_url: str = "https://www.goldmansachs.com"
) -> list[IBArticle]:
    parser = _GSInsightsParser()
    parser.feed(html_text)
    articles = [
        IBArticle(a.title, _absolutize(a.url, base_url), a.published_at, a.summary)
        for a in parser.articles
    ]
    return _dedupe_by_url(articles)


# --- JPMorgan (jpmorgan.com/insights/research) --------------------------------
# Cards are a flat run of `<a class="card-headline" href="...">Title</a>`,
# `<p class="date">...</p>`, `<p class="info">...</p>` in that order - the
# outer card wrapper's class varies (featured vs. regular cards) so this
# tracks the sequence rather than nesting depth.


def _parse_mon_dd_yyyy(text: str) -> date | None:
    try:
        return datetime.strptime(text.strip(), "%b %d, %Y").date()
    except ValueError:
        return None


class _JPMInsightsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.articles: list[IBArticle] = []
        self._capture: str | None = None
        self._in_pending_card = False
        self._pending_url: str | None = None
        self._pending_title: list[str] = []
        self._pending_date: list[str] = []
        self._pending_summary: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = (attrs_dict.get("class") or "").split()
        href = attrs_dict.get("href")
        if tag == "a" and "card-headline" in classes and href:
            self._flush()
            self._in_pending_card = True
            self._pending_url = href
            self._capture = "title"
        elif tag == "p" and self._in_pending_card and "date" in classes:
            self._capture = "date"
        elif tag == "p" and self._in_pending_card and "info" in classes:
            self._capture = "summary"

    def handle_endtag(self, tag: str) -> None:
        if tag in ("a", "p"):
            self._capture = None

    def handle_data(self, data: str) -> None:
        if self._capture == "title":
            self._pending_title.append(data)
        elif self._capture == "date":
            self._pending_date.append(data)
        elif self._capture == "summary":
            self._pending_summary.append(data)

    def _flush(self) -> None:
        if self._in_pending_card and self._pending_url:
            title = "".join(self._pending_title).strip()
            if title:
                self.articles.append(
                    IBArticle(
                        title=title,
                        url=self._pending_url,
                        published_at=_parse_mon_dd_yyyy("".join(self._pending_date)),
                        summary="".join(self._pending_summary).strip() or None,
                    )
                )
        self._in_pending_card = False
        self._pending_url = None
        self._pending_title = []
        self._pending_date = []
        self._pending_summary = []

    def close(self) -> None:
        self._flush()
        super().close()


def parse_jpm_insights_index(
    html_text: str, base_url: str = "https://www.jpmorgan.com"
) -> list[IBArticle]:
    parser = _JPMInsightsParser()
    parser.feed(html_text)
    parser.close()
    articles = [
        IBArticle(a.title, _absolutize(a.url, base_url), a.published_at, a.summary)
        for a in parser.articles
    ]
    return _dedupe_by_url(articles)


# --- BofA (business.bofa.com institutional investing insights) ---------------
# Cards are `<a class="tile-anchor ..." href="...">` wrapping a
# `<h4 class="tile__headline ...">` title and a `<div class="tile__body ...">`
# whose first `<p>` is the teaser. No reliable per-card publish date is
# exposed, so published_at is left None like Goldman Sachs.


class _BofAInsightsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._a_depth = 0
        self._card_a_depth: int | None = None
        self._card_href: str | None = None
        self._h4_depth = 0
        self._title_h4_depth: int | None = None
        self._div_depth = 0
        self._body_div_depth: int | None = None
        self._p_depth = 0
        self._summary_p_depth: int | None = None

        self.articles: list[IBArticle] = []
        self._title_parts: list[str] = []
        self._summary_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = (attrs_dict.get("class") or "").split()
        href = attrs_dict.get("href")
        if tag == "a":
            self._a_depth += 1
            if self._card_a_depth is None and "tile-anchor" in classes and href:
                self._card_a_depth = self._a_depth
                self._card_href = href
                self._title_parts = []
                self._summary_parts = []
        elif tag == "h4":
            self._h4_depth += 1
            if (
                self._card_a_depth is not None
                and self._title_h4_depth is None
                and "tile__headline" in classes
            ):
                self._title_h4_depth = self._h4_depth
        elif tag == "div":
            self._div_depth += 1
            if (
                self._card_a_depth is not None
                and self._body_div_depth is None
                and "tile__body" in classes
            ):
                self._body_div_depth = self._div_depth
        elif tag == "p":
            self._p_depth += 1
            if self._body_div_depth is not None and self._summary_p_depth is None:
                self._summary_p_depth = self._p_depth

    def handle_endtag(self, tag: str) -> None:
        if tag == "p":
            if self._summary_p_depth is not None and self._p_depth == self._summary_p_depth:
                self._summary_p_depth = None
            self._p_depth -= 1
        elif tag == "div":
            if self._body_div_depth is not None and self._div_depth == self._body_div_depth:
                self._body_div_depth = None
            self._div_depth -= 1
        elif tag == "h4":
            if self._title_h4_depth is not None and self._h4_depth == self._title_h4_depth:
                self._title_h4_depth = None
            self._h4_depth -= 1
        elif tag == "a":
            if self._card_a_depth is not None and self._a_depth == self._card_a_depth:
                title = "".join(self._title_parts).strip()
                if title and self._card_href:
                    summary = "".join(self._summary_parts).strip() or None
                    self.articles.append(
                        IBArticle(
                            title=title,
                            url=self._card_href,
                            published_at=None,
                            summary=summary,
                        )
                    )
                self._card_a_depth = None
                self._card_href = None
            self._a_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._title_h4_depth is not None:
            self._title_parts.append(data)
        if self._summary_p_depth is not None:
            self._summary_parts.append(data)


def parse_bofa_insights_index(
    html_text: str, base_url: str = "https://business.bofa.com"
) -> list[IBArticle]:
    parser = _BofAInsightsParser()
    parser.feed(html_text)
    articles = [
        IBArticle(a.title, _absolutize(a.url, base_url), a.published_at, a.summary)
        for a in parser.articles
    ]
    return _dedupe_by_url(articles)


# --- Citigroup (citigroup.com/global/insights, "Citi Institute") -------------
# Cards are `<article data-id="gpa-card">` wrapping a title `<h3 class="...title...">`,
# a summary `<p class="Summary ...">` (which itself malformedly nests a bare `<p>`, hence
# the depth tracking rather than a flat start/end pair), and eventually an `<a href>` -
# the anchor comes *after* the text content here, unlike GS/BofA where it wraps everything.
# No reliable per-card publish date is exposed.


class _CitiInsightsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._article_depth = 0
        self._card_article_depth: int | None = None
        self._h3_depth = 0
        self._title_h3_depth: int | None = None
        self._p_depth = 0
        self._summary_p_depth: int | None = None
        self._title_parts: list[str] = []
        self._summary_parts: list[str] = []
        self._href_captured = False

        self.articles: list[IBArticle] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = [c.lower() for c in (attrs_dict.get("class") or "").split()]
        if tag == "article":
            self._article_depth += 1
            if self._card_article_depth is None and attrs_dict.get("data-id") == "gpa-card":
                self._card_article_depth = self._article_depth
                self._title_parts = []
                self._summary_parts = []
                self._href_captured = False
        elif tag == "h3":
            self._h3_depth += 1
            if (
                self._card_article_depth is not None
                and self._title_h3_depth is None
                and any("title" in c for c in classes)
            ):
                self._title_h3_depth = self._h3_depth
        elif tag == "p":
            self._p_depth += 1
            if (
                self._card_article_depth is not None
                and self._summary_p_depth is None
                and any("summary" in c for c in classes)
            ):
                self._summary_p_depth = self._p_depth
        elif tag == "a":
            href = attrs_dict.get("href")
            if self._card_article_depth is not None and not self._href_captured and href:
                title = "".join(self._title_parts).strip()
                if title:
                    self.articles.append(
                        IBArticle(
                            title=title,
                            url=href,
                            published_at=None,
                            summary="".join(self._summary_parts).strip() or None,
                        )
                    )
                self._href_captured = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3":
            if self._title_h3_depth is not None and self._h3_depth == self._title_h3_depth:
                self._title_h3_depth = None
            self._h3_depth -= 1
        elif tag == "p":
            if self._summary_p_depth is not None and self._p_depth == self._summary_p_depth:
                self._summary_p_depth = None
            self._p_depth -= 1
        elif tag == "article":
            if (
                self._card_article_depth is not None
                and self._article_depth == self._card_article_depth
            ):
                self._card_article_depth = None
            self._article_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._title_h3_depth is not None:
            self._title_parts.append(data)
        if self._summary_p_depth is not None:
            self._summary_parts.append(data)


def parse_citi_insights_index(
    html_text: str, base_url: str = "https://www.citigroup.com"
) -> list[IBArticle]:
    parser = _CitiInsightsParser()
    parser.feed(html_text)
    articles = [
        IBArticle(a.title, _absolutize(a.url, base_url), a.published_at, a.summary)
        for a in parser.articles
    ]
    return _dedupe_by_url(articles)


# --- BlackRock (blackrock.com/us/individual/insights) -------------------------
# Cards are `<a class="... article-wrapper-link ..." href="..." title="...">` - the title is
# the attribute value directly, no nested text to walk. Inside: an `<div class="attribution-text
# date">` wrapping the first publish-date `<span>`, and a `<div class="description">` teaser.


class _BlackRockInsightsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._a_depth = 0
        self._card_a_depth: int | None = None
        self._card_href: str | None = None
        self._card_title: str | None = None
        self._div_depth = 0
        self._attribution_div_depth: int | None = None
        self._description_div_depth: int | None = None
        self._span_depth = 0
        self._date_span_depth: int | None = None
        self._date_span_done = False
        self._date_parts: list[str] = []
        self._summary_parts: list[str] = []

        self.articles: list[IBArticle] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = (attrs_dict.get("class") or "").split()
        href = attrs_dict.get("href")
        title = attrs_dict.get("title")
        if tag == "a":
            self._a_depth += 1
            if (
                self._card_a_depth is None
                and "article-wrapper-link" in classes
                and href
                and title
            ):
                self._card_a_depth = self._a_depth
                self._card_href = href
                self._card_title = title
                self._attribution_div_depth = None
                self._description_div_depth = None
                self._date_span_done = False
                self._date_parts = []
                self._summary_parts = []
        elif tag == "div":
            self._div_depth += 1
            if self._card_a_depth is not None:
                if self._attribution_div_depth is None and "attribution-text" in classes:
                    self._attribution_div_depth = self._div_depth
                if self._description_div_depth is None and "description" in classes:
                    self._description_div_depth = self._div_depth
        elif tag == "span":
            self._span_depth += 1
            if (
                self._attribution_div_depth is not None
                and not self._date_span_done
                and self._date_span_depth is None
            ):
                self._date_span_depth = self._span_depth

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            if self._date_span_depth is not None and self._span_depth == self._date_span_depth:
                self._date_span_depth = None
                self._date_span_done = True
            self._span_depth -= 1
        elif tag == "div":
            if (
                self._attribution_div_depth is not None
                and self._div_depth == self._attribution_div_depth
            ):
                self._attribution_div_depth = None
            if (
                self._description_div_depth is not None
                and self._div_depth == self._description_div_depth
            ):
                self._description_div_depth = None
            self._div_depth -= 1
        elif tag == "a":
            if self._card_a_depth is not None and self._a_depth == self._card_a_depth:
                if self._card_title and self._card_href:
                    self.articles.append(
                        IBArticle(
                            title=self._card_title.strip(),
                            url=self._card_href,
                            published_at=_parse_mon_dd_yyyy("".join(self._date_parts)),
                            summary="".join(self._summary_parts).strip() or None,
                        )
                    )
                self._card_a_depth = None
                self._card_href = None
                self._card_title = None
            self._a_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._date_span_depth is not None:
            self._date_parts.append(data)
        if self._description_div_depth is not None:
            self._summary_parts.append(data)


def parse_blackrock_insights_index(
    html_text: str, base_url: str = "https://www.blackrock.com"
) -> list[IBArticle]:
    parser = _BlackRockInsightsParser()
    parser.feed(html_text)
    articles = [
        IBArticle(a.title, _absolutize(a.url, base_url), a.published_at, a.summary)
        for a in parser.articles
    ]
    return _dedupe_by_url(articles)


# --- Vanguard (investor.vanguard.com/investor-resources-education) -----------
# Cards use a stable `cmp-articlecard-*` class family from Vanguard's CMS component. The
# title is the `<a class="cmp-articlecard-content__link" title="...">` attribute value, but
# the description `<div>` is a *sibling* after the anchor closes, not nested inside it - so
# this tracks state across the flat tag sequence like the JPMorgan parser, not by nesting.


class _VanguardInsightsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.articles: list[IBArticle] = []
        self._pending_url: str | None = None
        self._pending_title: str | None = None
        self._capturing_summary = False
        self._pending_summary_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = (attrs_dict.get("class") or "").split()
        href = attrs_dict.get("href")
        title = attrs_dict.get("title")
        if tag == "a" and "cmp-articlecard-content__link" in classes and href and title:
            self._flush()
            self._pending_url = href
            self._pending_title = title
        elif (
            tag == "div"
            and self._pending_url is not None
            and "cmp-articlecard-content__description" in classes
        ):
            self._capturing_summary = True
            self._pending_summary_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._capturing_summary:
            self._capturing_summary = False

    def handle_data(self, data: str) -> None:
        if self._capturing_summary:
            self._pending_summary_parts.append(data)

    def _flush(self) -> None:
        if self._pending_url and self._pending_title:
            self.articles.append(
                IBArticle(
                    title=self._pending_title.strip(),
                    url=self._pending_url,
                    published_at=None,
                    summary="".join(self._pending_summary_parts).strip() or None,
                )
            )
        self._pending_url = None
        self._pending_title = None
        self._capturing_summary = False
        self._pending_summary_parts = []

    def close(self) -> None:
        self._flush()
        super().close()


def parse_vanguard_insights_index(
    html_text: str, base_url: str = "https://investor.vanguard.com"
) -> list[IBArticle]:
    parser = _VanguardInsightsParser()
    parser.feed(html_text)
    parser.close()
    articles = [
        IBArticle(a.title, _absolutize(a.url, base_url), a.published_at, a.summary)
        for a in parser.articles
    ]
    return _dedupe_by_url(articles)


# --- PDF link finders ---------------------------------------------------------
# Some banks attach the actual report as a PDF on the article detail page rather than
# publishing the full text as HTML. These scan a fetched detail page for a link to that PDF;
# the collector downloads and extracts it as the document body when one is found.

_PDF_HREF_RE = re.compile(r'href="([^"]*\.pdf[^"]*)"', re.IGNORECASE)


def find_pdf_href(detail_html: str, base_url: str) -> str | None:
    """Matches a direct `<a href="...something.pdf">` link (BofA, BlackRock)."""
    match = _PDF_HREF_RE.search(detail_html)
    if match is None:
        return None
    return _absolutize(match.group(1), base_url)


_CITI_DOWNLOAD_LINK_RE = re.compile(r'"buttonLink":"(https://ir\.citi\.com/[^"]+)"')


def find_citi_pdf_link(detail_html: str, base_url: str) -> str | None:
    """Citi's "Download Here" CTA links to an ir.citi.com redirect, not a literal .pdf URL -
    the collector must fetch it and check the response Content-Type to confirm it's a PDF."""
    match = _CITI_DOWNLOAD_LINK_RE.search(detail_html)
    return match.group(1) if match else None


# --- Berkshire Hathaway (berkshirehathaway.com/letters/letters.html) ----------
# Plain hand-written HTML (no CMS). Each year is a single `<a href="...">YYYY</a>`; from 2004
# onward the href is a direct PDF (`2024ltr.pdf`), before that it's a same-site HTML page
# (`1998.html`). Only the PDF-era (2004+) is supported - the pre-2004 pages are themselves the
# full letter text rather than a listing-with-attached-PDF, which is a different capture shape
# (see EssayCollector) that this registry doesn't handle; 20+ years of letters is still deep
# coverage.

_BERKSHIRE_LETTER_RE = re.compile(r'<a\s+href="(\d{4})ltr\.pdf">\s*\d{4}\s*</a>', re.IGNORECASE)


def parse_berkshire_letters_index(
    html_text: str, base_url: str = "https://www.berkshirehathaway.com/letters"
) -> list[IBArticle]:
    articles = [
        IBArticle(
            title=f"Berkshire Hathaway {year} Shareholder Letter",
            url=_absolutize(f"{year}ltr.pdf", f"{base_url}/"),
            published_at=None,
            summary=None,
            pdf_url=_absolutize(f"{year}ltr.pdf", f"{base_url}/"),
        )
        for year in sorted(
            {m.group(1) for m in _BERKSHIRE_LETTER_RE.finditer(html_text)}, reverse=True
        )
    ]
    return _dedupe_by_url(articles)


# --- Oaktree Capital memos (oaktreecapital.com/insights/memos) ----------------
# Each card is a `<time datetime="...">` immediately followed by
# `<a class="oc-title-link" href="/insights/memo/{slug}">{Title}</a>`. The listing has no PDF
# link - the memo's own detail page does (see find_oaktree_pdf_link).

_OAKTREE_CARD_RE = re.compile(
    r'<time[^>]*datetime="[^"]*?(\d{4}-\d{2}-\d{2})[^"]*"[^>]*>.*?</time>\s*'
    r'<a class="oc-title-link" href="([^"]+)">([^<]+)</a>',
    re.DOTALL,
)


def parse_oaktree_memos_index(
    html_text: str, base_url: str = "https://www.oaktreecapital.com"
) -> list[IBArticle]:
    articles = [
        IBArticle(
            title=title.strip(),
            url=_absolutize(href, base_url),
            published_at=datetime.strptime(date_str, "%Y-%m-%d").date(),
            summary=None,
        )
        for date_str, href, title in _OAKTREE_CARD_RE.findall(html_text)
    ]
    return _dedupe_by_url(articles)


_OAKTREE_PDF_RE = re.compile(r"openPDF\('([^']*)',\s*'(https://[^']*\.pdf[^']*)'\)")
_OAKTREE_TRANSLATED_SUFFIX_RE = re.compile(r"_(JPN|KRN|SC|TC)$")


def find_oaktree_pdf_link(detail_html: str, base_url: str) -> str | None:
    """Memo pages offer the English original plus several translated PDFs via
    `openPDF('<label>', '<url>')` calls (not real hrefs). Picks the first entry whose label
    isn't a translated-language suffix."""
    for label, url in _OAKTREE_PDF_RE.findall(detail_html):
        if not _OAKTREE_TRANSLATED_SUFFIX_RE.search(label):
            return url
    return None


# --- Pershing Square Holdings (pershingsquareholdings.com/materials/) ---------
# A single flat page listing every published document as
# `<li class="materials--list--item ...">` with date/description/category/link spans already
# inline - no detail-page fetch needed. Filtered to the "Letters & Presentations" category and
# descriptions naming a shareholder letter, since the same page also lists fact sheets,
# investor-presentation slides, and shareholder notices that aren't letters.

_PSH_ITEM_RE = re.compile(
    r'<li class="materials--list--item[^"]*">'
    r'<span class="materials--list--item--date">([^<]+)</span>'
    r'<span class="materials--list--item--description">([^<]+)</span>'
    r'<span class="materials--list--item--category">([^<]+)</span>'
    r'<span class="materials--list--item--link"><a href="([^"]+)"',
    re.IGNORECASE,
)


def parse_pershing_square_letters_index(
    html_text: str, base_url: str = "https://pershingsquareholdings.com"
) -> list[IBArticle]:
    articles = []
    for date_str, description, category, href in _PSH_ITEM_RE.findall(html_text):
        if "letter" not in description.lower() and "letters" not in category.lower():
            continue
        try:
            published_at = datetime.strptime(date_str.strip(), "%B %d, %Y").date()
        except ValueError:
            published_at = None
        pdf_url = _absolutize(href, base_url)
        articles.append(
            IBArticle(
                title=description.strip(),
                url=pdf_url,
                published_at=published_at,
                summary=None,
                pdf_url=pdf_url,
            )
        )
    return _dedupe_by_url(articles)

