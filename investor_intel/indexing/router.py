from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from investor_intel.indexing.bm25_index import Bm25Index
from investor_intel.indexing.retrieval import DEFAULT_EXCLUDE_STATUS, EntityLexicon, RetrievalPolicy
from investor_intel.indexing.tools import (
    DocumentSearchTool,
    FilingLookupTool,
    GraphTool,
    HoldingsTool,
    Tool,
    ToolResult,
)

if TYPE_CHECKING:
    from investor_intel.indexing.embedding import Encoder
    from investor_intel.indexing.vector_index import VectorIndex

# 다른 모듈이 `from investor_intel.indexing.router import RetrievalPolicy`로 여전히
# 가져올 수 있게 재노출한다 - 정의 자체는 retrieval.py로 옮겼다(AdaptiveRetriever가
# 이 클래스를 쓰는데, router.py가 retrieval.py를 이미 임포트하고 있어 반대 방향으로
# 두면 순환 임포트가 된다).
__all__ = ["RetrievalPolicy", "RouteResult", "Router", "Trace"]

# ---------------------------------------------------------------------------
# 4주차 자료 §15 Single-Agent Routing 을 규칙으로 구현한 것.
#
#   질문 -> Router -> ┌ query_holdings   (표 데이터 집계)
#                     ├ lookup_filing    (공시 카탈로그)
#                     └ search_documents (비정형 문서)
#
# 자료가 지적한 한계도 그대로 안고 간다: 판단과 실행이 한 곳에 몰려 있고,
# 도구가 늘수록 분기 규칙이 복잡해지며, 도구를 잘못 고르면 결과 전체가 틀어진다.
# 아래 `route()`가 잘못 고른 경우를 대비해 문서 검색으로 폴백하는 이유가 그것이다.
# ---------------------------------------------------------------------------

# 검색이 필요 없는 질문. 4주차 §9 "모든 질문이 외부 검색을 필요로 하지는 않는다".
# 한글에는 \b 단어 경계가 기대대로 걸리지 않는다("안녕하세요"의 '안녕' 뒤에는 경계가 없다).
# 그래서 한글 인사말은 접두 일치로, 영문은 단어 경계로 따로 처리한다.
_NO_RETRIEVAL = re.compile(
    r"^\s*(?:안녕|반갑|반가워|고마|감사|잘\s*지|수고|ㅎㅇ|ㄱㅅ)"
    r"|^\s*(?:hi|hello|hey|thanks?|thank you|ok|okay)\b"
    r"|^\s*$", re.I)

_HOLDINGS_HINT = re.compile(
    r"13F|보유\s*(현황|종목|규모)|편입\s*종목|포트폴리오\s*(비중|상위|편입)|집중도|쏠림|최대\s*비중")
_CATALOG_HINT = re.compile(
    r"접수번호|공시번호|accession|제출\s*(일|시점|했나|됐나)|언제\s*(제출|접수|냈)")
# 2-hop 관계 질의. 1-hop(그냥 종목 언급 찾기)은 search_documents의 entity_key 필터로
# 충분하므로, 이 힌트는 "그 다음에" 무엇이 나왔는지를 묻는 질문에만 걸리게 좁힌다.
_GRAPH_HINT = re.compile(
    r"또\s*무엇을?\s*언급|함께\s*언급|같이\s*언급|관련\s*종목|연관\s*종목|어떤\s*종목.*(함께|같이)")


@dataclass
class Trace:
    step: str
    detail: str


@dataclass
class RouteResult:
    tool: str
    result: ToolResult
    trace: list[Trace] = field(default_factory=list)
    retrieval_needed: bool = True
    # DocumentSearchTool이 근거 커버리지 부족을 판단했을 때만 True. 다른 도구는 이
    # 개념이 없어 기본값 False다.
    escalate: bool = False


class Router:
    def __init__(self, bundle: Path, chunk_db: Path, structured_db: Path,
                 policy: RetrievalPolicy | None = None,
                 vector_index: VectorIndex | None = None,
                 encoder: Encoder | None = None,
                 exclude_status: Sequence[str] = DEFAULT_EXCLUDE_STATUS):
        """Hybrid Search는 선택적이다.

        `vector_index`/`encoder`를 둘 다 주면 `search_documents`가 BM25 + 벡터를 함께
        쓴다. 둘 중 하나라도 없으면 BM25 단독이다 - Router가 스스로 임베딩 모델을
        로딩하지 않는 이유는, 그 로딩(모델 다운로드·GPU 선택 등)의 책임을 호출부
        (CLI 스크립트)에 남겨 두는 것이 이 클래스를 테스트하기 쉽게 만들기 때문이다.
        """
        lex = EntityLexicon(bundle)
        index = Bm25Index(chunk_db, korean_ngram=True, metadata_boost=True,
                          korean_keep_word=True)
        self.policy = policy or RetrievalPolicy()
        self.docs = DocumentSearchTool(index, lex, vector_index=vector_index, encoder=encoder,
                                       policy=self.policy, exclude_status=exclude_status)
        self.filings = FilingLookupTool(structured_db, lex)
        self.holdings = HoldingsTool(structured_db)
        self.graph = GraphTool(index, lex)

    def tools(self) -> list[Tool]:
        """모델에 bind할 때 넘길 도구 목록. 지금은 규칙이 고르지만 형태는 같다."""
        return [self.docs.as_tool(), self.filings.as_tool(), self.holdings.as_tool(),
                self.graph.as_tool()]

    @staticmethod
    def needs_retrieval(query: str) -> bool:
        return not bool(_NO_RETRIEVAL.match(query))

    @staticmethod
    def route(query: str) -> str:
        if _HOLDINGS_HINT.search(query):
            return "query_holdings"
        if _CATALOG_HINT.search(query):
            return "lookup_filing"
        if _GRAPH_HINT.search(query):
            return "graph_traverse"
        return "search_documents"

    def answer(self, query: str) -> RouteResult:
        trace: list[Trace] = []
        if not self.needs_retrieval(query):
            trace.append(Trace("skip_retrieval", "검색이 필요 없는 질문으로 판단"))
            return RouteResult("none", ToolResult(True, answer="(검색 없이 응답)"),
                               trace, retrieval_needed=False)

        chosen = self.route(query)
        trace.append(Trace("route", f"`{chosen}` 선택"))
        runner = {"query_holdings": self.holdings.run,
                  "lookup_filing": self.filings.run,
                  "search_documents": self.docs.run,
                  "graph_traverse": self.graph.run}[chosen]
        res = runner(query)
        trace.append(Trace("run_tool", res.answer or f"근거 {len(res.evidence)}건"))

        # 전용 도구가 실패하면 문서 검색으로 폴백한다. 라우팅이 틀렸을 때의 안전망이다.
        if not res.ok and chosen != "search_documents":
            trace.append(Trace("fallback", "전용 도구 실패, `search_documents`로 재시도"))
            res = self.docs.run(query)
            chosen = "search_documents"

        if not res.ok or len(res.evidence) < self.policy.min_evidence:
            trace.append(Trace("stop", "근거가 부족해 중단합니다. 사람 확인이 필요합니다"))
        return RouteResult(chosen, res, trace, escalate=res.escalate)
