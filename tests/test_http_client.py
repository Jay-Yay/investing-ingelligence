import httpx
import respx

from investor_intel.collectors.http_client import HttpClientError, SimpleHttpClient


@respx.mock
def test_get_text_returns_body() -> None:
    respx.get("https://example.com/test.xml").mock(
        return_value=httpx.Response(200, text="<root/>")
    )
    client = SimpleHttpClient()
    result = client.get_text("https://example.com/test.xml")
    client.close()

    assert result == "<root/>"


@respx.mock
def test_get_text_retries_on_429_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    route = respx.get("https://example.com/retry.xml").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, text="ok"),
        ]
    )
    client = SimpleHttpClient()
    result = client.get_text("https://example.com/retry.xml")
    client.close()

    assert result == "ok"
    assert route.call_count == 2


@respx.mock
def test_persistent_5xx_raises_after_max_retries(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    respx.get("https://example.com/always500.xml").mock(return_value=httpx.Response(500))
    client = SimpleHttpClient()
    try:
        client.get_text("https://example.com/always500.xml")
        raise AssertionError("expected HttpClientError")
    except HttpClientError:
        pass
    finally:
        client.close()


@respx.mock
def test_rate_limiter_acquire_called_per_request() -> None:
    calls: list[None] = []

    class SpyRateLimiter:
        def acquire(self) -> None:
            calls.append(None)

    respx.get("https://example.com/spy.xml").mock(return_value=httpx.Response(200, text="ok"))
    client = SimpleHttpClient(rate_limiter=SpyRateLimiter())
    client.get_text("https://example.com/spy.xml")
    client.close()

    assert len(calls) == 1


@respx.mock
def test_sends_configured_user_agent() -> None:
    route = respx.get("https://example.com/ua.xml").mock(
        return_value=httpx.Response(200, text="ok")
    )
    client = SimpleHttpClient(user_agent="Investor Intel/0.1")
    client.get_text("https://example.com/ua.xml")
    client.close()

    assert route.calls.last.request.headers["User-Agent"] == "Investor Intel/0.1"
