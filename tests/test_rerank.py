from __future__ import annotations

from dataclasses import dataclass

from investor_intel.indexing.rerank import RerankSignal, rerank, wants_numeric_answer


@dataclass
class FakeHit:
    doc_id: str
    okf_status: str = "stable"
    entity_key: str = ""
    period_year: str = ""
    kind: str = ""


def test_entity_match_promotes_a_hit_that_the_filter_could_not_isolate() -> None:
    """'교보증권이 제시한 에이피알 목표주가' 실패 사례 - entity_key가 필터에서 relax된
    뒤에도, 실제로 그 종목을 담은 히트를 순위로 우선할 수 있어야 한다."""
    hits = [
        FakeHit("wrong_company", entity_key="|kr-030610|"),
        FakeHit("right_company", entity_key="|kr-278470|"),
    ]
    out = rerank(hits, "목표주가", entity_key="kr-278470")
    assert [h.doc_id for h in out][0] == "right_company"


def test_period_match_breaks_ties_between_equal_entity_matches() -> None:
    hits = [
        FakeHit("old", entity_key="|kr-278470|", period_year="2020"),
        FakeHit("new", entity_key="|kr-278470|", period_year="2026"),
    ]
    out = rerank(hits, "실적", entity_key="kr-278470", period_year="2026")
    assert out[0].doc_id == "new"


def test_non_stable_status_is_penalized_below_stable_hits() -> None:
    hits = [FakeHit("corrupt_hit", okf_status="corrupt"), FakeHit("stable_hit")]
    out = rerank(hits, "질문")
    assert [h.doc_id for h in out] == ["stable_hit", "corrupt_hit"]


def test_table_chunks_are_promoted_for_numeric_intent_queries() -> None:
    hits = [FakeHit("prose", kind="prose"), FakeHit("table", kind="table")]
    out = rerank(hits, "보유 종목 총 몇 개인가")
    assert out[0].doc_id == "table"


def test_table_promotion_does_not_apply_to_non_numeric_queries() -> None:
    """숫자 의도가 없는 질문에서는 표를 굳이 앞세우지 않는다 - 원래 순서를 지킨다."""
    hits = [FakeHit("prose", kind="prose"), FakeHit("table", kind="table")]
    out = rerank(hits, "무슨 이야기를 했나")
    assert [h.doc_id for h in out] == ["prose", "table"]


def test_wants_numeric_answer_detects_aggregation_intent() -> None:
    assert wants_numeric_answer("보유 종목 개수 몇 개인가")
    assert wants_numeric_answer("총 보고 가치 얼마")
    assert not wants_numeric_answer("무슨 이야기를 했나")


def test_stable_sort_preserves_original_order_when_no_signal_differs() -> None:
    """보너스가 전부 같으면 원래 순서를 그대로 지킨다 - 새 점수로 순위를 흔들지 않는다."""
    hits = [FakeHit("a"), FakeHit("b"), FakeHit("c")]
    out = rerank(hits, "아무 질문")
    assert [h.doc_id for h in out] == ["a", "b", "c"]


def test_hits_without_the_expected_attributes_pass_through_unharmed() -> None:
    """Hit/VectorHit/FusedHit 이외의 타입이 섞여도(속성이 없으면) 보너스 0으로
    안전하게 처리돼야 한다 - 크래시하면 안 된다."""
    class Bare:
        def __init__(self, doc_id):
            self.doc_id = doc_id

    hits = [Bare("x"), Bare("y")]
    out = rerank(hits, "질문", entity_key="kr-278470")
    assert [h.doc_id for h in out] == ["x", "y"]


def test_custom_signal_weights_change_the_ranking() -> None:
    hits = [FakeHit("a", entity_key="|kr-1|"), FakeHit("b", period_year="2026")]
    zero_entity = RerankSignal(entity_match=0.0, period_match=5.0)
    out = rerank(hits, "질문", entity_key="kr-1", period_year="2026", signal=zero_entity)
    assert out[0].doc_id == "b"
