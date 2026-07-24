import httpx
import pytest
import respx

from investor_intel.collectors.dart_client import DartClient, DartClientError


def test_empty_api_key_raises() -> None:
    with pytest.raises(ValueError):
        DartClient(api_key="")


@respx.mock
def test_get_json_returns_parsed_body() -> None:
    respx.get("https://opendart.fss.or.kr/api/test.json").mock(
        return_value=httpx.Response(200, json={"status": "000"})
    )
    client = DartClient(api_key="test-key")
    result = client.get_json("https://opendart.fss.or.kr/api/test.json")
    client.close()

    assert result == {"status": "000"}


@respx.mock
def test_get_json_retries_on_429_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    route = respx.get("https://opendart.fss.or.kr/api/retry.json").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json={"status": "000"}),
        ]
    )
    client = DartClient(api_key="test-key")
    result = client.get_json("https://opendart.fss.or.kr/api/retry.json")
    client.close()

    assert result == {"status": "000"}
    assert route.call_count == 2


@respx.mock
def test_persistent_5xx_raises_after_max_retries(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    respx.get("https://opendart.fss.or.kr/api/always500.json").mock(
        return_value=httpx.Response(500)
    )
    client = DartClient(api_key="test-key")
    with pytest.raises(DartClientError):
        client.get_json("https://opendart.fss.or.kr/api/always500.json")
    client.close()


@respx.mock
def test_rate_limiter_acquire_called_per_request() -> None:
    calls: list[None] = []

    class SpyRateLimiter:
        def acquire(self) -> None:
            calls.append(None)

    respx.get("https://opendart.fss.or.kr/api/spy.json").mock(
        return_value=httpx.Response(200, json={"status": "000"})
    )
    client = DartClient(api_key="test-key", rate_limiter=SpyRateLimiter())
    client.get_json("https://opendart.fss.or.kr/api/spy.json")
    client.close()

    assert len(calls) == 1
