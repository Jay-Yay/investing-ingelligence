from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from investor_intel.collectors.http_client import SimpleHttpClient

_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


class FredClientError(Exception):
    pass


@dataclass
class FredObservation:
    observation_date: date
    value: float | None  # FRED returns "." for missing points -> None


def series_url(series_id: str) -> str:
    """사람이 확인할 수 있는 FRED 시리즈 페이지 URL (source_url로 저장)."""
    return f"https://fred.stlouisfed.org/series/{series_id}"


class FredClient:
    """FRED(세인트루이스 연은) API 래퍼. 무료 API 키가 필요하다
    (https://fred.stlouisfed.org/docs/api/api_key.html).

    observations 엔드포인트는 각 관측치의 realtime_start/end(그 값이 유효했던 발표
    시점 구간)를 함께 주지만, 기본 호출(vintage 파라미터 없음)은 "현재 알려진 최신 값"만
    반환하므로 최초 발표일을 신뢰성 있게 복원할 수 없다 - 그래서 release_date는 만들어내지
    않고 호출부에서 None으로 남긴다. 대신 개정 여부(is_revised)는
    investor_intel.regime.history_store가 같은 observation_date에 대해 이전에 저장된
    값과 비교해 판단한다.
    """

    def __init__(self, api_key: str, http_client: SimpleHttpClient | None = None) -> None:
        if not api_key:
            raise ValueError("FRED_API_KEY is required")
        self._api_key = api_key
        self._client = http_client or SimpleHttpClient(user_agent="Investor Intel Regime/0.1")

    def get_observations(
        self, series_id: str, observation_start: date | None = None
    ) -> list[FredObservation]:
        url = (
            f"{_BASE_URL}?series_id={series_id}&api_key={self._api_key}&file_type=json"
        )
        if observation_start is not None:
            url += f"&observation_start={observation_start.isoformat()}"
        data = self._client.get_json(url)
        if "observations" not in data:
            raise FredClientError(f"unexpected FRED response for {series_id}: {data}")

        results: list[FredObservation] = []
        for row in data["observations"]:
            raw_value = row.get("value")
            value = None if raw_value in (None, ".", "") else float(raw_value)
            results.append(
                FredObservation(observation_date=date.fromisoformat(row["date"]), value=value)
            )
        return results

    def close(self) -> None:
        self._client.close()
