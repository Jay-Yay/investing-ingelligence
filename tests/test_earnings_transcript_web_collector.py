from datetime import date
from types import SimpleNamespace

import pytest
from freezegun import freeze_time

from investor_intel.collectors.earnings_transcript_web import (
    EarningsTranscriptError,
    collect_earnings_transcript_web,
)
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
        usage=SimpleNamespace(input_tokens=500, output_tokens=300),
    )


@freeze_time("2026-07-27T09:00:00+00:00")
def test_collect_earnings_transcript_web_returns_item_when_transcript_found() -> None:
    fake = _FakeAnthropic(
        _text_response(
            "## 경영진 발언 핵심 요지\n- 매출 성장 지속\n\n"
            "## Q&A 핵심 문답\n- Q: 마진 전망은? / A: 개선 중\n\n"
            "출처: [Example](https://example.com/transcript)"
        )
    )
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)

    result, input_tokens, output_tokens = collect_earnings_transcript_web(
        client, "BE", "Bloom Energy", date(2026, 6, 30)
    )

    assert result is not None
    assert result.success is True
    assert len(result.items) == 1
    item = result.items[0]
    assert item.source_specific_id == "BE-2026-06-30"
    assert item.canonical_url == "earnings-transcript-search://BE/2026-06-30"
    assert item.title == "[컨퍼런스콜-웹서치] Bloom Energy 2026-06-30 실적발표 컨퍼런스콜"
    assert item.document_type == "earnings_call_transcript"
    assert item.content_capture_mode == "excerpt"
    assert item.content_capture_reason is not None
    assert item.reporting_period == "2026-06-30"
    assert item.companies == ["BE"]
    assert "경영진 발언" in item.body_text
    assert input_tokens == 500
    assert output_tokens == 300


def test_collect_earnings_transcript_web_returns_none_when_not_found() -> None:
    fake = _FakeAnthropic(_text_response("전문 찾지 못함"))
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)

    result, input_tokens, output_tokens = collect_earnings_transcript_web(
        client, "BE", "Bloom Energy", date(2026, 6, 30)
    )

    assert result is None
    assert input_tokens == 500
    assert output_tokens == 300


def test_collect_earnings_transcript_web_sends_web_search_tool_and_period_query() -> None:
    fake = _FakeAnthropic(_text_response("전문 찾지 못함"))
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)

    collect_earnings_transcript_web(client, "BE", "Bloom Energy", date(2026, 6, 30))

    call = fake.messages.calls[0]
    assert call["tools"] == [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
    ]
    assert "BE" in call["messages"][0]["content"]
    assert "2026-06-30" in call["messages"][0]["content"]


def test_collect_earnings_transcript_web_raises_when_no_text_block_present() -> None:
    fake = _FakeAnthropic(
        SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input={})],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
    )
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)

    with pytest.raises(EarningsTranscriptError):
        collect_earnings_transcript_web(client, "BE", "Bloom Energy", date(2026, 6, 30))
