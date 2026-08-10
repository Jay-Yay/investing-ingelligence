from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol

import anthropic


class _MessagesProtocol(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _AnthropicClientProtocol(Protocol):
    messages: _MessagesProtocol


class _BatchesProtocol(Protocol):
    """`messages.batches`의 최소 인터페이스.

    `_MessagesProtocol`에 넣지 않고 따로 둔다 - 배치를 안 쓰는 기존 테스트 가짜 클라이언트가
    `batches` 속성 없이도 유효하게 남도록 하기 위함이다(배치 경로에서만 접근한다).
    """

    def create(self, *, requests: list[dict[str, Any]]) -> Any: ...
    def retrieve(self, batch_id: str) -> Any: ...
    def results(self, batch_id: str) -> Any: ...


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

    # --- Message Batches API ---------------------------------------------------------------
    # 야간 크론에서 vault에 기록만 하는 analyze는 지연 민감도가 0이라 배치로 돌릴 수 있고,
    # 배치는 입력/출력 토큰이 전 구간 50% 할인이다. 각 요청의 params에 model이 들어가므로
    # 한 배치에 서로 다른 모델(sonnet 소형 묶음 + haiku 대형 문서)을 섞어 보낼 수 있다.

    @property
    def _batches(self) -> _BatchesProtocol:
        return self._client.messages.batches  # type: ignore[union-attr,return-value]

    def create_batch(self, requests: list[dict[str, Any]]) -> str:
        """`{"custom_id": ..., "params": {...}}` 목록을 제출하고 batch_id를 돌려준다."""
        return self._batches.create(requests=requests).id

    def retrieve_batch(self, batch_id: str) -> Any:
        """배치 상태를 조회한다 - `processing_status`가 "ended"면 결과를 읽을 수 있다."""
        return self._batches.retrieve(batch_id)

    def batch_results(self, batch_id: str) -> Iterator[Any]:
        """배치 결과를 순회한다. **도착 순서는 보장되지 않으므로 custom_id로 매칭해야 한다.**"""
        return iter(self._batches.results(batch_id))
