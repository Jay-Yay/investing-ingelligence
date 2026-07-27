from __future__ import annotations

import re

from investor_intel.collectors.sec_client import SECClient
from investor_intel.collectors.sec_urls import document_url, filing_index_url
from investor_intel.collectors.table_markdown import convert_tables_to_markdown
from investor_intel.collectors.text_extract import strip_markup, truncate

_TRANSCRIPT_EXHIBIT_NAME_RE = re.compile(r"ex-?99", re.IGNORECASE)
_TRANSCRIPT_CUE_RE = re.compile(r"\boperator\b", re.IGNORECASE)
_QA_CUE_RE = re.compile(r"question-and-answer|question and answer|\bQ&A\b", re.IGNORECASE)


def fetch_full_text(
    client: SECClient, cik: str, accession_number: str, filename: str
) -> str | None:
    """primaryDocument HTML을 가져와 태그를 제거한 원문 텍스트를 반환한다. 실패 시 None."""
    try:
        html = client.get_text(document_url(cik, accession_number, filename))
    except Exception:  # noqa: BLE001
        return None

    text = strip_markup(convert_tables_to_markdown(html))
    if not text:
        return None
    return truncate(text)


def find_transcript_exhibit(client: SECClient, cik: str, accession_number: str) -> str | None:
    """8-K 필링의 첨부 문서 중 실적발표 컨퍼런스콜 녹취록으로 보이는 것을 찾아 원문을 반환한다.

    SEC 필링 중 약 20~30%만 8-K에 Exhibit 99.x로 실제 통화 녹취록을 첨부한다(나머지는 보도자료만).
    파일명에 "ex99"류 패턴이 있는 문서 후보를 가져와, "Operator"(사회자 멘트)와 질의응답 표현이
    함께 나오면 녹취록으로 판단한다 - 순수 보도자료는 이 두 신호가 함께 나타나지 않는다.
    찾지 못하면(비-8-K, exhibit 없음, 패턴 불일치, 네트워크 오류 등) None을 반환하고 호출부는
    기존과 동일하게 metadata_only로 처리한다.
    """
    try:
        index = client.get_json(filing_index_url(cik, accession_number))
    except Exception:  # noqa: BLE001
        return None

    items = index.get("directory", {}).get("item", [])
    candidates = [
        item["name"]
        for item in items
        if isinstance(item.get("name"), str)
        and item["name"].lower().endswith(".htm")
        and _TRANSCRIPT_EXHIBIT_NAME_RE.search(item["name"])
    ]

    for filename in candidates:
        try:
            html = client.get_text(document_url(cik, accession_number, filename))
        except Exception:  # noqa: BLE001
            continue
        text = strip_markup(convert_tables_to_markdown(html))
        if _TRANSCRIPT_CUE_RE.search(text) and _QA_CUE_RE.search(text):
            return truncate(text)

    return None
