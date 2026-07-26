from types import SimpleNamespace

import pytest

from investor_intel.llm.daily_report import DailyReportError, synthesize_daily_narrative


class _FakeClient:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def create_message(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def test_returns_text_block_content() -> None:
    text_block = SimpleNamespace(type="text", text="오늘의 요약입니다.")
    usage = SimpleNamespace(input_tokens=120, output_tokens=80)
    client = _FakeClient(SimpleNamespace(content=[text_block], usage=usage))
    outcome = synthesize_daily_narrative(
        client, summary="원시 데이터 요약", system_prompt="시스템 프롬프트"
    )

    assert outcome.text == "오늘의 요약입니다."
    assert outcome.usage.input_tokens == 120
    assert outcome.usage.output_tokens == 80
    assert len(client.calls) == 1
    assert client.calls[0]["system"] == "시스템 프롬프트"


def test_raises_when_no_text_block() -> None:
    usage = SimpleNamespace(input_tokens=10, output_tokens=5)
    client = _FakeClient(
        SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={})], usage=usage)
    )
    with pytest.raises(DailyReportError):
        synthesize_daily_narrative(
            client, summary="원시 데이터 요약", system_prompt="시스템 프롬프트"
        )
