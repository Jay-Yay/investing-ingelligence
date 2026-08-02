from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.regime.collectors.common import build_observation, unavailable_observation
from investor_intel.regime.models import IndicatorFrequency, IndicatorId, IndicatorObservation
from investor_intel.regime.percentile import percentile_rank, value_n_observations_back

_ZIP_URL_TEMPLATE = "https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip"
_YEARS_BACK = 5  # 5년 백분위 계산에 필요한 만큼 과거 연도 파일을 함께 받는다
# CFTC_Contract_Market_Code는 연도가 바뀌어도 고정이다 - 계약의 표시 명칭(Market_and_
# Exchange_Names)은 "E-MINI S&P 500 STOCK INDEX"(2020) -> "E-MINI S&P 500"(2025)처럼 연도별로
# 바뀌는 것이 실제로 확인되어(라이브 조회로 검증) 이름이 아니라 코드로 매칭한다.
_CONTRACT_CODES = {
    "sp500_e_mini": "13874A",
    "nasdaq100_e_mini": "209742",
    "russell2000_e_mini": "239742",
}
INDICATOR_NAME = "레버리지 및 포지셔닝"
SOURCE_NAME = "CFTC Traders in Financial Futures (Futures Only)"
_SOURCE_URL = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm"

# FINRA 마진통계 페이지(margin-statistics)는 라이브 조회 결과 봇 차단(HTTP 403)으로 자동 수집이
# 불가능함을 확인했다 - 이 저장소가 이미 같은 이유로 제외한 Morgan Stanley/State Street/Fisher
# Investments(Runbook.md)와 동일한 사례다. 개인 레버리지(margin debt) 축은 이번 페이즈에서
# unavailable로 남기고, 기관 포지셔닝(CFTC)만으로 지표를 구성한다.
MARGIN_DEBT_UNAVAILABLE_REASON = "FINRA margin statistics page blocks automated access (HTTP 403)"


def _fetch_year_rows(client: SimpleHttpClient, year: int) -> list[dict[str, str]]:
    response = client.get(_ZIP_URL_TEMPLATE.format(year=year))
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
        if not names:
            return []
        with zf.open(names[0]) as f:
            text = f.read().decode("utf-8", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _series_for_code(
    rows_by_year: list[list[dict[str, str]]], code: str
) -> list[tuple[date, float, float, float]]:
    """(report_date, open_interest, asset_mgr_net_pct_oi, leveraged_funds_net_pct_oi) 목록,
    날짜 오름차순."""
    points: list[tuple[date, float, float, float]] = []
    for rows in rows_by_year:
        for row in rows:
            if row.get("CFTC_Contract_Market_Code", "").strip() != code:
                continue
            try:
                report_date = date.fromisoformat(row["Report_Date_as_YYYY-MM-DD"])
                oi = float(row["Open_Interest_All"])
                am_long = float(row["Asset_Mgr_Positions_Long_All"])
                am_short = float(row["Asset_Mgr_Positions_Short_All"])
                lm_long = float(row["Lev_Money_Positions_Long_All"])
                lm_short = float(row["Lev_Money_Positions_Short_All"])
            except (KeyError, ValueError):
                continue
            if oi == 0:
                continue
            points.append(
                (
                    report_date,
                    oi,
                    (am_long - am_short) / oi * 100,
                    (lm_long - lm_short) / oi * 100,
                )
            )
    points.sort(key=lambda p: p[0])
    return points


def collect(client: SimpleHttpClient, fetched_at: datetime) -> IndicatorObservation:
    """CFTC "Traders in Financial Futures"(선물 단독) 연간 파일을 최근 수년치 받아 S&P500/
    Nasdaq100/Russell2000 E-mini의 자산운용사(Asset Manager)·레버리지드펀드(Leveraged Funds)
    순포지션이 미결제약정(Open Interest) 대비 몇 %인지, 그 값이 5년래 몇 백분위인지 계산한다.

    이 데이터는 선물(및 옵션) 시장에 보고되는 대형 트레이더 포지션의 일부일 뿐 시장 전체의
    롱/숏 비중이 아니다 - report_renderer가 항상 이 한계를 명시해야 한다.

    개인 레버리지(FINRA margin debt)는 소스 페이지가 자동화 접근을 차단해(403, 라이브 확인)
    이번 페이즈에서는 다루지 않는다 - details.margin_debt_status로 명시.

    value = 3개 지수 레버리지드펀드 순포지션 %OI의 평균(헤드라인). details.instruments에
    지수별 세부값과 5년 백분위.
    """
    rows_by_year: list[list[dict[str, str]]] = []
    for year in range(fetched_at.year - _YEARS_BACK, fetched_at.year + 1):
        try:
            rows = _fetch_year_rows(client, year)
        except Exception:  # noqa: BLE001 - 특정 연도 파일이 아직 게시되지 않았을 수 있다
            continue
        if rows:
            rows_by_year.append(rows)

    if not rows_by_year:
        return unavailable(fetched_at, "CFTC TFF annual files could not be fetched")

    per_instrument: dict[str, dict[str, object]] = {}
    for label, code in _CONTRACT_CODES.items():
        series = _series_for_code(rows_by_year, code)
        if not series:
            continue
        latest_date, latest_oi, latest_am_pct, latest_lm_pct = series[-1]
        lm_series = [(p[0], p[3]) for p in series]
        lm_4w_ago = value_n_observations_back(lm_series, 4)  # 주간 발표 기준 4주 전
        per_instrument[label] = {
            "report_date": latest_date.isoformat(),
            "open_interest": latest_oi,
            "asset_mgr_net_pct_oi": round(latest_am_pct, 2),
            "asset_mgr_net_pct_oi_5y_percentile": percentile_rank(
                [p[2] for p in series], latest_am_pct
            ),
            "leveraged_funds_net_pct_oi": round(latest_lm_pct, 2),
            "leveraged_funds_net_pct_oi_5y_percentile": percentile_rank(
                [p[3] for p in series], latest_lm_pct
            ),
            "leveraged_funds_net_pct_oi_change_4w": (
                None if lm_4w_ago is None else round(latest_lm_pct - lm_4w_ago, 2)
            ),
        }

    if not per_instrument:
        return unavailable(
            fetched_at, "none of the tracked contract codes were found in CFTC files"
        )

    lm_values = [v["leveraged_funds_net_pct_oi"] for v in per_instrument.values()]
    headline_value = round(sum(lm_values) / len(lm_values), 2)  # type: ignore[arg-type]
    latest_report_date = max(date.fromisoformat(v["report_date"]) for v in per_instrument.values())  # type: ignore[arg-type]

    lm_percentiles = [
        v["leveraged_funds_net_pct_oi_5y_percentile"]
        for v in per_instrument.values()
        if v["leveraged_funds_net_pct_oi_5y_percentile"] is not None
    ]
    overheating_signal = bool(
        lm_percentiles and (sum(lm_percentiles) / len(lm_percentiles)) >= 90  # type: ignore[arg-type]
    )
    changes_4w = [
        v["leveraged_funds_net_pct_oi_change_4w"]
        for v in per_instrument.values()
        if v["leveraged_funds_net_pct_oi_change_4w"] is not None
    ]
    change_4w_avg = None if not changes_4w else round(sum(changes_4w) / len(changes_4w), 2)  # type: ignore[arg-type]
    deleveraging_signal = bool(change_4w_avg is not None and change_4w_avg <= -10)

    return build_observation(
        indicator_id=IndicatorId.LEVERAGE_POSITIONING,
        indicator_name=INDICATOR_NAME,
        value=headline_value,
        unit="pct_of_open_interest",
        observation_date=latest_report_date,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=_SOURCE_URL,
        frequency=IndicatorFrequency.WEEKLY,
        details={
            "instruments": per_instrument,
            "leveraged_funds_net_pct_oi_change_4w_avg": change_4w_avg,
            "overheating_signal": overheating_signal,
            "deleveraging_signal": deleveraging_signal,
            "margin_debt_status": "unavailable",
            "margin_debt_reason": MARGIN_DEBT_UNAVAILABLE_REASON,
            "scope_caveat": (
                "CFTC 데이터는 선물(및 옵션) 시장에 보고되는 대형 트레이더 포지션의 일부이며 "
                "시장 전체 롱/숏 비중이 아니다"
            ),
        },
    )


def unavailable(fetched_at: datetime, reason: str) -> IndicatorObservation:
    return unavailable_observation(
        indicator_id=IndicatorId.LEVERAGE_POSITIONING,
        indicator_name=INDICATOR_NAME,
        unit="pct_of_open_interest",
        frequency=IndicatorFrequency.WEEKLY,
        fetched_at=fetched_at,
        source_name=SOURCE_NAME,
        source_url=_SOURCE_URL,
        reason=reason,
    )
