import httpx
import pytest
import respx

from investor_intel.collectors.sec_client import SECClient, SECClientError


def test_empty_user_agent_raises() -> None:
    with pytest.raises(ValueError):
        SECClient(user_agent="")


@respx.mock
def test_get_json_sends_user_agent_header() -> None:
    route = respx.get("https://data.sec.gov/test.json").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = SECClient(user_agent="Investor Intel test@example.com")
    result = client.get_json("https://data.sec.gov/test.json")
    client.close()

    assert result == {"ok": True}
    assert route.calls.last.request.headers["User-Agent"] == "Investor Intel test@example.com"


@respx.mock
def test_get_text_retries_on_429_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    route = respx.get("https://www.sec.gov/test.xml").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, text="<root/>"),
        ]
    )
    client = SECClient(user_agent="Investor Intel test@example.com")
    result = client.get_text("https://www.sec.gov/test.xml")
    client.close()

    assert result == "<root/>"
    assert route.call_count == 2


@respx.mock
def test_persistent_429_raises_after_max_retries(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    respx.get("https://www.sec.gov/always429.xml").mock(return_value=httpx.Response(429))
    client = SECClient(user_agent="Investor Intel test@example.com")
    with pytest.raises(SECClientError):
        client.get_text("https://www.sec.gov/always429.xml")
    client.close()


@respx.mock
def test_rate_limiter_acquire_called_per_request() -> None:
    calls: list[None] = []

    class SpyRateLimiter:
        def acquire(self) -> None:
            calls.append(None)

    respx.get("https://data.sec.gov/spy.json").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = SECClient(user_agent="Investor Intel test@example.com", rate_limiter=SpyRateLimiter())
    client.get_json("https://data.sec.gov/spy.json")
    client.close()

    assert len(calls) == 1
