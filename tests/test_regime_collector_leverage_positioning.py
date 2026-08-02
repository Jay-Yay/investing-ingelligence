import csv
import io
import zipfile
from datetime import UTC, datetime

import httpx
import respx

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.regime.collectors import leverage_positioning
from investor_intel.regime.models import IndicatorId, IndicatorStatus

_NOW = datetime(2026, 1, 15, 9, tzinfo=UTC)
_HEADER = [
    "Market_and_Exchange_Names",
    "Report_Date_as_YYYY-MM-DD",
    "CFTC_Contract_Market_Code",
    "Open_Interest_All",
    "Asset_Mgr_Positions_Long_All",
    "Asset_Mgr_Positions_Short_All",
    "Lev_Money_Positions_Long_All",
    "Lev_Money_Positions_Short_All",
]


def _zip_bytes(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_HEADER)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("FinFutYY.txt", buf.getvalue())
    return zip_buf.getvalue()


def _row(report_date: str, lev_long: int, lev_short: int) -> dict:
    return {
        "Market_and_Exchange_Names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
        "Report_Date_as_YYYY-MM-DD": report_date,
        "CFTC_Contract_Market_Code": "13874A",
        "Open_Interest_All": "1000",
        "Asset_Mgr_Positions_Long_All": "500",
        "Asset_Mgr_Positions_Short_All": "400",
        "Lev_Money_Positions_Long_All": str(lev_long),
        "Lev_Money_Positions_Short_All": str(lev_short),
    }


@respx.mock
def test_collect_matches_by_stable_contract_code_across_years() -> None:
    # 연도별로 net leveraged funds position이 증가하는 추세를 만들어, 가장 최신 연도(2026)의
    # 값이 최상위 백분위가 되는지 확인한다 - CFTC_Contract_Market_Code로 매칭하므로 계약 표시
    # 명칭이 연도별로 달라도(라이브 조회로 확인된 실제 현상) 문제없어야 한다.
    for i, year in enumerate(range(2021, 2027)):
        respx.get(f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip").mock(
            return_value=httpx.Response(
                200,
                content=_zip_bytes(
                    [_row(f"{year}-01-05", lev_long=400 + i * 50, lev_short=400)]
                ),
            )
        )
    client = SimpleHttpClient()
    obs = leverage_positioning.collect(client, _NOW)

    assert obs.status == IndicatorStatus.OK
    assert obs.indicator_id == IndicatorId.LEVERAGE_POSITIONING
    instruments = obs.details["instruments"]
    assert "sp500_e_mini" in instruments
    assert instruments["sp500_e_mini"]["leveraged_funds_net_pct_oi_5y_percentile"] == 100.0
    assert obs.details["margin_debt_status"] == "unavailable"


@respx.mock
def test_collect_returns_unavailable_when_no_years_fetchable() -> None:
    for year in range(2021, 2027):
        respx.get(f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip").mock(
            return_value=httpx.Response(404)
        )
    client = SimpleHttpClient()
    obs = leverage_positioning.collect(client, _NOW)
    assert obs.status == IndicatorStatus.UNAVAILABLE
