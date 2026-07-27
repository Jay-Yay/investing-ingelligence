from types import SimpleNamespace

import pytest
from freezegun import freeze_time

from investor_intel.collectors.web_research import WebResearchError, collect_web_research
from investor_intel.llm.client import AnthropicClient


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeAnthropic:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _text_response(text: str):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=120, output_tokens=80),
    )


@freeze_time("2026-07-27T09:00:00+00:00")
def test_collect_web_research_wraps_text_response_as_single_item() -> None:
    fake = _FakeAnthropic(
        _text_response(
            "- [기사 제목](https://example.com/a) — 출처, 2026-07-26\n  인용 문장"
        )
    )
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)

    result, input_tokens, output_tokens = collect_web_research(client, "NBIS", "Nebius Group")

    assert result.success is True
    assert result.errors == []
    assert len(result.items) == 1
    item = result.items[0]
    assert item.source_specific_id == "NBIS-2026-07-27"
    assert item.canonical_url == "web-search://NBIS/2026-07-27"
    assert "기사 제목" in item.body_text
    assert item.document_type == "web_search_digest"
    assert item.content_capture_mode == "full"
    assert input_tokens == 120
    assert output_tokens == 80


def test_collect_web_research_sends_web_search_tool_and_query() -> None:
    fake = _FakeAnthropic(_text_response("검색 결과 없음"))
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)

    collect_web_research(client, "NBIS", "Nebius Group")

    call = fake.messages.calls[0]
    assert call["tools"] == [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
    ]
    assert call["messages"][0]["content"] == "NBIS Nebius Group 최근 뉴스"


def test_collect_web_research_raises_when_no_text_block_present() -> None:
    fake = _FakeAnthropic(
        SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input={})],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
    )
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)

    with pytest.raises(WebResearchError):
        collect_web_research(client, "NBIS", "Nebius Group")
