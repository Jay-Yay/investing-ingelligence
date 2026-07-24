from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

_VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


@dataclass
class EssayPage:
    title: str
    body_text: str


@dataclass
class _PendingParagraph:
    parts: list[str] = field(default_factory=list)


class _EssayHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[str] = []
        self._entry_title_open_depth: int | None = None
        self._entry_content_open_depth: int | None = None
        self._in_title_tag = False
        self._in_script_or_style = False
        self._active_paragraph: _PendingParagraph | None = None

        self.entry_title_parts: list[str] = []
        self.doc_title_parts: list[str] = []
        self.entry_content_paragraphs: list[str] = []
        self.fallback_paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = (attrs_dict.get("class") or "").split()

        if tag not in _VOID_ELEMENTS:
            self._stack.append(tag)
        depth = len(self._stack)

        if tag in ("script", "style"):
            self._in_script_or_style = True
        if tag == "title":
            self._in_title_tag = True
        if "entry-title" in classes and self._entry_title_open_depth is None:
            self._entry_title_open_depth = depth
        if "entry-content" in classes and self._entry_content_open_depth is None:
            self._entry_content_open_depth = depth
        if tag == "p":
            self._active_paragraph = _PendingParagraph()

    def handle_endtag(self, tag: str) -> None:
        depth = len(self._stack)

        if self._entry_title_open_depth is not None and depth == self._entry_title_open_depth:
            self._entry_title_open_depth = None
        if self._entry_content_open_depth is not None and depth == self._entry_content_open_depth:
            self._entry_content_open_depth = None

        if tag == "p" and self._active_paragraph is not None:
            text = "".join(self._active_paragraph.parts).strip()
            if text:
                if self._entry_content_open_depth is not None:
                    self.entry_content_paragraphs.append(text)
                else:
                    self.fallback_paragraphs.append(text)
            self._active_paragraph = None

        if tag in ("script", "style"):
            self._in_script_or_style = False
        if tag == "title":
            self._in_title_tag = False

        if tag not in _VOID_ELEMENTS and self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_script_or_style:
            return
        if self._in_title_tag:
            self.doc_title_parts.append(data)
        if self._entry_title_open_depth is not None:
            self.entry_title_parts.append(data)
        if self._active_paragraph is not None:
            self._active_paragraph.parts.append(data)


def parse_essay_html(html_text: str) -> EssayPage:
    parser = _EssayHTMLParser()
    parser.feed(html_text)

    entry_title = "".join(parser.entry_title_parts).strip()
    doc_title = "".join(parser.doc_title_parts).strip()
    title = entry_title or doc_title or "(제목 없음)"

    paragraphs = parser.entry_content_paragraphs or parser.fallback_paragraphs
    body_text = "\n\n".join(paragraphs)

    return EssayPage(title=title, body_text=body_text)
