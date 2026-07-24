# RealTelethonClient itself is a thin pass-through over the real `telethon.TelegramClient` and
# is intentionally NOT exercised here with live network calls - see phase 18's plan doc
# self-review for why (MTProto isn't curl-able, and a real session requires an interactive
# phone/OTP login this environment cannot perform). These tests only cover the pure, in-repo
# parts: the dataclass shape and that a fake implementing the Protocol satisfies it structurally.

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from investor_intel.collectors.telethon_client import TelethonClientProtocol, TelethonMessage


class _FakeTelethonClient:
    def __init__(self, messages: list[TelethonMessage]) -> None:
        self._messages = messages

    async def iter_messages(self, entity: str, limit: int) -> AsyncIterator[TelethonMessage]:
        for message in self._messages[:limit]:
            yield message


def test_telethon_message_holds_id_text_and_date() -> None:
    message = TelethonMessage(id=42, text="hello", date=datetime(2026, 7, 24, tzinfo=UTC))
    assert message.id == 42
    assert message.text == "hello"
    assert message.date.tzinfo is not None


async def _collect(
    client: TelethonClientProtocol, entity: str, limit: int
) -> list[TelethonMessage]:
    return [message async for message in client.iter_messages(entity, limit)]


def test_fake_client_satisfies_protocol_and_respects_limit() -> None:
    import asyncio

    messages = [
        TelethonMessage(id=i, text=f"msg {i}", date=datetime(2026, 7, 24, tzinfo=UTC))
        for i in range(5)
    ]
    fake: TelethonClientProtocol = _FakeTelethonClient(messages)

    result = asyncio.run(_collect(fake, "somechannel", limit=3))
    assert len(result) == 3
    assert [m.id for m in result] == [0, 1, 2]
