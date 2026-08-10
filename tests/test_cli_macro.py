import json
from pathlib import Path

from typer.testing import CliRunner

from investor_intel.cli import app

runner = CliRunner()

_THESES_YAML = """theses:
  - id: ai_capex_funding_bottleneck
    title: "AI 인프라 자금조달 병목 가설"
    indicators:
      - id: hyperscaler_bond_bid_to_cover
        label: "채권 응찰배율"
      - id: ai_revenue_capex_gap
        label: "AI 매출-capex 갭"
"""


def _write_config(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "macro_theses.yaml").write_text(_THESES_YAML, encoding="utf-8")


def test_record_indicators_fails_for_unknown_thesis(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir)
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps({"hyperscaler_bond_bid_to_cover": {"value": "1.8x"}}))

    result = runner.invoke(
        app,
        [
            "record-indicators",
            "no_such_thesis",
            "--data-file",
            str(data_file),
            "--config-dir",
            str(config_dir),
            "--vault-path",
            str(tmp_path / "vault"),
        ],
    )
    assert result.exit_code == 1
    assert "찾을 수 없다" in result.output


def test_record_indicators_fails_for_unknown_indicator_id(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir)
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps({"not_a_real_indicator": {"value": "x"}}))

    result = runner.invoke(
        app,
        [
            "record-indicators",
            "ai_capex_funding_bottleneck",
            "--data-file",
            str(data_file),
            "--config-dir",
            str(config_dir),
            "--vault-path",
            str(tmp_path / "vault"),
        ],
    )
    assert result.exit_code == 1
    assert "정의되지 않은 지표" in result.output


def test_record_indicators_then_macro_status_renders_table(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    vault_path = tmp_path / "vault"
    _write_config(config_dir)

    data_file = tmp_path / "data.json"
    data_file.write_text(
        json.dumps(
            {
                "hyperscaler_bond_bid_to_cover": {
                    "value": "1.8x",
                    "note": "7월 발행분",
                    "source_url": "https://example.com/a",
                },
                "ai_revenue_capex_gap": {"value": "$600bn"},
            }
        )
    )

    record_result = runner.invoke(
        app,
        [
            "record-indicators",
            "ai_capex_funding_bottleneck",
            "--data-file",
            str(data_file),
            "--as-of",
            "2026-07-30 12:40",
            "--config-dir",
            str(config_dir),
            "--vault-path",
            str(vault_path),
        ],
    )
    assert record_result.exit_code == 0
    assert "기록 완료" in record_result.output

    log_path = vault_path / "40_Analysis" / "Macro" / "ai_capex_funding_bottleneck.md"
    assert log_path.exists()
    assert "hyperscaler_bond_bid_to_cover: 1.8x" in log_path.read_text(encoding="utf-8")

    status_result = runner.invoke(
        app,
        [
            "macro-status",
            "ai_capex_funding_bottleneck",
            "--config-dir",
            str(config_dir),
            "--vault-path",
            str(vault_path),
        ],
    )
    assert status_result.exit_code == 0
    assert "2026-07-30 12:40" in status_result.output
    assert "채권 응찰배율" in status_result.output
    assert "1.8x" in status_result.output


def test_macro_status_with_no_history_reports_empty(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir)

    result = runner.invoke(
        app,
        [
            "macro-status",
            "ai_capex_funding_bottleneck",
            "--config-dir",
            str(config_dir),
            "--vault-path",
            str(tmp_path / "vault"),
        ],
    )
    assert result.exit_code == 0
    assert "기록된 스냅샷이 없다" in result.output
