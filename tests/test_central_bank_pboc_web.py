from types import SimpleNamespace

import pytest
from freezegun import freeze_time

from investor_intel.collectors.central_bank_pboc_web import (
    PbocMpcWebError,
    collect_pboc_mpc_web,
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
        usage=SimpleNamespace(input_tokens=400, output_tokens=200),
    )


@freeze_time("2026-07-27T09:00:00+00:00")
def test_collect_pboc_mpc_web_returns_item_when_communique_found() -> None:
    fake = _FakeAnthropic(
        _text_response(
            "## 회의 개요\n- 2026년 2분기 정례회의\n\n"
            "## 통화정책 기조 핵심 문구\n- 稳健的货币政策\n\n"
            "## 경기 판단\n- 내수 회복세\n\n"
            "출처: [PBOC](https://pbc.gov.cn/example)"
        )
    )
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)

    result, input_tokens, output_tokens = collect_pboc_mpc_web(client, "2026Q2")

    assert result is not None
    assert result.success is True
    (item,) = result.items
    assert item.source_specific_id == "pboc-mpc-2026Q2"
    assert item.document_type == "central_bank_minutes"
    assert item.themes == ["macro", "central_bank", "CN"]
    assert item.reporting_period == "2026Q2"
    assert item.content_capture_mode == "excerpt"
    assert input_tokens == 400
    assert output_tokens == 200


def test_collect_pboc_mpc_web_returns_none_when_not_found() -> None:
    fake = _FakeAnthropic(_text_response("공보 찾지 못함"))
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)

    result, input_tokens, output_tokens = collect_pboc_mpc_web(client, "2026Q2")

    assert result is None
    assert input_tokens == 400
    assert output_tokens == 200


def test_collect_pboc_mpc_web_raises_on_empty_response() -> None:
    fake = _FakeAnthropic(_text_response(""))
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)

    with pytest.raises(PbocMpcWebError):
        collect_pboc_mpc_web(client, "2026Q2")
