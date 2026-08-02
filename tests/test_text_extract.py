from investor_intel.collectors.text_extract import strip_markup, truncate


def test_strip_markup_removes_tags_and_normalizes_whitespace() -> None:
    raw = "<DOCUMENT><TITLE>제목</TITLE><P>본문   내용</P>\n\n\n\n<P>둘째 단락</P></DOCUMENT>"
    result = strip_markup(raw)
    assert "<" not in result
    assert ">" not in result
    assert "제목" in result
    assert "본문 내용" in result
    assert "\n\n\n" not in result


def test_strip_markup_unescapes_common_entities() -> None:
    result = strip_markup("A &amp; B &nbsp; C")
    assert result == "A & B C"


def test_strip_markup_unescapes_numeric_character_references() -> None:
    """SEC 필링은 &nbsp;/&amp;/&lt;/&gt; 네 개만으로는 커버 안 되는 &#160;(nbsp)/&#8217;(’)/
    &#9746;(☒)/&#58;(:) 같은 숫자 문자 참조를 광범위하게 쓴다 - 이전 버전(4개 named entity만
    수동 치환)은 이런 코드를 그대로 남겨 원문이 깨져 보이게 했다(AMZN 10-Q 실사례).
    """
    raw = "Amazon.com, Inc. (NASDAQ&#58; AMZN)&#160;&#9746; registrant&#8217;s offices"
    result = strip_markup(raw)
    assert "&#" not in result
    assert "Amazon.com, Inc. (NASDAQ: AMZN) ☒ registrant’s offices" == result


def test_truncate_returns_unchanged_text_under_limit() -> None:
    text = "짧은 텍스트"
    assert truncate(text, max_chars=100) == text


def test_truncate_cuts_and_appends_notice_over_limit() -> None:
    text = "가" * 100
    result = truncate(text, max_chars=40)
    assert result.startswith("가" * 40)
    assert "생략" in result
    assert "100" in result and "40" in result
