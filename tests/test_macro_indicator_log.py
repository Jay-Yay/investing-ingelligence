from datetime import datetime

from investor_intel.models.macro import IndicatorSnapshot
from investor_intel.storage.macro_indicator_log import (
    append_macro_snapshot,
    read_macro_history,
)


def _values(**overrides: str) -> dict[str, IndicatorSnapshot]:
    defaults = {
        "bond_bid_to_cover": IndicatorSnapshot(
            value="1.8x", note="7월 발행분", source_url="https://example.com/a"
        ),
        "ai_revenue_capex_gap": IndicatorSnapshot(value="$600bn"),
    }
    for key, value in overrides.items():
        defaults[key] = IndicatorSnapshot(value=value)
    return defaults


def test_read_macro_history_returns_empty_when_no_log(tmp_path) -> None:
    assert read_macro_history(tmp_path, "ai_capex_funding_bottleneck") == []


def test_append_and_read_macro_history(tmp_path) -> None:
    append_macro_snapshot(
        tmp_path,
        "ai_capex_funding_bottleneck",
        "AI 인프라 자금조달 병목 가설",
        datetime(2026, 7, 30, 12, 40),
        _values(),
    )
    append_macro_snapshot(
        tmp_path,
        "ai_capex_funding_bottleneck",
        "AI 인프라 자금조달 병목 가설",
        datetime(2026, 8, 6, 9, 0),
        _values(bond_bid_to_cover="1.5x"),
    )

    history = read_macro_history(tmp_path, "ai_capex_funding_bottleneck")
    assert [ts for ts, _ in history] == ["2026-07-30 12:40", "2026-08-06 09:00"]
    assert history[0][1]["bond_bid_to_cover"] == "1.8x"
    assert history[1][1]["bond_bid_to_cover"] == "1.5x"


def test_append_macro_snapshot_same_timestamp_overwrites_instead_of_duplicating(tmp_path) -> None:
    as_of = datetime(2026, 7, 30, 12, 40)
    append_macro_snapshot(
        tmp_path, "thesis_a", "Thesis A", as_of, _values(bond_bid_to_cover="1.8x")
    )
    append_macro_snapshot(
        tmp_path, "thesis_a", "Thesis A", as_of, _values(bond_bid_to_cover="1.2x")
    )

    path = tmp_path / "40_Analysis" / "Macro" / "thesis_a.md"
    content = path.read_text(encoding="utf-8")
    assert content.count("## 2026-07-30 12:40") == 1
    assert "bond_bid_to_cover: 1.2x" in content
    assert "bond_bid_to_cover: 1.8x" not in content


def test_macro_snapshots_include_note_and_source_as_nested_lines(tmp_path) -> None:
    append_macro_snapshot(
        tmp_path,
        "thesis_a",
        "Thesis A",
        datetime(2026, 7, 30, 12, 40),
        _values(),
    )

    path = tmp_path / "40_Analysis" / "Macro" / "thesis_a.md"
    content = path.read_text(encoding="utf-8")
    assert "- bond_bid_to_cover: 1.8x" in content
    assert "  - note: 7월 발행분" in content
    assert "  - source: https://example.com/a" in content


def test_macro_logs_are_scoped_per_thesis(tmp_path) -> None:
    as_of = datetime(2026, 7, 30, 12, 40)
    append_macro_snapshot(
        tmp_path, "thesis_a", "Thesis A", as_of, _values(bond_bid_to_cover="1.8x")
    )
    append_macro_snapshot(
        tmp_path, "thesis_b", "Thesis B", as_of, _values(bond_bid_to_cover="3.0x")
    )

    history_a = read_macro_history(tmp_path, "thesis_a")
    history_b = read_macro_history(tmp_path, "thesis_b")
    assert history_a[0][1]["bond_bid_to_cover"] == "1.8x"
    assert history_b[0][1]["bond_bid_to_cover"] == "3.0x"
