from __future__ import annotations

import html
import re

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
# 블록 레벨 태그의 경계는 줄바꿈으로 살려둔다 - 그냥 태그를 공백으로 지우면(_TAG_RE) SEC
# HTML은 원래 <p>/<div>마다 있던 개행이 하나도 없이 저장돼 있는 경우가 흔해서, 문단 수십 개가
# 몽땅 한 줄로 이어붙어 7만자짜리 단일 라인이 나온다 - Obsidian이 이런 극단적으로 긴 한 줄을
# 렌더링하면서 한 글자씩 세로로 쌓아 보여주는 버그로 이어졌다(AMZN 10-Q "Guidance" 문단
# 실사례로 발견 - 표 문제가 아니라 순수 텍스트 문단이었다).
_BLOCK_BREAK_RE = re.compile(r"</?(?:p|div|li|h[1-6]|tr)\b[^>]*>|<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

MAX_FULL_TEXT_CHARS = 40_000


def strip_markup(raw: str) -> str:
    """HTML/XML 태그를 제거하고 공백을 정규화한다.

    표(TABLE/TR/TD 등) 구조는 이 함수가 처리하지 않는다 - 호출부가 먼저
    `table_markdown.convert_tables_to_markdown`으로 표를 마크다운으로 바꿔둔 뒤 이 함수에
    넘기는 것을 전제로 한다. <script>/<style> 태그는 내용까지 통째로 제거한다(태그만 벗기면
    내부 CSS/JS 텍스트가 그대로 새어나온다). <p>/<div>/<li>/<h1-6>/<tr>/<br> 경계는 태그를
    지우기 전에 줄바꿈으로 먼저 바꿔둔다 - 그냥 지우면 문단 구분이 통째로 사라져 문서 전체가
    거의 한 줄이 되고, 그 극단적으로 긴 줄을 Obsidian이 렌더링하면서 깨지는 문제가 있었다.

    HTML 엔티티는 `html.unescape`로 전부 디코딩한다(named entity는 물론 `&#160;`/`&#8217;`류
    숫자 문자 참조까지) - SEC 필링은 &nbsp;/&amp;/&lt;/&gt; 네 개만으로는 커버되지 않는
    &#160;(nbsp), &#8217;(’), &#9746;(☒), &#8212;(—) 등을 광범위하게 쓰므로, 그 넷만 수동
    치환하던 이전 버전은 원문 곳곳에 디코딩 안 된 엔티티 코드가 그대로 남아 텍스트가 깨져
    보였다(AMZN 10-Q 실사례로 발견).
    """
    text = _SCRIPT_STYLE_RE.sub(" ", raw)
    text = _BLOCK_BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
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
