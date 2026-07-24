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
    client = _FakeClient(SimpleNamespace(content=[text_block]))
    result = synthesize_daily_narrative(
        client, summary="원시 데이터 요약", system_prompt="시스템 프롬프트"
    )

    assert result == "오늘의 요약입니다."
    assert len(client.calls) == 1
    assert client.calls[0]["system"] == "시스템 프롬프트"


def test_raises_when_no_text_block() -> None:
    client = _FakeClient(SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={})]))
    with pytest.raises(DailyReportError):
        synthesize_daily_narrative(
            client, summary="원시 데이터 요약", system_prompt="시스템 프롬프트"
        )
