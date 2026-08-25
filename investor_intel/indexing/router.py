from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from investor_intel.indexing.bm25_index import Bm25Index
from investor_intel.indexing.retrieval import EntityLexicon
from investor_intel.indexing.tools import (
    DocumentSearchTool, FilingLookupTool, HoldingsTool, Tool, ToolResult)

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


@dataclass
class RetrievalPolicy:
    """4주차 §12가 말한 '운영 시 필요한 추가 통제'를 값으로 박아 둔 것.

    루프를 도는 코드에 이 숫자들이 흩어져 있으면 나중에 무엇이 상한인지 알 수 없다.
    """

    max_retries: int = 2                 # 최대 재검색 횟수
    forbid_repeat_query: bool = True     # 동일한 검색 반복 방지
    min_evidence: int = 1                # 근거가 이보다 적으면 중단
    escalate_to_human_below: float = 0.2 # 근거 커버리지가 이 밑이면 사람에게 넘김
    max_latency_ms: int = 3000           # 지연시간 상한


class Router:
    def __init__(self, bundle: Path, chunk_db: Path, structured_db: Path,
                 policy: RetrievalPolicy | None = None):
        lex = EntityLexicon(bundle)
        index = Bm25Index(chunk_db, korean_ngram=True, metadata_boost=True,
                          korean_keep_word=True)
        self.docs = DocumentSearchTool(index, lex)
        self.filings = FilingLookupTool(structured_db, lex)
        self.holdings = HoldingsTool(structured_db)
        self.policy = policy or RetrievalPolicy()

    def tools(self) -> list[Tool]:
        """모델에 bind할 때 넘길 도구 목록. 지금은 규칙이 고르지만 형태는 같다."""
        return [self.docs.as_tool(), self.filings.as_tool(), self.holdings.as_tool()]

    @staticmethod
    def needs_retrieval(query: str) -> bool:
        return not bool(_NO_RETRIEVAL.match(query))

    @staticmethod
    def route(query: str) -> str:
        if _HOLDINGS_HINT.search(query):
            return "query_holdings"
        if _CATALOG_HINT.search(query):
            return "lookup_filing"
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
                  "search_documents": self.docs.run}[chosen]
        res = runner(query)
        trace.append(Trace("run_tool", res.answer or f"근거 {len(res.evidence)}건"))

        # 전용 도구가 실패하면 문서 검색으로 폴백한다. 라우팅이 틀렸을 때의 안전망이다.
        if not res.ok and chosen != "search_documents":
            trace.append(Trace("fallback", "전용 도구 실패, `search_documents`로 재시도"))
            res = self.docs.run(query)
            chosen = "search_documents"

        if not res.ok or len(res.evidence) < self.policy.min_evidence:
            trace.append(Trace("stop", "근거가 부족해 중단합니다. 사람 확인이 필요합니다"))
        return RouteResult(chosen, res, trace)
