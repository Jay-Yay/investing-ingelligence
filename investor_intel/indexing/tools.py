from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from investor_intel.indexing.bm25_index import Bm25Index
from investor_intel.indexing.retrieval import AdaptiveRetriever, EntityLexicon, plan_query

# ---------------------------------------------------------------------------
# 4주차 자료의 "Retriever를 Tool로 만드는 이유"를 그대로 옮긴 부분이다.
#
#   고정형 RAG   : 모든 질문 -> 항상 같은 검색 -> 답변
#   Tool로 제공  : 질문 -> 검색이 필요한가 판단 -> 어떤 도구를 쓸까 -> 결과가 충분한가
#
# 다만 판단 주체가 LLM이 아니라 규칙이다. LangGraph 튜토리얼이 모델에 도구를 bind해
# 모델이 tool_calls를 내게 하는 자리에, 여기서는 규칙이 도구를 고른다.
# 그래서 도구의 name/description은 지금 당장은 쓰이지 않지만, 나중에 모델에 그대로
# 넘길 수 있도록 같은 모양으로 정의해 둔다.
# ---------------------------------------------------------------------------


@dataclass
class Tool:
    name: str
    description: str          # 모델에 bind할 때 그대로 쓰는 설명
    parameters: dict          # JSON Schema
    run: Callable[..., "ToolResult"]


@dataclass
class ToolResult:
    ok: bool
    answer: str | None = None          # 도구가 값을 직접 계산한 경우
    evidence: list[dict] = field(default_factory=list)
    note: str | None = None            # 품질 경고 등
    tool: str = ""


# ---------------------------------------------------------------------------
# 1) 비정형 문서 검색 도구
# ---------------------------------------------------------------------------
class DocumentSearchTool:
    """4주차 표의 '비정형 문서 내용 -> Vector Store, BM25, Hybrid Search' 자리."""

    def __init__(self, index: Bm25Index, lex: EntityLexicon):
        self.retriever = AdaptiveRetriever(index, lex)

    def as_tool(self) -> Tool:
        return Tool(
            name="search_documents",
            description=(
                "공시·리서치·블로그·텔레그램 메시지의 본문에서 근거 문단을 찾는다. "
                "'무슨 이야기를 했는지', '왜 그렇게 봤는지' 같은 서술형 질문에 쓴다. "
                "숫자를 세거나 합계를 내는 질문에는 적합하지 않다."),
            parameters={"type": "object", "properties": {
                "query": {"type": "string", "description": "사용자 질문 원문"}},
                "required": ["query"]},
            run=self.run)

    def run(self, query: str, k: int = 10) -> ToolResult:
        res = self.retriever.search(query, k=k)
        ev = [{"doc_id": h.doc_id, "title": h.title, "text": h.text[:200],
               "status": h.okf_status} for h in res.hits[:5]]
        return ToolResult(ok=bool(ev), evidence=ev, tool="search_documents",
                          note=None if ev else "검색 결과가 없습니다")


# ---------------------------------------------------------------------------
# 2) 공시 카탈로그 조회 도구
# ---------------------------------------------------------------------------
_FILING_WORDS = ("사업보고서", "분기보고서", "반기보고서", "10-K", "10-Q", "20-F", "8-K", "13F")
# 사람이 쓰는 말과 공시 제목이 다르다. 질문의 표현을 공시 제목 쪽으로 옮겨 준다.
_FILING_SYNONYMS = {
    "연간보고서": "사업보고서", "연차보고서": "사업보고서", "결산보고서": "사업보고서",
    "애뉴얼리포트": "사업보고서", "annual report": "사업보고서",
}


class FilingLookupTool:
    """4주차 표의 '표 데이터 -> SQL Database' 중 공시 카탈로그 쪽.

    "접수번호가 뭐냐", "언제 제출됐냐" 같은 질문은 본문을 읽을 필요가 없다.
    카탈로그 한 줄을 정확히 집어 오면 끝이고, 그게 훨씬 정확하다.
    """

    def __init__(self, db_path: Path, lex: EntityLexicon):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.lex = lex

    def as_tool(self) -> Tool:
        return Tool(
            name="lookup_filing",
            description=(
                "특정 회사가 특정 연도에 낸 공시 한 건의 접수번호·제출일·원문 링크를 찾는다. "
                "'접수번호', '제출 시점', '언제 냈나' 같은 질문에 쓴다."),
            parameters={"type": "object", "properties": {
                "company": {"type": "string"}, "year": {"type": "string"},
                "filing_type": {"type": "string"}}, "required": ["company"]},
            run=self.run)

    def run(self, query: str) -> ToolResult:
        plan = plan_query(query, self.lex)
        if not plan.entity_key:
            return ToolResult(False, note="질문에서 회사를 찾지 못했습니다", tool="lookup_filing")
        wanted = [w for w in _FILING_WORDS if w in query]
        wanted += [v for k, v in _FILING_SYNONYMS.items() if k.lower() in query.lower()]
        wanted = list(dict.fromkeys(wanted))
        # "2013사업연도 연간보고서"는 2013년에 낸 공시가 아니라 2013 회계연도를 다룬 공시다.
        # DART는 filing_type에 "사업보고서 (2013.12)"처럼 대상 기간을 적어 두므로 그걸 쓴다.
        wants_fiscal = bool(re.search(r"사업연도|회계연도|결산|연간보고서|FY", query, re.I))
        # "2013사업연도" 처럼 '년'이 없는 표기도 여기서는 연도로 본다.
        year = plan.period_year or (re.search(r"(19|20)\d{2}", query).group(0)
                                    if re.search(r"(19|20)\d{2}", query) else None)
        sql = "SELECT * FROM filings WHERE entity_key = ?"
        params: list[Any] = [plan.entity_key]
        if year:
            if wants_fiscal:
                # 대상 기간은 filing_type 괄호 안의 "(2013.12)" 로만 판단한다.
                # DART 문서의 reporting_period 는 접수일이 들어가 있는 경우가 많아
                # 회계연도 기준으로 믿을 수 없다(실측으로 확인).
                sql += " AND filing_type LIKE ?"
                params.append(f"%({year}.%")
            else:
                sql += " AND (pub_year = ? OR fiscal_year = ?)"
                params += [year, year]
        if wanted:
            sql += " AND (" + " OR ".join("filing_type LIKE ?" for _ in wanted) + ")"
            params += [f"%{w}%" for w in wanted]
        rows = self.conn.execute(sql + " ORDER BY published LIMIT 5", params).fetchall()
        if not rows:
            return ToolResult(False, note="조건에 맞는 공시가 없습니다", tool="lookup_filing")
        r = rows[0]
        return ToolResult(
            True,
            answer=f"{r['entity']} {r['filing_type']} · 접수번호 {r['native_id']} · 제출일 {r['published']}",
            evidence=[{"doc_id": x["concept_id"], "title": x["title"],
                       "native_id": x["native_id"], "published": x["published"]} for x in rows],
            tool="lookup_filing",
            note=("조건에 맞는 공시가 여러 건이라 가장 이른 것을 골랐습니다"
                  if len(rows) > 1 else None))


# ---------------------------------------------------------------------------
# 3) 13F 보유 현황 집계 도구
# ---------------------------------------------------------------------------
_METRICS = [
    ("count", re.compile(r"종목\s*(개수|수)|몇\s*종목|편입\s*종목")),
    ("top_weight", re.compile(r"최대\s*비중|가장\s*(큰|많은)\s*비중|1위\s*종목|비중\s*(1위|최대)")),
    ("top5", re.compile(r"상위\s*5|쏠림|집중도")),
    ("total", re.compile(r"총\s*(보유|평가|보고)|보유\s*규모|운용\s*규모|전체\s*규모")),
]
_QUARTER = re.compile(r"(20\d{2})\s*년?\s*([1-4])\s*분기|(20\d{2})[-\s]?Q([1-4])", re.I)
_MONTH_END = re.compile(r"(20\d{2})\s*년?\s*(\d{1,2})\s*월\s*말")


class HoldingsTool:
    """4주차 표의 '매출·건수·상태 등 표 데이터 -> SQL Database, Text-to-SQL' 자리.

    "보유 종목이 몇 개냐"는 문서를 아무리 잘 찾아도 답이 안 나온다. 세는 연산이
    필요하기 때문이다. 표를 표로 저장해 두면 SQL 한 줄이면 된다.
    """

    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def as_tool(self) -> Tool:
        return Tool(
            name="query_holdings",
            description=(
                "기관투자자의 13F 보유 현황을 집계한다. 보유 종목 개수, 총 보유 규모, "
                "최대 비중 종목, 상위 5종목 집중도를 계산해서 숫자로 답한다."),
            parameters={"type": "object", "properties": {
                "investor": {"type": "string"},
                "as_of": {"type": "string", "description": "2025-Q4 형태"},
                "metric": {"type": "string",
                           "enum": ["count", "total", "top_weight", "top5"]}},
                "required": ["investor", "metric"]},
            run=self.run)

    def _find_snapshot(self, query: str) -> sqlite3.Row | None:
        rows = self.conn.execute(
            "SELECT DISTINCT investor_key, investor FROM snapshots").fetchall()
        hit = None
        for r in rows:
            # '베일리기포드', '듀케인', '드러켄밀러' 같은 한글 표기를 영문 사명에 잇는다
            for token in re.findall(r"[가-힣A-Za-z]{3,}", query):
                if token.lower() in r["investor"].lower().replace(" ", ""):
                    hit = r
                    break
            if hit:
                break
        if hit is None:
            for r in rows:
                for ko, en in _INVESTOR_ALIASES.items():
                    if ko in query and en.lower() in r["investor"].lower():
                        hit = r
                        break
                if hit:
                    break
        if hit is None:
            return None
        sql = "SELECT * FROM snapshots WHERE investor_key = ?"
        params: list[Any] = [hit["investor_key"]]
        q = _QUARTER.search(query)
        if q:
            y = q.group(1) or q.group(3)
            n = q.group(2) or q.group(4)
            sql += " AND as_of = ?"
            params.append(f"{y}-Q{n}")
        else:
            m = _MONTH_END.search(query)
            if m:
                y, mm = m.group(1), int(m.group(2))
                sql += " AND as_of = ?"
                params.append(f"{y}-Q{(mm - 1) // 3 + 1}")
            else:
                yy = re.search(r"(20\d{2})", query)
                if yy:
                    sql += " AND as_of LIKE ?"
                    params.append(f"{yy.group(1)}-%")
        return self.conn.execute(sql + " ORDER BY published DESC LIMIT 1", params).fetchone()

    def run(self, query: str) -> ToolResult:
        snap = self._find_snapshot(query)
        if snap is None:
            return ToolResult(False, note="해당 기관·기간의 13F 스냅샷을 찾지 못했습니다",
                              tool="query_holdings")
        metric = next((m for m, pat in _METRICS if pat.search(query)), "count")
        note = None
        if snap["truncated"]:
            note = (f"이 스냅샷은 보고서가 밝힌 보유 종목 {snap['reported_count']}개 중 "
                    f"{snap['captured_rows']}개만 본문 표에 저장돼 있습니다. "
                    f"개수·총액은 보고서 머리글 값을, 종목별 순위는 확보된 행만 사용합니다.")
        ev = [{"concept_id": snap["concept_id"], "investor": snap["investor"],
               "as_of": snap["as_of"], "published": snap["published"]}]

        if metric == "count":
            return ToolResult(True, f"{snap['investor']} {snap['as_of']} 보유 종목 "
                                    f"{snap['reported_count']}개", ev, note, "query_holdings")
        if metric == "total":
            return ToolResult(True, f"{snap['investor']} {snap['as_of']} 총 보고 가치 "
                                    f"{snap['total_value_k']:,}천 달러", ev, note, "query_holdings")
        if metric == "top5":
            return ToolResult(True, f"{snap['investor']} {snap['as_of']} 상위 5종목 집중도 "
                                    f"{snap['top5_pct']}%", ev, note, "query_holdings")
        row = self.conn.execute(
            "SELECT security, weight_pct, value_k FROM holdings WHERE concept_id = ? "
            "ORDER BY weight_pct DESC LIMIT 1", (snap["concept_id"],)).fetchone()
        if row is None:
            return ToolResult(False, note="표에 종목 행이 없습니다", tool="query_holdings")
        return ToolResult(True, f"{snap['investor']} {snap['as_of']} 최대 비중 종목은 "
                                f"{row['security']} ({row['weight_pct']}%)", ev, note, "query_holdings")


_INVESTOR_ALIASES = {
    "베일리기포드": "baillie", "베일리 기포드": "baillie",
    "듀케인": "duquesne", "드러켄밀러": "duquesne",
    "퍼싱스퀘어": "pershing", "퍼싱 스퀘어": "pershing",
    "오크트리": "oaktree", "블랙록": "blackrock",
}
