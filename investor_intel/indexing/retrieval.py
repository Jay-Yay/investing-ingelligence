from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import yaml

from investor_intel.indexing.bm25_index import Bm25Index, Hit
from investor_intel.indexing.tokenizer import tokenize

if TYPE_CHECKING:
    from investor_intel.indexing.embedding import Encoder
    from investor_intel.indexing.vector_index import VectorIndex

# corrupt 문서는 capture_mode='full'이면서 본문만 깨진 상태라 그것만으로는 걸러낼 수
# 없다(2026-08-25 이전에는 Hit에 okf_status가 실려 있지도 않았다 - 검색 결과에서 corrupt
# 여부 자체를 알 수 없었다). stub/superseded는 기본으로 지우지 않는다 - V4 사건(본문 없는
# 문서를 지웠다가 식별자 질의 정확도가 0.993→0.340으로 무너짐)의 교훈이 stub에 그대로
# 적용된다.
DEFAULT_EXCLUDE_STATUS: tuple[str, ...] = ("corrupt",)

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
    # 근거 커버리지가 policy.escalate_to_human_below 밑이면 True. Router/Tool이 이 값을
    # 보고 "자신 있게 틀린 답"을 내는 대신 사람 확인이 필요하다는 신호를 낼 수 있다.
    escalate: bool = False


@dataclass
class RetrievalPolicy:
    """4주차 §12가 말한 '운영 시 필요한 추가 통제'를 값으로 박아 둔 것.

    루프를 도는 코드에 이 숫자들이 흩어져 있으면 나중에 무엇이 상한인지 알 수 없다.
    AdaptiveRetriever.search()가 다섯 필드를 모두 실제로 강제한다 - 예전에는 이 클래스가
    router.py에 선언만 돼 있었고 min_evidence 하나만 Router에서 읽혔다.
    """

    max_retries: int = 2                 # 최대 재검색 횟수 (완화·재작성·상태해제 합산)
    forbid_repeat_query: bool = True     # 동일한 (질의, 필터) 조합 반복 방지
    min_evidence: int = 1                # 근거가 이보다 적으면 중단
    escalate_to_human_below: float = 0.2 # 근거 커버리지가 이 밑이면 사람에게 넘김
    max_latency_ms: int = 3000           # 지연시간 상한


class SearchBackend(Protocol):
    """`Bm25Index`와 `HybridSearcher`가 함께 만족하는 인터페이스.

    AdaptiveRetriever는 둘 중 어느 쪽을 받았는지 몰라도 된다 - Hybrid를 실제 질의
    경로에 연결하는 지점이 여기다. HybridSearcher.search_documents는 hybrid.py에서
    Bm25Index와 이름을 맞추기 위해 별칭으로 추가했다.
    """

    def search_documents(self, query: str, k: int = 10, **filters: Any) -> list[Any]: ...


class AdaptiveRetriever:
    """메타데이터 프리필터 + 실패 시 완화·재작성 루프.

    Agentic RAG 서베이의 Adaptive(질의에 따라 검색 전략을 고름)와 Corrective(결과를
    평가해 스스로 고침) 패턴을 LLM 없이 결정론적 규칙으로 구현한 것이다. 판단 주체가
    LLM이 아니므로 '에이전트'라고 부르지는 않는다 - 통제 흐름만 같은 모양이다.
    """

    def __init__(self, index: Bm25Index, lex: EntityLexicon, *,
                 vector_index: VectorIndex | None = None,
                 encoder: Encoder | None = None,
                 hybrid_kwargs: dict | None = None,
                 grade_threshold: float = 0.45,
                 policy: RetrievalPolicy | None = None,
                 exclude_status: Sequence[str] = DEFAULT_EXCLUDE_STATUS):
        self.index = index
        self.lex = lex
        self.grade_threshold = grade_threshold
        self.policy = policy or RetrievalPolicy()
        self.exclude_status = tuple(exclude_status)
        # vector_index/encoder를 둘 다 받았을 때만 Hybrid로 동작한다. 둘 중 하나라도
        # 없으면 BM25 단독으로 조용히 되돌아간다 - 벡터 인덱스가 아직 없는 환경에서도
        # 이 클래스는 그대로 동작해야 한다.
        self.backend: SearchBackend = index
        if vector_index is not None and encoder is not None:
            from investor_intel.indexing.hybrid import HybridSearcher
            self.backend = HybridSearcher(index, vector_index, encoder, **(hybrid_kwargs or {}))

    @property
    def vector_enabled(self) -> bool:
        return self.backend is not self.index

    @property
    def max_steps(self) -> int:
        return self.policy.max_retries + 1

    def _search(self, query: str, k: int, filters: dict, tried: set[tuple]) -> list | None:
        """`forbid_repeat_query`를 강제한다. 이미 시도한 (질의, 필터) 조합이면 None."""
        sig = (query, tuple(sorted(
            (key, tuple(value) if isinstance(value, (list, tuple)) else value)
            for key, value in filters.items()
        )))
        if self.policy.forbid_repeat_query and sig in tried:
            return None
        tried.add(sig)
        return self.backend.search_documents(query, k=k, **filters)

    def search(self, query: str, k: int = 10, *, use_plan: bool = True,
               adaptive: bool = True) -> RetrievalResult:
        start = time.monotonic()
        plan = plan_query(query, self.lex) if use_plan else QueryPlan(text=query)
        steps: list[Step] = []
        tried: set[tuple] = set()

        filters: dict = {}
        if self.exclude_status:
            filters["exclude_status"] = self.exclude_status
        if use_plan:
            if plan.entity_key:
                filters["entity_key"] = plan.entity_key
            if plan.period_year:
                filters["period_year"] = plan.period_year
            if plan.okf_types:
                filters["okf_types"] = plan.okf_types

        hits = self._search(query, k, filters, tried) or []
        cov = _coverage(query, hits)
        steps.append(Step("retrieve", f"필터 {plan.describe() if use_plan else '없음'}",
                          len(hits), round(cov, 3)))
        if not adaptive:
            return self._finish(hits, steps, plan)

        def _timed_out() -> bool:
            elapsed = (time.monotonic() - start) * 1000
            if elapsed <= self.policy.max_latency_ms:
                return False
            steps.append(Step("timeout",
                f"{self.policy.max_latency_ms}ms 초과 - 중단", len(hits), round(cov, 3)))
            return True

        # 1차 완화: 결과가 없거나 근거 커버리지가 낮으면 가장 좁은 슬롯부터 푼다.
        order = ["okf_types", "period_year", "entity_key"]
        while (len(hits) < 3 or cov < self.grade_threshold) and len(steps) < self.max_steps:
            if _timed_out():
                return self._finish(hits, steps, plan)
            dropped = next((key for key in order if key in filters), None)
            if dropped is None:
                break
            filters.pop(dropped)
            new_hits = self._search(query, k, filters, tried)
            if new_hits is None:
                continue  # 이미 시도한 조합 - 필터는 이미 뺐으니 다음 슬롯으로 넘어간다
            hits, cov = new_hits, _coverage(query, new_hits)
            steps.append(Step("relax_filter", f"`{dropped}` 필터 해제", len(hits), round(cov, 3)))

        # 2차: 그래도 부족하면 질의를 재작성한다(엔티티 정식 명칭을 덧붙이고 흔한 조각을 뺀다).
        if cov < self.grade_threshold and len(steps) < self.max_steps and not _timed_out():
            rewritten = self._rewrite(query, plan)
            if rewritten != query:
                h2 = self._search(rewritten, k, filters, tried)
                if h2 is not None:
                    c2 = _coverage(rewritten, h2)
                    steps.append(Step("rewrite_query", f"→ “{rewritten}”", len(h2), round(c2, 3)))
                    if c2 > cov:
                        hits, cov = h2, c2

        # 최후 수단: 그래도 근거가 전혀 없으면 corrupt 제외를 해제한다. 완전한 무응답보다
        # "있지만 못 읽는 문서가 있다"는 것을 아는 쪽이 낫다 - 다만 상태는 그대로 실려
        # 있으므로 소비자가 반드시 경고를 붙여야 한다(tools.py DocumentSearchTool 참고).
        if not hits and "exclude_status" in filters and len(steps) < self.max_steps:
            filters.pop("exclude_status")
            h3 = self._search(query, k, filters, tried)
            if h3:
                hits, cov = h3, _coverage(query, h3)
                steps.append(Step("relax_status_filter",
                    "근거가 전혀 없어 corrupt 제외를 해제함 - 결과에 손상된 문서가 섞일 수 있음",
                    len(hits), round(cov, 3)))

        return self._finish(hits, steps, plan, cov)

    def _finish(self, hits: list, steps: list[Step], plan: QueryPlan,
                cov: float | None = None) -> RetrievalResult:
        if cov is None:
            cov = steps[-1].coverage if steps else 0.0
        escalate = cov < self.policy.escalate_to_human_below
        if escalate:
            steps.append(Step("escalate",
                f"근거 커버리지 {cov:.2f} < {self.policy.escalate_to_human_below} - "
                "사람 확인이 필요합니다", len(hits), round(cov, 3)))
        return RetrievalResult(hits, steps, plan, escalate=escalate)

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
