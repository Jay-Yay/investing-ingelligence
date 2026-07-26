from datetime import date

from investor_intel.models.analysis import PositionSignal
from investor_intel.models.common import DecisionStatus, RecommendationRating, ThesisShift
from investor_intel.storage.signal_log import append_signal_log, read_latest_signal_text


def _signal(**overrides) -> PositionSignal:
    defaults = dict(
        symbol="NBIS",
        new_facts=["fact"],
        thesis_shift=ThesisShift.STRENGTHENED,
        causal_chain="a -> b",
        expectation_vs_price="not priced in",
        counter_evidence=["risk"],
        decision_status=DecisionStatus.COMPLETE,
        signal=RecommendationRating.BUY,
        signal_strength=75,
        action_conditions="buy now",
        next_check_conditions="if X happens",
    )
    defaults.update(overrides)
    return PositionSignal(**defaults)


def test_read_latest_signal_text_returns_none_when_no_log(tmp_path) -> None:
    assert read_latest_signal_text(tmp_path, "NBIS") is None


def test_append_and_read_latest_signal(tmp_path) -> None:
    append_signal_log(tmp_path, "NBIS", date(2026, 7, 25), _signal())
    append_signal_log(tmp_path, "NBIS", date(2026, 7, 26), _signal(signal_strength=50))

    latest = read_latest_signal_text(tmp_path, "NBIS")
    assert latest is not None
    assert latest.startswith("## 2026-07-26")
    assert "signal_strength: 50" in latest
    assert "2026-07-25" not in latest


def test_append_signal_log_same_day_overwrites_instead_of_duplicating(tmp_path) -> None:
    append_signal_log(tmp_path, "NBIS", date(2026, 7, 26), _signal(signal_strength=40))
    append_signal_log(tmp_path, "NBIS", date(2026, 7, 26), _signal(signal_strength=90))

    path = tmp_path / "40_Analysis" / "Claims" / "NBIS.md"
    content = path.read_text(encoding="utf-8")
    assert content.count("## 2026-07-26") == 1
    assert "signal_strength: 90" in content
    assert "signal_strength: 40" not in content


def test_signal_logs_are_scoped_per_symbol(tmp_path) -> None:
    append_signal_log(tmp_path, "NBIS", date(2026, 7, 26), _signal(symbol="NBIS"))
    append_signal_log(tmp_path, "RDDT", date(2026, 7, 26), _signal(symbol="RDDT", signal_strength=10))

    assert "signal_strength: 75" in read_latest_signal_text(tmp_path, "NBIS")
    assert "signal_strength: 10" in read_latest_signal_text(tmp_path, "RDDT")
