from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator

from investor_intel.models.common import ContentCaptureMode, SourceType


class ContentCapture(BaseModel):
    mode: ContentCaptureMode
    reason: str | None = None

    @model_validator(mode="after")
    def check_reason_matches_mode(self) -> ContentCapture:
        if self.mode != ContentCaptureMode.FULL and not self.reason:
            raise ValueError("reason is required when content_capture.mode is not 'full'")
        if self.mode == ContentCaptureMode.FULL and self.reason:
            raise ValueError("reason must be null when content_capture.mode is 'full'")
        return self


class AssetMention(BaseModel):
    ticker: str
    asset_type: str


class SourceDocument(BaseModel):
    id: str
    source_type: SourceType
    source_name: str
    author: str | None = None
    title: str | None = None
    source_url: str
    published_at: datetime
    collected_at: datetime
    updated_at: datetime | None = None
    language: str
    content_hash: str
    content_capture: ContentCapture
    assets: list[AssetMention] = []
    companies: list[str] = []
    themes: list[str] = []
    document_type: str
    filing_type: str | None = None
    reporting_period: str | None = None
    accession_number: str | None = None
    llm_processed: bool = False
    llm_model: str | None = None
    llm_prompt_version: str | None = None

    @field_validator("published_at", "collected_at", "updated_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("datetime fields must be timezone-aware")
        return value
