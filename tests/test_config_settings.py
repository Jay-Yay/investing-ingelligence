from pathlib import Path

from investor_intel.config.settings import AppSettings


def test_defaults_when_no_env(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VAULT_PATH", raising=False)
    monkeypatch.delenv("DAILY_LLM_BUDGET_USD", raising=False)
    monkeypatch.delenv("MONTHLY_LLM_BUDGET_USD", raising=False)
    settings = AppSettings(_env_file=None)
    assert settings.anthropic_model == "claude-sonnet-5"
    assert settings.anthropic_api_key is None
    assert settings.vault_path == Path("./vault")
    assert settings.daily_llm_budget_usd == 1.5
    assert settings.monthly_llm_budget_usd == 45.0


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-custom-test")
    monkeypatch.setenv("SEC_USER_AGENT", "Test Agent test@example.com")
    settings = AppSettings(_env_file=None)
    assert settings.anthropic_model == "claude-custom-test"
    assert settings.sec_user_agent == "Test Agent test@example.com"
