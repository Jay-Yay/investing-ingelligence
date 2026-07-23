from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from investor_intel.models.common import ContentCaptureMode, SourceType
from investor_intel.models.source_document import ContentCapture, SourceDocument


def _now() -> datetime:
    return datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)


def test_content_capture_full_requires_no_reason() -> None:
    with pytest.raises(ValidationError):
        ContentCapture(mode=ContentCaptureMode.FULL, reason="should not be set")


def test_content_capture_excerpt_requires_reason() -> None:
    with pytest.raises(ValidationError):
        ContentCapture(mode=ContentCaptureMode.EXCERPT, reason=None)
    cc = ContentCapture(mode=ContentCaptureMode.EXCERPT, reason="유료 콘텐츠")
    assert cc.reason == "유료 콘텐츠"


def test_source_document_requires_timezone_aware_datetime() -> None:
    with pytest.raises(ValidationError):
        SourceDocument(
            id="abc123",
            source_type=SourceType.TELEGRAM,
            source_name="allbareun",
            source_url="https://t.me/allbareun/1",
            published_at=datetime(2026, 7, 24, 9, 0),
            collected_at=_now(),
            language="ko",
            content_hash="x" * 64,
            content_capture=ContentCapture(mode=ContentCaptureMode.FULL),
            document_type="opinion",
        )


def test_source_document_valid_construction() -> None:
    doc = SourceDocument(
        id="abc123",
        source_type=SourceType.TELEGRAM,
        source_name="allbareun",
        source_url="https://t.me/allbareun/1",
        published_at=_now(),
        collected_at=_now(),
        language="ko",
        content_hash="x" * 64,
        content_capture=ContentCapture(mode=ContentCaptureMode.FULL),
        document_type="opinion",
    )
    assert doc.assets == []
    assert doc.llm_processed is False
