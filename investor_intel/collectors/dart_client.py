from __future__ import annotations

import time
from typing import Protocol

import httpx

from investor_intel.collectors.base import RateLimiter

_MAX_RETRIES = 3
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class DartClientError(Exception):
    pass


class _RateLimiterProtocol(Protocol):
    def acquire(self) -> None: ...


class DartClient:
    def __init__(
        self,
        api_key: str,
        rate_limiter: _RateLimiterProtocol | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenDART requires an API key")
        self._api_key = api_key
        self._rate_limiter: _RateLimiterProtocol = rate_limiter or RateLimiter(max_per_second=2.0)
        self._client = http_client or httpx.Client(timeout=30.0)

    def _request(self, url: str) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            self._rate_limiter.acquire()
            response = self._client.get(url)
            if response.status_code not in _RETRY_STATUS_CODES:
                response.raise_for_status()
                return response
            last_exc = DartClientError(
                f"OpenDART request to {url} failed with status {response.status_code}"
            )
            if attempt < _MAX_RETRIES:
                time.sleep(2 ** (attempt - 1))
        assert last_exc is not None
        raise last_exc

    def get_json(self, url: str) -> dict:
        return self._request(url).json()

    def get_bytes(self, url: str) -> bytes:
        return self._request(url).content

    def close(self) -> None:
        self._client.close()
