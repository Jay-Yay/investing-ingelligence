from __future__ import annotations

import re

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

MAX_FULL_TEXT_CHARS = 40_000


def strip_markup(raw: str) -> str:
    """HTML/XML 태그를 제거하고 공백을 정규화한다.

    표(TABLE/TR/TD 등) 구조는 이 함수가 처리하지 않는다 - 호출부가 먼저
    `table_markdown.convert_tables_to_markdown`으로 표를 마크다운으로 바꿔둔 뒤 이 함수에
    넘기는 것을 전제로 한다. <script>/<style> 태그는 내용까지 통째로 제거한다(태그만 벗기면
    내부 CSS/JS 텍스트가 그대로 새어나온다).
    """
    text = _SCRIPT_STYLE_RE.sub(" ", raw)
    text = _TAG_RE.sub(" ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace(
        "&gt;", ">"
    )
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def truncate(text: str, max_chars: int = MAX_FULL_TEXT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars].rstrip()
        + f"\n\n[...이하 생략, 원문 총 {len(text):,}자 중 {max_chars:,}자까지만 캡처됨. "
        "전체 원문은 출처 링크 참고...]"
    )
