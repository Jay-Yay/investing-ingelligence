from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from telethon import TelegramClient
from telethon.errors.rpcerrorlist import FloodWaitError
from telethon.sessions import StringSession

_MAX_FLOOD_WAIT_SECONDS = 60


@dataclass
class TelethonMessage:
    id: int
    text: str
    date: datetime


class TelethonClientProtocol(Protocol):
    def iter_messages(self, entity: str, limit: int) -> AsyncIterator[TelethonMessage]: ...


class RealTelethonClient:
    """Thin wrapper around telethon.TelegramClient - exposes only what this project needs."""

    def __init__(self, session: str, api_id: int, api_hash: str) -> None:
        self._client = TelegramClient(StringSession(session), api_id, api_hash)

    async def iter_messages(self, entity: str, limit: int) -> AsyncIterator[TelethonMessage]:
        async with self._client:
            try:
                async for message in self._client.iter_messages(entity, limit=limit):
                    text = message.raw_text or ""
                    if not text:
                        continue
                    yield TelethonMessage(id=message.id, text=text, date=message.date)
            except FloodWaitError as exc:
                if exc.seconds > _MAX_FLOOD_WAIT_SECONDS:
                    raise
                await asyncio.sleep(exc.seconds)
                async for message in self._client.iter_messages(entity, limit=limit):
                    text = message.raw_text or ""
                    if not text:
                        continue
                    yield TelethonMessage(id=message.id, text=text, date=message.date)
