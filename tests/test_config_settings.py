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


def test_blank_env_value_treated_as_unset(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("DART_API_KEY", "   ")
    settings = AppSettings(_env_file=None)
    assert settings.anthropic_api_key is None
    assert settings.dart_api_key is None


def test_large_doc_char_threshold_default_routes_typical_backlog_docs() -> None:
    """실측 미처리 문서 평균(central_bank/ib_insights ~29KB)이 임계값을 넘어야 저렴한
    모델로 라우팅된다 - 50,000자였을 때는 분량 대부분이 기본 모델로 갔다."""
    assert AppSettings(_env_file=None).large_doc_char_threshold == 15_000


def test_analyze_uses_batch_api_by_default() -> None:
    """analyze는 야간 크론 전용이라 지연 민감도가 0 - 50% 할인되는 배치가 기본이다."""
    assert AppSettings(_env_file=None).analyze_use_batch_api is True
