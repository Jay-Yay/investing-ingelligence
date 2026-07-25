from pathlib import Path

import httpx
import respx
from typer.testing import CliRunner

from investor_intel.cli import app
from investor_intel.config.loaders import load_sources_yaml

runner = CliRunner()


def _init_vault(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    monkeypatch.chdir(tmp_path)
    vault_path = tmp_path / "vault"
    config_dir = tmp_path / "config"
    result = runner.invoke(
        app, ["init", "--vault-path", str(vault_path), "--config-dir", str(config_dir)]
    )
    assert result.exit_code == 0, result.output
    return vault_path, config_dir


def test_sync_inbox_reports_missing_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    vault_path = tmp_path / "vault"

    result = runner.invoke(app, ["sync-inbox", "--vault-path", str(vault_path)])

    assert result.exit_code == 1
    assert "inbox_sources.md" in result.output


def test_sync_inbox_processes_naver_line_added_by_init(tmp_path: Path, monkeypatch) -> None:
    vault_path, config_dir = _init_vault(tmp_path, monkeypatch)
    inbox_path = vault_path / "00_System" / "inbox_sources.md"
    assert inbox_path.exists()
    with inbox_path.open("a", encoding="utf-8") as f:
        f.write("- [ ] naver: https://m.blog.naver.com/newblog\n")

    result = runner.invoke(
        app,
        [
            "sync-inbox",
            "--vault-path",
            str(vault_path),
            "--config-dir",
            str(config_dir),
            "--sqlite-path",
            str(tmp_path / "index.sqlite3"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "1건 추가" in result.output
    sources = load_sources_yaml(config_dir / "sources.yaml")
    assert any(s.id == "naver_newblog" for s in sources)

    updated = inbox_path.read_text(encoding="utf-8")
    assert "- [x] naver: https://m.blog.naver.com/newblog" in updated


@respx.mock
def test_sync_inbox_adds_sec_company_when_env_configured(
    tmp_path: Path, monkeypatch
) -> None:
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(
            200,
            json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}},
        )
    )
    vault_path, config_dir = _init_vault(tmp_path, monkeypatch)
    monkeypatch.setenv("SEC_USER_AGENT", "Investor Intel test@example.com")
    inbox_path = vault_path / "00_System" / "inbox_sources.md"
    with inbox_path.open("a", encoding="utf-8") as f:
        f.write("- [ ] sec: AAPL\n")

    result = runner.invoke(
        app,
        [
            "sync-inbox",
            "--vault-path",
            str(vault_path),
            "--config-dir",
            str(config_dir),
            "--sqlite-path",
            str(tmp_path / "index.sqlite3"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (config_dir / "companies.yaml").exists()


def test_sync_inbox_reports_failure_and_nonzero_exit_without_sec_user_agent(
    tmp_path: Path, monkeypatch
) -> None:
    vault_path, config_dir = _init_vault(tmp_path, monkeypatch)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    inbox_path = vault_path / "00_System" / "inbox_sources.md"
    with inbox_path.open("a", encoding="utf-8") as f:
        f.write("- [ ] sec: AAPL\n")

    result = runner.invoke(
        app,
        [
            "sync-inbox",
            "--vault-path",
            str(vault_path),
            "--config-dir",
            str(config_dir),
            "--sqlite-path",
            str(tmp_path / "index.sqlite3"),
        ],
    )

    assert result.exit_code == 1
    assert "SEC_USER_AGENT" in result.output
