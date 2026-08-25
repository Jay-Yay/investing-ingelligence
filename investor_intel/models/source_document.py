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


class DocumentEntities(BaseModel):
    """이 문서가 누구에 대한 것인지.

    `companies`가 평평한 목록 하나였을 때는 "리포트를 쓴 증권사"와 "리포트가 다루는 종목"이
    구분되지 않았다. 그 둘을 섞으면 분석 주체로 필터링해 정답을 지우게 된다(교보증권으로
    필터링해 에이피알 목표주가 문서를 제거한 실패 사례).

    - `subject`:       이 문서를 발행한 주체 (공시 제출인, 채널, 투자자)
    - `mentions`:      본문이 다루는 종목
    - `analyst_house`: 리포트를 쓴 증권사·운용사
    """

    subject: str | None = None
    mentions: list[str] = []
    analyst_house: list[str] = []
    # 어떤 사전으로 뽑은 관계인지. 사전이 바뀌면 결과도 바뀌므로 재현에 필요하다.
    lexicon_version: str | None = None


class SourceDocument(BaseModel):
    id: str
    source_type: SourceType
    source_name: str
    author: str | None = None
    title: str | None = None
    source_url: str
    source_specific_id: str | None = None
    published_at: datetime
    collected_at: datetime
    updated_at: datetime | None = None
    language: str
    content_hash: str
    content_capture: ContentCapture
    assets: list[AssetMention] = []
    companies: list[str] = []
    entities: DocumentEntities = DocumentEntities()
    themes: list[str] = []
    document_type: str
    # --- 본문 품질 측정값 (판정이 아니라 관측값이다 - `ingest.quality` 참고) ---
    readable_ratio: float = 1.0
    truncated: bool = False
    original_chars: int | None = None
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
