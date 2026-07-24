from pathlib import Path

from investor_intel.collectors.essay_parser import parse_essay_html

FIXTURES = Path(__file__).parent / "fixtures" / "essay"


def test_parses_wordpress_entry_title_and_content() -> None:
    html_text = (FIXTURES / "wordpress_essay.html").read_text(encoding="utf-8")
    page = parse_essay_html(html_text)

    assert page.title == "SITUATIONAL AWARENESS: The Decade Ahead"
    assert "Leopold Aschenbrenner, June 2024" in page.body_text
    assert "You can see the future first in San Francisco." in page.body_text
    assert "smarter than you or I" in page.body_text


def test_falls_back_to_title_tag_and_all_paragraphs_when_no_entry_content() -> None:
    html_text = (FIXTURES / "generic_page.html").read_text(encoding="utf-8")
    page = parse_essay_html(html_text)

    assert page.title == "A Generic Investor Note"
    assert "This site has no WordPress markup at all." in page.body_text
    assert "Fallback extraction should pick up every paragraph on the page." in page.body_text
    assert "console.log" not in page.body_text
