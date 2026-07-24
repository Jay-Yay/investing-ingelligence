from pathlib import Path

from typer.testing import CliRunner

from investor_intel.cli import app

runner = CliRunner()


def test_doctor_fails_when_sec_user_agent_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    result = runner.invoke(app, ["doctor", "--config-dir", str(config_dir)])
    assert result.exit_code == 1
    assert "MISSING] SEC_USER_AGENT" in result.output


def test_doctor_passes_when_required_envs_present(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", "Test Agent test@example.com")
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    result = runner.invoke(app, ["doctor", "--config-dir", str(config_dir)])
    assert result.exit_code == 0
    assert "OK] SEC_USER_AGENT" in result.output


def test_doctor_reports_missing_config_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SEC_USER_AGENT", "Test Agent test@example.com")
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    result = runner.invoke(app, ["doctor", "--config-dir", str(config_dir)])
    assert "MISSING] config/sources.yaml" in result.output
    assert "MISSING] config/dart_companies.yaml" in result.output
