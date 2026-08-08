from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    anthropic_large_doc_model: str = "claude-haiku-4-5"
    # 미처리 백로그 실측(2026-08) 기준 central_bank/ib_insights 문서 평균이 ~29KB라
    # 임계값 50,000에서는 분량 대부분이 sonnet(3배 가격)으로 갔다. 15,000이면 고유 18.9MB
    # 기준 sonnet 10.8MB -> 5.0MB로 줄어 입력비 추정이 ~$11.9 -> ~$8.5가 된다. 주장 추출은
    # 정해진 툴 스키마를 채우는 작업이라 haiku로 내려도 품질 저하가 작다.
    large_doc_char_threshold: int = 15_000
    # analyze는 야간 크론에서 vault에 기록만 하므로 지연 민감도가 0이고, Message Batches API는
    # 입력/출력 토큰이 전 구간 50% 할인이다. 대화형으로 즉시 결과가 필요하면 CLI `--no-batch`.
    analyze_use_batch_api: bool = True
    sec_user_agent: str | None = None
    dart_api_key: str | None = None
    fred_api_key: str | None = None
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
        "fred_api_key",
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
