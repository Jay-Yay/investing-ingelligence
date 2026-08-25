from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from investor_intel.indexing.bm25_index import Bm25Index, Hit
from investor_intel.indexing.tokenizer import tokenize

# 맨 숫자 4자리를 연도로 보면 안 된다. 이 코퍼스에는 금액·수량·계좌번호에 4자리 숫자가
# 널려 있어서, 실측에서 오탐 연도 슬롯 하나 때문에 자동 평가셋 636건 중 50건의 정답이
# 통째로 사라졌다(필터가 걸리는 순간 정답 문서가 후보에서 제외된다).
# 연도 신호가 명시된 경우에만 기간 슬롯을 만든다.
_YEAR = re.compile(
    r"(?:(19[89]\d|20[0-4]\d)\s*년"          # 2003년
    r"|FY\s?(19[89]\d|20[0-4]\d)"            # FY2024
    r"|(19[89]\d|20[0-4]\d)\s*(?:Q[1-4]|[1-4]\s*분기)"   # 2024 Q1 / 2024 3분기
    r")", re.I)
_QUARTER = re.compile(r"([1-4])\s*분기|Q([1-4])", re.I)

# 질의에 나타나는 표현 -> OKF concept type. 4주차 자료의 '질문 유형에 맞는 인덱스를
# 고른다'를 어휘 규칙으로 옮긴 것이다.
_TYPE_HINTS = [
    (re.compile(r"공시|보고서|사업보고서|분기보고서|반기보고서|접수번호"), ["DartFiling", "SecFiling"]),
    (re.compile(r"13F|보유\s*현황|포트폴리오\s*(비중|편입)"), ["HoldingsSnapshot"]),
    (re.compile(r"리포트|리서치|목표주가|투자의견"), ["ResearchNote", "MarketCommentary"]),
]


@dataclass
class QueryPlan:
    """질의에서 뽑아낸 메타데이터 슬롯.

    OKF 번들이 entities/period/type을 확정값으로 갖고 있어야 이 슬롯들이 의미가 있다.
    지식 레이어 없이 같은 일을 하려면 매 질의마다 본문을 다시 해석해야 한다.
    """

    text: str
    entity_key: str | None = None
    entity_name: str | None = None
    period_year: str | None = None
    okf_types: list[str] = field(default_factory=list)
    analyst_house: str | None = None

    def describe(self) -> str:
        bits = []
        if self.entity_name:
            bits.append(f"entity={self.entity_name}({self.entity_key})")
        if self.analyst_house:
            bits.append(f"analyst_house={self.analyst_house}(필터 아님)")
        if self.period_year:
            bits.append(f"year={self.period_year}")
        if self.okf_types:
            bits.append(f"type∈{{{','.join(self.okf_types)}}}")
        return " · ".join(bits) or "(슬롯 없음)"


# OKF 번들이 '분석 주체'와 '분석 대상'을 이미 분리해 뒀는데, 질의 해석기가 그 구분을
# 모르면 "교보증권이 제시한 에이피알 목표주가"에서 교보증권을 대상 종목으로 잡는다.
# 그러면 에이피알 리포트가 후보에서 통째로 빠진다(실측: 추적 A에서 정답 소실).
_ANALYST_HOUSE = re.compile(r"(증권|투자증권|자산운용|캐피탈|금융투자)$")


class EntityLexicon:
    """OKF 번들의 companies/ 디렉터리를 그대로 질의 해석 사전으로 쓴다."""

    def __init__(self, bundle: Path):
        self.by_name: dict[str, tuple[str, str]] = {}
        for p in (bundle / "companies").glob("*.md"):
            if p.name == "index.md":
                continue
            head = p.read_text(encoding="utf-8").split("---", 2)
            if len(head) < 3:
                continue
            fm = yaml.safe_load(head[1]) or {}
            name = str(fm.get("title") or "").strip()
            if len(name) < 2:
                continue
            self.by_name[name] = (p.stem, name)
            # 영문 사명은 사용자가 법인 형태(Group N.V., Inc., Corp)까지 쓰지 않는다.
            # 앞쪽 1~2 단어를 별칭으로 등록해 'Nebius'로도 잡히게 한다.
            words = re.findall(r"[A-Za-z][A-Za-z0-9&.\-]*", name)
            for n_words in (2, 1):
                if len(words) > n_words:
                    alias = " ".join(words[:n_words])
                    if len(alias) >= 4:
                        self.by_name.setdefault(alias, (p.stem, name))

    def find_all(self, text: str) -> list[tuple[str, str]]:
        """질의에 등장하는 등록 엔티티를 전부, 긴 이름 우선으로 돌려준다."""
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for name in sorted(self.by_name, key=len, reverse=True):
            if name in text:
                key, canonical = self.by_name[name]
                if key not in seen:
                    seen.add(key)
                    out.append((key, canonical))
        return out

    def find(self, text: str) -> tuple[str, str] | None:
        """대상 종목 하나. 증권사·운용사 이름은 대상이 아니라 발행 주체이므로 건너뛴다."""
        hits = self.find_all(text)
        for key, name in hits:
            if not _ANALYST_HOUSE.search(name):
                return key, name
        return None


def plan_query(query: str, lex: EntityLexicon) -> QueryPlan:
    plan = QueryPlan(text=query)
    all_hits = lex.find_all(query)
    houses = [n for _, n in all_hits if _ANALYST_HOUSE.search(n)]
    if houses:
        plan.analyst_house = houses[0]
        # 증권사 이름이 나왔다는 것 자체가 '리서치를 찾는다'는 신호다.
        plan.okf_types = ["ResearchNote", "MarketCommentary"]
    hit = lex.find(query)
    if hit:
        plan.entity_key, plan.entity_name = hit
    y = _YEAR.search(query)
    if y:
        plan.period_year = next(g for g in y.groups() if g)
    if not plan.okf_types:
        for pat, types in _TYPE_HINTS:
            if pat.search(query):
                plan.okf_types = types
                break
    return plan


def _coverage(query: str, hits: list[Hit], top: int = 5) -> float:
    """검색 결과가 질의를 얼마나 덮는지의 결정론적 대용치.

    LangGraph 튜토리얼의 grade_documents는 LLM에게 yes/no를 시킨다. 여기서는 LLM 없이
    '질의 토큰 중 상위 결과가 실제로 포함한 비율'을 쓴다. LLM Grader보다 무디지만
    두 가지 장점이 있다: 비용이 0이고, 같은 입력에 항상 같은 판정을 준다.
    대신 의미는 같은데 표현이 다른 근거는 관련 없다고 잘못 판정한다 - 이 한계가
    그대로 재검색 루프의 상한이 된다.
    """
    q = {t for t in tokenize(query) if len(t) >= 2}
    if not q:
        return 0.0
    seen: set[str] = set()
    for h in hits[:top]:
        seen |= {t for t in tokenize(f"{h.title} {h.text}") if len(t) >= 2}
    return len(q & seen) / len(q)


@dataclass
class Step:
    action: str
    detail: str
    n_results: int
    coverage: float


@dataclass
class RetrievalResult:
    hits: list[Hit]
    steps: list[Step]
    plan: QueryPlan


class AdaptiveRetriever:
    """메타데이터 프리필터 + 실패 시 완화·재작성 루프.

    Agentic RAG 서베이의 Adaptive(질의에 따라 검색 전략을 고름)와 Corrective(결과를
    평가해 스스로 고침) 패턴을 LLM 없이 결정론적 규칙으로 구현한 것이다. 판단 주체가
    LLM이 아니므로 '에이전트'라고 부르지는 않는다 - 통제 흐름만 같은 모양이다.
    """

    def __init__(self, index: Bm25Index, lex: EntityLexicon, *, grade_threshold: float = 0.45,
                 max_steps: int = 3):
        self.index = index
        self.lex = lex
        self.grade_threshold = grade_threshold
        self.max_steps = max_steps

    def search(self, query: str, k: int = 10, *, use_plan: bool = True,
               adaptive: bool = True) -> RetrievalResult:
        plan = plan_query(query, self.lex) if use_plan else QueryPlan(text=query)
        steps: list[Step] = []

        filters: dict = {}
        if use_plan:
            if plan.entity_key:
                filters["entity_key"] = plan.entity_key
            if plan.period_year:
                filters["period_year"] = plan.period_year
            if plan.okf_types:
                filters["okf_types"] = plan.okf_types

        hits = self.index.search_documents(query, k=k, **filters)
        cov = _coverage(query, hits)
        steps.append(Step("retrieve", f"필터 {plan.describe() if use_plan else '없음'}",
                          len(hits), round(cov, 3)))
        if not adaptive:
            return RetrievalResult(hits, steps, plan)

        # 1차 완화: 결과가 없거나 근거 커버리지가 낮으면 가장 좁은 슬롯부터 푼다.
        order = ["okf_types", "period_year", "entity_key"]
        while (len(hits) < 3 or cov < self.grade_threshold) and len(steps) < self.max_steps:
            dropped = None
            for key in order:
                if key in filters:
                    dropped = key
                    filters.pop(key)
                    break
            if dropped is None:
                break
            hits = self.index.search_documents(query, k=k, **filters)
            cov = _coverage(query, hits)
            steps.append(Step("relax_filter", f"`{dropped}` 필터 해제", len(hits), round(cov, 3)))

        # 2차: 그래도 부족하면 질의를 재작성한다(엔티티 정식 명칭을 덧붙이고 흔한 조각을 뺀다).
        if cov < self.grade_threshold and len(steps) < self.max_steps:
            rewritten = self._rewrite(query, plan)
            if rewritten != query:
                h2 = self.index.search_documents(rewritten, k=k, **filters)
                c2 = _coverage(rewritten, h2)
                steps.append(Step("rewrite_query", f"→ “{rewritten}”", len(h2), round(c2, 3)))
                if c2 > cov:
                    hits, cov = h2, c2
        return RetrievalResult(hits, steps, plan)

    def _rewrite(self, query: str, plan: QueryPlan) -> str:
        """LangGraph의 rewrite_question 자리. LLM 대신 슬롯을 근거로 질의를 다시 쓴다."""
        parts = [query]
        if plan.entity_name and plan.entity_name not in query:
            parts.append(plan.entity_name)
        # 조사만 남은 1글자 한글 토큰과 흔한 서술어는 검색어로서 값이 없다
        cleaned = " ".join(w for w in query.split()
                           if not re.fullmatch(r"[가-힣]{1}", w)
                           and w not in ("얼마", "무엇", "어떻게", "어디", "언제", "왜", "인가", "뭐야"))
        if cleaned and cleaned != query:
            parts = [cleaned] + parts[1:]
        return " ".join(dict.fromkeys(parts)).strip()
