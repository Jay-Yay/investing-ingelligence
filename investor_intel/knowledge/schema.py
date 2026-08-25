from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import yaml

# OKF는 concept 파일마다 `type` 하나만 요구한다. 나머지는 관례이므로, 이 코퍼스의
# 지식 단위를 여섯 종류로 나눈다. 원본 source_type을 그대로 쓰지 않는 이유는,
# 지식 레이어의 타입은 '수집 경로'가 아니라 '무엇에 대한 지식인가'여야 하기 때문이다.
ConceptType = Literal[
    "Company",           # 종목 자체 (종목코드/티커로 식별되는 관계 허브)
    "Security",          # 13F가 보고한 이름만 있는 보유 종목 (식별자 없음)
    "Investor",          # 13F 보고 주체
    "SourceChannel",     # 블로그·텔레그램 채널·IB 하우스
    "DartFiling",
    "SecFiling",
    "HoldingsSnapshot",  # 13F 보유 현황
    "MarketCommentary",  # 텔레그램 메시지
    "ResearchNote",      # IB 인사이트 / 네이버 리서치
    "BlogPost",
    "Essay",
]

# status는 OKF 표준 필드가 아니라 이 번들의 확장이다. 이 코퍼스는 문서의 1/3이
# 본문 없이 링크만 있으므로, '검색 대상이 되는 지식'과 '아직 본문을 못 가져온 자리표시자'를
# 구분하지 않으면 검색 결과가 조용히 오염된다.
Status = Literal["stable", "stub", "superseded", "corrupt"]


@dataclass
class EntityRef:
    kind: Literal["company", "security", "investor", "channel"]
    key: str          # kr-005930, us-NBIS, inv-baillie-gifford-co
    name: str

    def path_from(self, depth: int) -> str:
        folder = {"company": "companies", "security": "securities",
                  "investor": "investors", "channel": "sources"}[self.kind]
        return "../" * depth + f"{folder}/{self.key}.md"


@dataclass
class Period:
    published: str | None = None   # 발행일
    as_of: str | None = None       # 보고 기준일
    fiscal: str | None = None      # 2010-Q1

    def year(self) -> str | None:
        for v in (self.as_of, self.published):
            if v and len(v) >= 4 and v[:4].isdigit():
                return v[:4]
        return None


@dataclass
class Provenance:
    system: str
    native_id: str | None
    collected_at: str
    content_hash: str
    source_path: str


@dataclass
class Concept:
    """OKF concept 하나 = 파일 하나."""

    # --- OKF 표준 필드 ---
    type: ConceptType
    title: str
    description: str
    resource: str = ""
    tags: list[str] = field(default_factory=list)
    timestamp: str = ""
    # --- 확장 필드 ---
    key: str = ""                       # 파일명(확장자 제외)
    folder: str = ""                    # 번들 루트 기준 디렉터리
    status: Status = "stable"
    language: str = ""
    capture: str = "full"
    period: Period | None = None
    stale_after: str | None = None
    subject: EntityRef | None = None
    mentions: list[EntityRef] = field(default_factory=list)
    # 본문에 등장한 증권사·운용사. 이들은 '분석 대상'이 아니라 '분석 주체'라 관계를
    # 분리한다. 한 덩어리로 두면 "SK하이닉스를 다룬 문서"를 찾을 때 SK증권이 쓴 다른
    # 종목 리포트가 같이 딸려온다.
    analyst_houses: list[EntityRef] = field(default_factory=list)
    provenance: Provenance | None = None
    # 본문 품질. 이 코퍼스의 옛 DART 공시 일부는 인코딩이 깨진 채로 저장돼 있는데,
    # 원본 vault에는 그 사실을 적을 자리가 없어 그대로 색인돼 왔다.
    quality: dict | None = None
    body: str = ""
    extra_links: list[tuple[str, str]] = field(default_factory=list)  # (label, rel path)

    @property
    def depth(self) -> int:
        return len([p for p in self.folder.split("/") if p])

    def frontmatter(self) -> dict:
        d: dict = {
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "resource": self.resource,
            "tags": self.tags,
            "timestamp": self.timestamp,
            "status": self.status,
        }
        if self.language:
            d["language"] = self.language
        d["capture"] = self.capture
        if self.period:
            p = {k: v for k, v in vars(self.period).items() if v}
            if p:
                d["period"] = p
        if self.stale_after:
            d["stale_after"] = self.stale_after
        ent: dict = {}
        if self.subject:
            ent["subject"] = {"kind": self.subject.kind, "key": self.subject.key,
                              "name": self.subject.name}
        if self.mentions:
            ent["mentions"] = [m.key for m in self.mentions]
        if self.analyst_houses:
            ent["analyst_house"] = [m.key for m in self.analyst_houses]
        if ent:
            d["entities"] = ent
        if self.quality:
            d["quality"] = self.quality
        if self.provenance:
            d["provenance"] = {k: v for k, v in vars(self.provenance).items() if v}
        return d

    def render(self) -> str:
        fm = yaml.safe_dump(self.frontmatter(), allow_unicode=True, sort_keys=False,
                            default_flow_style=False, width=100)
        parts = [f"---\n{fm}---\n"]
        parts.append(f"# 요약\n\n{self.description}\n")
        body = self.body.strip() or "_본문 미확보. 아래 원문 링크 참조._"
        parts.append(f"# 원문\n\n{body}\n")

        # OKF: concept 사이의 관계는 일반 마크다운 링크로 표현한다.
        rel: list[str] = []
        if self.subject:
            label = {"company": "대상 종목", "security": "종목", "investor": "보고 주체",
                     "channel": "발행 채널"}
            rel.append(f"- {label[self.subject.kind]}: "
                       f"[{self.subject.name}]({self.subject.path_from(self.depth)})")
        for m in self.mentions[:40]:
            rel.append(f"- 언급 종목: [{m.name}]({m.path_from(self.depth)})")
        for m in self.analyst_houses[:10]:
            rel.append(f"- 분석 주체: [{m.name}]({m.path_from(self.depth)})")
        for lbl, path in self.extra_links:
            rel.append(f"- {lbl}: {path}")
        if rel:
            parts.append("# 관계\n\n" + "\n".join(rel) + "\n")

        src: list[str] = []
        if self.provenance:
            src.append(f"- 수집 시스템: `{self.provenance.system}`")
            if self.provenance.native_id:
                src.append(f"- 원 식별자: `{self.provenance.native_id}`")
            src.append(f"- 원본 파일: `{self.provenance.source_path}`")
            src.append(f"- 내용 해시: `{self.provenance.content_hash[:16]}…`")
        if self.resource:
            src.append(f"- 원문: <{self.resource}>")
        if src:
            parts.append("# 출처\n\n" + "\n".join(src) + "\n")
        return "\n".join(parts)
