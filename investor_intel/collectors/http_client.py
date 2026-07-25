from __future__ import annotations

import time
from typing import Any, Protocol

import httpx

from investor_intel.collectors.base import RateLimiter

_MAX_RETRIES = 3
_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_DEFAULT_USER_AGENT = "Investor Intel/0.1"


class HttpClientError(Exception):
    pass


class _RateLimiterProtocol(Protocol):
    def acquire(self) -> None: ...


class SimpleHttpClient:
    def __init__(
        self,
        user_agent: str = _DEFAULT_USER_AGENT,
        rate_limiter: _RateLimiterProtocol | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._rate_limiter: _RateLimiterProtocol = rate_limiter or RateLimiter(max_per_second=2.0)
        self._client = http_client or httpx.Client(timeout=30.0, follow_redirects=True)

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self._user_agent}

    def _request(self, url: str) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, _MAX_RETRIES + 1):
            self._rate_limiter.acquire()
            response = self._client.get(url, headers=self._headers())
            if response.status_code not in _RETRY_STATUS_CODES:
                response.raise_for_status()
                return response
            last_exc = HttpClientError(
                f"request to {url} failed with status {response.status_code}"
            )
            if attempt < _MAX_RETRIES:
                time.sleep(2 ** (attempt - 1))
        assert last_exc is not None
        raise last_exc

    def get_text(self, url: str) -> str:
        return self._request(url).text

    def get_json(self, url: str) -> Any:
        return self._request(url).json()

    def get(self, url: str) -> httpx.Response:
        return self._request(url)

    def close(self) -> None:
        self._client.close()
