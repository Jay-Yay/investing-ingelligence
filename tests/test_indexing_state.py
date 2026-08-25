from __future__ import annotations

import sqlite3

from investor_intel.indexing.state import IndexState, fingerprint


def _state() -> IndexState:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return IndexState(conn)


def test_first_plan_asks_for_a_full_rebuild() -> None:
    """상태 기록이 없으면 무엇이 색인됐는지 알 수 없다 - 증분으로 시작하면 안 된다."""
    plan = _state().plan({"a": "fp1"}, "V7/x")
    assert plan.full_rebuild
    assert "첫 빌드" in plan.rebuild_reason


def test_signature_change_forces_a_full_rebuild() -> None:
    """청킹 규칙이 바뀌면 파일 해시는 그대로인데 색인 결과는 달라져야 한다."""
    state = _state()
    state.set_info("signature", "V7/2026-08-25.1")
    state.record_indexed("a", "fp1", 3)

    plan = state.plan({"a": "fp1"}, "V7/2026-09-01.0")
    assert plan.full_rebuild
    assert "설정 변경" in plan.rebuild_reason


def test_plan_separates_changed_unchanged_and_removed() -> None:
    state = _state()
    state.set_info("signature", "V7/x")
    state.record_indexed("keep", "fp-keep", 2)
    state.record_indexed("edit", "fp-old", 2)
    state.record_indexed("gone", "fp-gone", 2)

    plan = state.plan({"keep": "fp-keep", "edit": "fp-new", "add": "fp-add"}, "V7/x")
    assert not plan.full_rebuild
    assert plan.changed == {"edit": "fp-new", "add": "fp-add"}
    assert plan.unchanged == {"keep"}
    assert plan.removed == {"gone"}


def test_unchanged_corpus_is_a_noop() -> None:
    state = _state()
    state.set_info("signature", "V7/x")
    state.record_indexed("a", "fp1", 1)
    assert state.plan({"a": "fp1"}, "V7/x").is_noop


def test_reindexing_a_document_invalidates_its_embedding() -> None:
    """본문이 바뀌어 다시 색인했으면 기존 벡터는 낡았다 - 남겨두면 뜻 검색이 옛 내용을 가리킨다."""
    state = _state()
    state.record_indexed("a", "fp1", 1)
    state.record_embedded("a", "e5-large")
    assert state.docs_needing_embedding("e5-large") == set()

    state.record_indexed("a", "fp2", 1)
    assert state.docs_needing_embedding("e5-large") == {"a"}


def test_switching_model_marks_everything_as_needing_embedding() -> None:
    """모델을 바꾸면 벡터 공간이 달라져 섞어 쓸 수 없다."""
    state = _state()
    state.record_indexed("a", "fp1", 1)
    state.record_embedded("a", "e5-base")
    assert state.docs_needing_embedding("e5-large") == {"a"}


def test_fingerprint_covers_both_file_content_and_index_settings() -> None:
    assert fingerprint("raw", "V7/x") == fingerprint("raw", "V7/x")
    assert fingerprint("raw", "V7/x") != fingerprint("raw2", "V7/x")
    assert fingerprint("raw", "V7/x") != fingerprint("raw", "V6/x")


def test_forget_removes_state_for_deleted_documents() -> None:
    state = _state()
    state.record_indexed("a", "fp1", 1)
    state.record_indexed("b", "fp2", 1)
    state.forget({"a"})
    assert set(state.fingerprints()) == {"b"}


def test_summary_reports_what_the_index_holds() -> None:
    state = _state()
    state.set_info("signature", "V7/x")
    state.record_indexed("a", "fp1", 3)
    state.record_indexed("b", "fp2", 4)
    state.record_embedded("a", "e5")
    summary = state.summary()
    assert summary["docs"] == 2
    assert summary["chunks"] == 7
    assert summary["embedded"] == 1
    assert summary["signature"] == "V7/x"
