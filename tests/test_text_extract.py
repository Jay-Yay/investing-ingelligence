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


def test_truncate_returns_unchanged_text_under_limit() -> None:
    text = "짧은 텍스트"
    assert truncate(text, max_chars=100) == text


def test_truncate_cuts_and_appends_notice_over_limit() -> None:
    text = "가" * 100
    result = truncate(text, max_chars=40)
    assert result.startswith("가" * 40)
    assert "생략" in result
    assert "100" in result and "40" in result
