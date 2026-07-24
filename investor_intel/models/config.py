from __future__ import annotations

from pydantic import BaseModel


class SourceConfig(BaseModel):
    id: str
    type: str
    name: str
    enabled: bool = True
    url: str
    author: str | None = None
    weight: float = 1.0
    collection_mode: str = "full"
    backfill_days: int = 365
    tags: list[str] = []


class CompanyConfig(BaseModel):
    ticker: str
    cik: str
    name: str
    filing_types: list[str]
    is_foreign_private_issuer: bool = False


class InvestorConfig(BaseModel):
    id: str
    name: str
    fund_name: str
    cik: str
    related_essay_url: str | None = None


class AppSettingsYaml(BaseModel):
    vault_path: str = "./vault"
    timezone: str = "Asia/Seoul"
    daily_report_time: str = "09:00"
