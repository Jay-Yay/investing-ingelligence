from __future__ import annotations

from typing import Any, Protocol

import anthropic


class _MessagesProtocol(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _AnthropicClientProtocol(Protocol):
    messages: _MessagesProtocol


class AnthropicClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        client: _AnthropicClientProtocol | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Anthropic API key is required")
        self.model = model
        self._client = client or anthropic.Anthropic(api_key=api_key)

    def create_message(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        max_tokens: int = 4096,
    ) -> Any:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        return self._client.messages.create(**kwargs)
