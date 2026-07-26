from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

from investor_intel.collectors.base import CollectItem
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.collectors.naver_research_document import render_naver_research_body
from investor_intel.collectors.naver_research_parser import (
    NaverResearchDetail,
    NaverResearchStub,
    parse_naver_research_detail,
)
from investor_intel.collectors.pdf_extract import PdfExtractError, extract_pdf_text

DETAIL_URL = "https://m.stock.naver.com/api/research/company/{research_id}"
CANONICAL_URL = "https://m.stock.naver.com/research/company/{research_id}"

_EMPTY_DETAIL = NaverResearchDetail(
    content_text=None, opinion=None, goal_price=None, prev_goal_price=None, attach_url=None
)


def fetch_detail(client: SimpleHttpClient, research_id: int) -> NaverResearchDetail:
    try:
        json_text = client.get_text(DETAIL_URL.format(research_id=research_id))
        return parse_naver_research_detail(json_text)
    except Exception:  # noqa: BLE001 - detail is best-effort, falls back to title-only
        return _EMPTY_DETAIL


def fetch_pdf_text(client: SimpleHttpClient, attach_url: str | None) -> str | None:
    if not attach_url:
        return None
    try:
        response = client.get(attach_url)
    except Exception:  # noqa: BLE001
        return None
    # sniff magic bytes rather than trust Content-Type - see ib_insights.py for why
    if not response.content.startswith(b"%PDF-"):
        return None
    try:
        return extract_pdf_text(response.content)
    except PdfExtractError:
        return None


def build_research_collect_item(
    client: SimpleHttpClient, stub: NaverResearchStub, fallback_author: str
) -> CollectItem:
    canonical_url = CANONICAL_URL.format(research_id=stub.research_id)
    detail = fetch_detail(client, stub.research_id)
    pdf_text = fetch_pdf_text(client, detail.attach_url)

    resolved_stub = stub if stub.item_name else replace(stub, item_name=detail.item_name or "")
    body = render_naver_research_body(resolved_stub, detail, canonical_url, pdf_text)

    if pdf_text:
        mode, reason = "full", None
    elif detail.content_text:
        mode = "excerpt"
        reason = "PDF 원문 대신 네이버 API의 content 요약 필드만 캡처함"
    else:
        mode = "metadata_only"
        reason = "본문/PDF를 모두 가져오지 못해 제목만 캡처함"

    published = stub.write_date or date.today()
    return CollectItem(
        source_specific_id=str(stub.research_id),
        canonical_url=canonical_url,
        title=f"[{resolved_stub.item_name}] {stub.title}",
        author=stub.broker_name or fallback_author,
        published_at=datetime(published.year, published.month, published.day, tzinfo=UTC),
        updated_at=None,
        language="ko",
        body_text=body,
        content_capture_mode=mode,
        content_capture_reason=reason,
        companies=[stub.item_code] if stub.item_code else [],
        document_type="ib_research_summary",
        filing_type=None,
        reporting_period=None,
        accession_number=None,
    )
