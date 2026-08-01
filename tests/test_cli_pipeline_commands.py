from pathlib import Path

from typer.testing import CliRunner

from investor_intel.cli import app

runner = CliRunner()


def test_analyze_fails_without_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["analyze", "--vault-path", str(tmp_path / "vault")],
    )
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output


def test_portfolio_reports_no_portfolio_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["portfolio", "--vault-path", str(tmp_path / "vault")],
    )
    assert result.exit_code == 0
    assert "portfolio.yaml 없음" in result.output


def test_report_generates_file_without_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    vault_path = tmp_path / "vault"

    result = runner.invoke(app, ["report", "--vault-path", str(vault_path)])
    assert result.exit_code == 0
    report_files = list((vault_path / "50_Reports" / "Daily").glob("*.md"))
    assert len(report_files) == 1


def test_earnings_transcript_fails_without_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["earnings-transcript", "--vault-path", str(tmp_path / "vault")],
    )
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output


def test_earnings_transcript_fails_without_sec_user_agent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["earnings-transcript", "--vault-path", str(tmp_path / "vault")],
    )
    assert result.exit_code == 1
    assert "SEC_USER_AGENT" in result.output


def test_earnings_transcript_reports_no_companies_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("SEC_USER_AGENT", "Investor Intel test@example.com")
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    result = runner.invoke(
        app,
        [
            "earnings-transcript",
            "--config-dir",
            str(config_dir),
            "--vault-path",
            str(tmp_path / "vault"),
            "--sqlite-path",
            str(tmp_path / "index.sqlite3"),
        ],
    )
    assert result.exit_code == 0
    assert "companies.yaml 없음" in result.output


def test_run_daily_with_empty_config_still_succeeds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    vault_path = tmp_path / "vault"

    result = runner.invoke(
        app,
        [
            "run-daily",
            "--config-dir",
            str(config_dir),
            "--vault-path",
            str(vault_path),
            "--sqlite-path",
            str(tmp_path / "index.sqlite3"),
        ],
    )
    assert result.exit_code == 0
    assert "리포트 생성 완료" in result.output
