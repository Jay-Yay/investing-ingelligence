from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser


@dataclass
class IBArticle:
    title: str
    url: str
    published_at: date | None
    summary: str | None


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


def _parse_jpm_date(text: str) -> date | None:
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
                        published_at=_parse_jpm_date("".join(self._pending_date)),
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
