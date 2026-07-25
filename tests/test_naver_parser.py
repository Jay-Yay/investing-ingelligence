from pathlib import Path

from investor_intel.collectors.naver_parser import (
    extract_blog_id,
    extract_log_no,
    parse_naver_rss,
)

FIXTURES = Path(__file__).parent / "fixtures" / "naver"


def test_parses_all_items() -> None:
    xml_text = (FIXTURES / "rss_feed.xml").read_text(encoding="utf-8")
    posts = parse_naver_rss(xml_text)
    assert len(posts) == 2

    first = posts[0]
    assert first.title == "엔비디아 실적 발표 후기"
    assert first.link == "https://blog.naver.com/engineerinvestor/223456789"
    assert "엔비디아" in first.description
    assert first.guid == "https://blog.naver.com/engineerinvestor/223456789"


def test_pub_date_parses_to_tz_aware_datetime() -> None:
    xml_text = (FIXTURES / "rss_feed.xml").read_text(encoding="utf-8")
    posts = parse_naver_rss(xml_text)
    first = posts[0]
    assert first.published_at.tzinfo is not None
    assert first.published_at.isoformat() == "2024-05-01T21:00:00+09:00"


def test_extract_blog_id_from_mobile_url() -> None:
    assert extract_blog_id("https://m.blog.naver.com/engineerinvestor") == "engineerinvestor"


def test_extract_blog_id_strips_trailing_slash() -> None:
    assert extract_blog_id("https://m.blog.naver.com/engineerinvestor/") == "engineerinvestor"


def test_extract_log_no_from_plain_guid() -> None:
    assert extract_log_no("https://blog.naver.com/engineerinvestor/223456789") == "223456789"


def test_extract_log_no_strips_rss_query_string() -> None:
    link = "https://blog.naver.com/engineerinvestor/224352080433?fromRss=true&trackingCode=rss"
    assert extract_log_no(link) == "224352080433"
