from __future__ import annotations

import re
from dataclasses import dataclass

from investor_intel.collectors.sec_client import SECClient
from investor_intel.collectors.sec_urls import document_url, filing_index_url
from investor_intel.collectors.table_markdown import convert_tables_to_markdown
from investor_intel.collectors.text_extract import strip_markup

_TRANSCRIPT_EXHIBIT_NAME_RE = re.compile(r"ex-?99", re.IGNORECASE)
_TRANSCRIPT_CUE_RE = re.compile(r"\boperator\b", re.IGNORECASE)
_QA_CUE_RE = re.compile(r"question-and-answer|question and answer|\bQ&A\b", re.IGNORECASE)

# Inline XBRL(iXBRL) 문서는 화면에 보이지 않는 태깅 전용 데이터(컨텍스트/단위/숨김 팩트)를
# <ix:header>...</ix:header> 블록 하나에 몰아 문서 최상단(<body> 직후)에 심는다. 이 블록은
# XBRL 스펙상 렌더러가 항상 숨기므로 사람이 읽는 본문이 아니다 - 태그만 벗기면 "amzn-20260630
# false 2026 Q2 ..." 같은 태그/컨텍스트 나열이 그대로 텍스트로 새어나와 실제 본문(Item 2/MD&A 등)
# 앞에 쓸모없는 분량만 채운다.
_IX_HEADER_RE = re.compile(r"<ix:header\b.*?</ix:header>", re.IGNORECASE | re.DOTALL)

# 8-K의 "Results of Operations and Financial Condition" 항목 코드 - 이 코드가 있으면 실적
# 보도자료(대개 Exhibit 99.1)가 첨부돼 있다고 신뢰할 수 있다(SEC 표준 8-K 항목 분류).
RESULTS_OF_OPERATIONS_ITEM = "2.02"


def _strip_inline_xbrl_header(html: str) -> str:
    return _IX_HEADER_RE.sub(" ", html)


def fetch_full_text(
    client: SECClient, cik: str, accession_number: str, filename: str
) -> str | None:
    """primaryDocument HTML을 가져와 태그를 제거한 원문 텍스트를 반환한다. 실패 시 None."""
    try:
        html = client.get_text(document_url(cik, accession_number, filename))
    except Exception:  # noqa: BLE001
        return None

    html = _strip_inline_xbrl_header(html)
    text = strip_markup(convert_tables_to_markdown(html))
    if not text:
        return None
    return text


@dataclass
class EarningsExhibit:
    text: str
    is_transcript: bool


def find_earnings_exhibit(
    client: SECClient, cik: str, accession_number: str, filing_items: list[str]
) -> EarningsExhibit | None:
    """8-K의 Exhibit 99.x 중 실적 관련 원문(컨퍼런스콜 녹취록 또는 실적발표 보도자료)을 찾는다.

    SEC 필링 중 약 20~30%만 8-K에 Exhibit 99.x로 실제 통화 녹취록을 첨부한다(나머지는 보도자료만).
    "Operator"(사회자 멘트)와 질의응답 표현이 함께 나오면 진짜 녹취록으로 판단해 우선 반환한다.
    녹취록이 아니더라도 8-K 항목 코드에 2.02(실적/재무상태 결과)가 있으면 거의 항상 실적발표
    보도자료가 Exhibit 99.x로 첨부돼 있으므로(관례상 99.1이 본 보도자료), 후보 중 첫 번째로
    유의미한 내용을 담은 exhibit을 보도자료로 캡처한다 - 컨퍼런스콜 대사가 아니어도 매출/EPS
    등 실적 디테일은 이 보도자료에 담겨 있어 캡처할 가치가 있다.

    아무 후보도 없거나(비-8-K, exhibit 없음), 항목 2.02도 없고 녹취록 패턴도 안 맞으면(예:
    인수합병/임원변경 등 실적과 무관한 8-K) None을 반환하고 호출부는 metadata_only로 처리한다.
    """
    try:
        index = client.get_json(filing_index_url(cik, accession_number))
    except Exception:  # noqa: BLE001
        return None

    items = index.get("directory", {}).get("item", [])
    candidates = sorted(
        item["name"]
        for item in items
        if isinstance(item.get("name"), str)
        and item["name"].lower().endswith(".htm")
        and _TRANSCRIPT_EXHIBIT_NAME_RE.search(item["name"])
    )

    has_results_item = RESULTS_OF_OPERATIONS_ITEM in filing_items
    press_release_fallback: str | None = None

    for filename in candidates:
        try:
            html = client.get_text(document_url(cik, accession_number, filename))
        except Exception:  # noqa: BLE001
            continue
        text = strip_markup(convert_tables_to_markdown(html))
        if not text:
            continue
        if _TRANSCRIPT_CUE_RE.search(text) and _QA_CUE_RE.search(text):
            return EarningsExhibit(text=text, is_transcript=True)
        if has_results_item and press_release_fallback is None:
            press_release_fallback = text

    if press_release_fallback is not None:
        return EarningsExhibit(text=press_release_fallback, is_transcript=False)

    return None
