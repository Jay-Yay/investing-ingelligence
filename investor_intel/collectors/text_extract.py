from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

MAX_FULL_TEXT_CHARS = 40_000


def strip_markup(raw: str) -> str:
    """HTML/XML 태그를 제거하고 공백을 정규화한다.

    표(TABLE/TR/TD 등)의 구조를 그대로 보존하지 않는 단순 정규식 기반 변환이다 - DART/SEC 원문
    전체를 완벽히 구조화된 마크다운으로 바꾸는 건 이번 범위 밖이고, claim 추출용 텍스트를 뽑아내는
    데는 충분하다.
    """
    text = _TAG_RE.sub(" ", raw)
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
