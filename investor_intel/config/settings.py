from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    sec_user_agent: str | None = None
    dart_api_key: str | None = None
    telegram_api_id: str | None = None
    telegram_api_hash: str | None = None
    telegram_session: str | None = None
    daily_llm_budget_usd: float = 1.5
    monthly_llm_budget_usd: float = 45.0
    vault_path: Path = Path("./vault")
    sqlite_path: Path = Path("./data/index.sqlite3")
    config_dir: Path = Path("./config")
    timezone: str = "Asia/Seoul"

    @field_validator(
        "anthropic_api_key",
        "sec_user_agent",
        "dart_api_key",
        "telegram_api_id",
        "telegram_api_hash",
        "telegram_session",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value
