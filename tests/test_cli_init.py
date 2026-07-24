from pathlib import Path

import pytest
from typer.testing import CliRunner

from investor_intel.cli import app
from investor_intel.config.loaders import (
    load_companies_yaml,
    load_dart_companies_yaml,
    load_investors_yaml,
    load_sources_yaml,
)

runner = CliRunner()


def test_init_creates_vault_and_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    vault = tmp_path / "vault"
    config_dir = tmp_path / "config"
    result = runner.invoke(
        app, ["init", "--vault-path", str(vault), "--config-dir", str(config_dir)]
    )
    assert result.exit_code == 0, result.output
    assert (vault / "10_Sources" / "13F").is_dir()
    assert (vault / "10_Sources" / "Essays").is_dir()
    assert (vault / "30_Portfolio" / "portfolio.yaml").exists()
    assert (config_dir / "prompts" / "extract_claims.md").exists()
    assert (config_dir / "prompts" / "analyze_filing.md").exists()
    assert (config_dir / "prompts" / "portfolio_impact.md").exists()
    assert (config_dir / "prompts" / "daily_report.md").exists()

    sources = load_sources_yaml(config_dir / "sources.yaml")
    assert any(s.id == "naver_engineerinvestor" for s in sources)
    assert any(s.id == "telegram_allbareun" for s in sources)

    investors = load_investors_yaml(config_dir / "investors.yaml")
    ciks = {i.cik for i in investors}
    assert ciks == {"0001536411", "0002045724"}

    companies = load_companies_yaml(config_dir / "companies.yaml")
    nbis = next(c for c in companies if c.ticker == "NBIS")
    assert nbis.is_foreign_private_issuer is True
    assert nbis.filing_types == ["20-F", "6-K"]
    assert nbis.cik == "0001513845"

    dart_companies = load_dart_companies_yaml(config_dir / "dart_companies.yaml")
    samsung = next(c for c in dart_companies if c.ticker == "005930")
    assert samsung.corp_code is None
    assert samsung.name == "삼성전자"


def test_init_is_idempotent_and_does_not_overwrite_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    vault = tmp_path / "vault"
    config_dir = tmp_path / "config"
    runner.invoke(app, ["init", "--vault-path", str(vault), "--config-dir", str(config_dir)])

    portfolio_path = vault / "30_Portfolio" / "portfolio.yaml"
    portfolio_path.write_text("as_of: 2099-01-01\n", encoding="utf-8")

    result = runner.invoke(
        app, ["init", "--vault-path", str(vault), "--config-dir", str(config_dir)]
    )
    assert result.exit_code == 0
    assert portfolio_path.read_text(encoding="utf-8") == "as_of: 2099-01-01\n"
