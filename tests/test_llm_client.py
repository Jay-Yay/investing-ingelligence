import pytest

from investor_intel.llm.client import AnthropicClient


class _FakeMessages:
    def __init__(self):
        self.calls = []
        self.response = {"ok": True}

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeAnthropic:
    def __init__(self):
        self.messages = _FakeMessages()


def test_empty_api_key_raises() -> None:
    with pytest.raises(ValueError):
        AnthropicClient(api_key="", model="claude-sonnet-5")


def test_model_property_reflects_constructor_arg() -> None:
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=_FakeAnthropic())
    assert client.model == "claude-sonnet-5"


def test_create_message_forwards_args_and_returns_result() -> None:
    fake = _FakeAnthropic()
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)

    result = client.create_message(
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"name": "x"}],
        tool_choice={"type": "tool", "name": "x"},
        max_tokens=2048,
    )

    assert result == {"ok": True}
    assert len(fake.messages.calls) == 1
    call = fake.messages.calls[0]
    assert call["model"] == "claude-sonnet-5"
    assert call["system"] == "You are a helpful assistant."
    assert call["messages"] == [{"role": "user", "content": "hello"}]
    assert call["tools"] == [{"name": "x"}]
    assert call["tool_choice"] == {"type": "tool", "name": "x"}
    assert call["max_tokens"] == 2048


def test_create_message_omits_tools_when_not_provided() -> None:
    fake = _FakeAnthropic()
    client = AnthropicClient(api_key="test-key", model="claude-sonnet-5", client=fake)

    client.create_message(system="sys", messages=[{"role": "user", "content": "hi"}])

    call = fake.messages.calls[0]
    assert "tools" not in call
    assert "tool_choice" not in call
