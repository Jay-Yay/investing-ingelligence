from __future__ import annotations

from investor_intel.indexing.answer import Citation, build_answer_bundle
from investor_intel.indexing.router import RouteResult
from investor_intel.indexing.tools import ToolResult


def _route(tool: str, result: ToolResult, escalate: bool = False) -> RouteResult:
    return RouteResult(tool=tool, result=result, escalate=escalate)


# --- Citation -----------------------------------------------------------------------------


def test_clean_citation_is_citable_and_renders_the_excerpt() -> None:
    c = Citation(doc_id="a", title="에이피알 실적", excerpt="매출이 늘었다", status="stable")
    assert c.citable
    assert "매출이 늘었다" in c.render(1)


def test_corrupt_citation_is_not_citable_and_points_to_the_original() -> None:
    c = Citation(doc_id="a", title="에이피알 실적", excerpt="깨진 텍스트", status="corrupt",
                doc_path="10_Sources/DART/x.md")
    assert not c.citable
    rendered = c.render(1)
    assert "깨진 텍스트" not in rendered
    assert "원문 확인 필요" in rendered
    assert "10_Sources/DART/x.md" in rendered


def test_stub_citation_is_not_citable() -> None:
    c = Citation(doc_id="a", title="제목만 있는 문서", excerpt="", status="stub")
    assert not c.citable
    assert "본문 미확보" in c.render(1)


# --- build_answer_bundle -------------------------------------------------------------------


def test_failed_tool_result_becomes_insufficient_evidence() -> None:
    bundle = build_answer_bundle("질문", _route("search_documents", ToolResult(False, note="없음")))
    assert bundle.insufficient_evidence
    assert bundle.render().startswith("정보 부족")


def test_evidence_that_is_entirely_corrupt_is_insufficient_evidence() -> None:
    """근거가 있어도 전부 인용 불가면, "찾았다"고 답하면 안 된다."""
    result = ToolResult(True, evidence=[{"doc_id": "a", "title": "t", "status": "corrupt"}])
    bundle = build_answer_bundle("질문", _route("search_documents", result))
    assert bundle.insufficient_evidence


def test_mixed_evidence_is_sufficient_and_marks_each_citation(tmp_path=None) -> None:
    result = ToolResult(True, evidence=[
        {"doc_id": "a", "title": "정상 문서", "status": "stable", "text": "본문"},
        {"doc_id": "b", "title": "깨진 문서", "status": "corrupt", "text": "깨짐"},
    ])
    bundle = build_answer_bundle("질문", _route("search_documents", result))
    assert not bundle.insufficient_evidence
    assert len(bundle.citable_citations) == 1
    rendered = bundle.render()
    assert "정상 문서" in rendered
    assert "깨짐" not in rendered  # corrupt 본문은 인용문에 나오지 않는다


def test_direct_answer_tools_without_status_default_to_citable() -> None:
    """HoldingsTool/FilingLookupTool의 근거는 status를 안 담는다 - 정보가 없으면
    인용 불가로 단정하지 않고 인용 가능으로 둔다."""
    result = ToolResult(True, answer="902개", evidence=[{"concept_id": "c1", "investor": "BG"}])
    bundle = build_answer_bundle("질문", _route("query_holdings", result))
    assert not bundle.insufficient_evidence
    assert bundle.citations[0].citable


def test_needs_human_review_is_carried_from_the_route_result() -> None:
    result = ToolResult(True, evidence=[{"doc_id": "a", "title": "t", "status": "stable"}])
    bundle = build_answer_bundle("질문", _route("search_documents", result, escalate=True))
    assert bundle.needs_human_review
    assert "사람 확인" in bundle.render()


def test_render_never_shows_note_without_the_insufficient_marker_confusing_it() -> None:
    result = ToolResult(True, evidence=[{"doc_id": "a", "title": "t", "status": "stable"}],
                        note="추가 확인 필요")
    bundle = build_answer_bundle("질문", _route("search_documents", result))
    rendered = bundle.render()
    assert not rendered.startswith("정보 부족")
    assert "추가 확인 필요" in rendered
