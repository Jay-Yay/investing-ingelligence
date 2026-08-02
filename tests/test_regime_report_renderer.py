from datetime import UTC, date, datetime

from investor_intel.regime.models import (
    AiRegime,
    IndicatorFrequency,
    IndicatorId,
    IndicatorObservation,
    IndicatorStatus,
    MarketRegime,
)
from investor_intel.regime.report_renderer import build_report, detect_new_releases, render_markdown
from investor_intel.regime.scoring import compute_scores

_NOW = datetime(2026, 1, 2, 9, tzinfo=UTC)


def _obs(
    indicator_id: IndicatorId,
    value: float | None = 1.0,
    status: IndicatorStatus = IndicatorStatus.OK,
    obs_date: date = date(2026, 1, 2),
    details: dict | None = None,
) -> IndicatorObservation:
    return IndicatorObservation(
        indicator_id=indicator_id,
        indicator_name=indicator_id.value,
        value=value,
        unit="unit",
        observation_date=obs_date,
        release_date=None,
        fetched_at=_NOW,
        source_name="test",
        source_url="https://example.com",
        frequency=IndicatorFrequency.DAILY,
        data_age_days=0,
        is_stale=False,
        is_revised=None,
        status=status,
        details=details or {},
    )


def _observations() -> dict[IndicatorId, IndicatorObservation]:
    return {indicator_id: _obs(indicator_id) for indicator_id in IndicatorId}


def test_build_report_and_render_markdown_smoke() -> None:
    observations = _observations()
    scores = compute_scores(observations)
    report = build_report(
        date(2026, 1, 2),
        observations,
        signals=[],
        market_regime=MarketRegime.NEUTRAL,
        ai_regime=AiRegime.INDETERMINATE,
        scores=scores,
        new_releases=[],
    )

    assert report.data_quality.coverage_ratio == 1.0
    markdown = render_markdown(report, observations)
    assert "# Daily Market Regime Report" in markdown
    assert "## 9. 판단 근거" in markdown


def test_detect_new_releases_flags_changed_values() -> None:
    yesterday = {IndicatorId.CREDIT_SPREAD_HY_OAS: _obs(IndicatorId.CREDIT_SPREAD_HY_OAS, 3.0)}
    today = {IndicatorId.CREDIT_SPREAD_HY_OAS: _obs(IndicatorId.CREDIT_SPREAD_HY_OAS, 3.5)}

    releases = detect_new_releases(today, yesterday)
    assert len(releases) == 1
    assert "3.0" in releases[0] and "3.5" in releases[0]


def test_detect_new_releases_empty_when_nothing_changed() -> None:
    obs = {IndicatorId.CREDIT_SPREAD_HY_OAS: _obs(IndicatorId.CREDIT_SPREAD_HY_OAS, 3.0)}
    assert detect_new_releases(obs, obs) == []
