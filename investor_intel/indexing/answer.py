"""검색 결과를 인용 강제 형태로 감싼다 — Generation 자리의 규칙 기반 게이트.

## 왜 LLM을 호출하지 않는가

노션 문서의 Generation 단계("근거만 사용하고 출처를 표시하며, 정보가 없으면 없다고
답한다")는 자연어 생성을 전제하지만, 이 저장소의 검색 계층은 판단 주체를 규칙으로 두는
것이 설계 원칙이다(`router.py` 서두 참고 — "판단 주체가 LLM이 아니라 규칙"). 이 모듈에
LLM 호출을 넣으면 그 원칙이 깨지고, 이 프로젝트의 로컬 실행 환경(API 키 없이 Claude
Code가 직접 vault를 읽는 방식)과도 어긋난다.

그래서 여기서 강제하는 것은 "자연어 답을 예쁘게 만드는 것"이 아니라 **"근거 없이는
답 구조 자체를 만들 수 없다"**와 **"출처 표시 없는 인용은 없다"**를 데이터 구조로
강제하는 것이다. Router는 지금까지 `ToolResult`만 돌려주고 그 안의 `text`는
호출부가 알아서 잘라 쓰거나 통째로 무시할 수 있었다 - 브리핑을 쓸 때 검색 계층을
우회해 vault를 직접 읽는 습관이 거기서 나온다. `AnswerBundle`을 거치면 그 우회가
구조적으로 어색해진다: 인용 가능 여부(`citable`)를 확인하지 않고 본문을 쓸 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from investor_intel.indexing.router import RouteResult

# 이 상태의 근거는 본문을 그대로 인용하면 안 된다. corrupt는 문자열 자체가 손상됐고,
# stub은 본문이 아예 없다(제목·링크만 있는 자리표시자).
_NOT_CITABLE_STATUS = {"corrupt", "stub"}


@dataclass
class Citation:
    """근거 한 건. `citable=False`면 본문을 인용하지 말고 링크만 제시해야 한다."""

    doc_id: str
    title: str
    excerpt: str
    status: str = ""
    doc_path: str = ""

    @property
    def citable(self) -> bool:
        return self.status not in _NOT_CITABLE_STATUS

    def render(self, index: int) -> str:
        if self.citable:
            return f"[{index}] {self.title} — {self.excerpt}"
        reason = "본문 손상" if self.status == "corrupt" else "본문 미확보"
        location = f" ({self.doc_path})" if self.doc_path else ""
        return f"[{index}] {self.title} ({reason} - 원문 확인 필요{location})"


@dataclass
class AnswerBundle:
    """Router 응답을 인용 강제 형태로 감싈 것.

    `insufficient_evidence`가 True면 `render()`가 근거를 하나도 출력하지 않는다 -
    CLAUDE.md의 "정보 부족 시 질문 생성 중지, 역질문" 규칙을 코드 레벨에서 강제하는
    지점이다. 이 필드를 확인하지 않고 `direct_answer`나 `citations`를 직접 조립하면
    그 강제를 우회하게 된다 - 소비자는 항상 `render()`를 거치거나 최소한 이 필드를
    먼저 확인해야 한다.
    """

    query: str
    tool: str
    direct_answer: str | None = None
    citations: list[Citation] = field(default_factory=list)
    note: str | None = None
    insufficient_evidence: bool = False
    needs_human_review: bool = False

    @property
    def citable_citations(self) -> list[Citation]:
        return [c for c in self.citations if c.citable]

    def render(self) -> str:
        if self.insufficient_evidence:
            return f"정보 부족: {self.note or '근거를 찾지 못했습니다.'}"
        lines: list[str] = []
        if self.direct_answer:
            lines.append(self.direct_answer)
        lines += [c.render(i) for i, c in enumerate(self.citations, 1)]
        if self.needs_human_review:
            lines.append("(근거 커버리지가 낮습니다 - 사람 확인을 권장합니다)")
        if self.note:
            lines.append(f"주의: {self.note}")
        return "\n".join(lines)


def build_answer_bundle(query: str, result: "RouteResult") -> AnswerBundle:
    """`Router.answer()`의 결과를 인용 강제 형태로 옮긴다.

    근거가 하나도 없거나(`not res.ok`) 근거 전부가 인용 불가(corrupt/stub)면
    `insufficient_evidence=True`로 표시한다 - "있지만 못 읽는다"와 "찾았고 인용할 수
    있다"를 구분하지 않으면, 손상된 근거 하나만으로도 "찾았습니다"라고 답하게 된다.
    """
    res = result.result
    citations = [
        Citation(
            doc_id=str(evidence.get("doc_id") or evidence.get("concept_id") or ""),
            title=str(evidence.get("title") or evidence.get("investor") or ""),
            excerpt=str(evidence.get("text") or "")[:200],
            status=str(evidence.get("status") or ""),
            doc_path=str(evidence.get("doc_path") or ""),
        )
        for evidence in res.evidence
    ]
    has_citable_evidence = any(c.citable for c in citations)
    insufficient = not res.ok or (bool(citations) and not has_citable_evidence)
    return AnswerBundle(
        query=query, tool=result.tool, direct_answer=res.answer, citations=citations,
        note=res.note, insufficient_evidence=insufficient,
        needs_human_review=result.escalate,
    )
