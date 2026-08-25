from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml

from investor_intel.indexing.text_normalize import normalize

_FM = re.compile(r"^---\n(.*?)\n---\n", re.S)
_SECTION = re.compile(r"^# (.+)$", re.M)
_SKIP_TYPES = {"Index", "Bundle", "Log"}


@dataclass
class OkfConcept:
    """OKF concept 하나를 인덱싱 입력으로 읽어들인 것.

    10_Sources를 직접 읽는 `loader.py`와 다른 점은, 여기서는 파싱해서 '추론'할 게 없다는
    것이다. 어느 종목에 대한 것인지, 어느 기간인지, 본문이 실제로 있는지가 전부 확정된
    필드로 들어 있다. 지식 레이어를 한 번 만들어두면 소비자(consumer)마다 같은 파싱을
    다시 하지 않아도 된다는 것이 OKF가 말하는 producer/consumer 분리다.
    """

    concept_id: str
    path: str
    okf_type: str
    title: str
    description: str
    status: str
    capture: str
    language: str
    tags: list[str]
    resource: str
    published: str
    period_year: str
    fiscal: str
    entity_keys: list[str]
    subject_name: str
    source_system: str
    native_id: str
    sections: list[tuple[str, str]] = field(default_factory=list)

    @property
    def body(self) -> str:
        return "\n\n".join(f"## {h}\n{t}" for h, t in self.sections)

    @property
    def has_body(self) -> bool:
        return self.status != "stub" and bool(self.body.strip())


def _split_sections(md: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    parts = re.split(r"^# ", md, flags=re.M)
    for part in parts[1:]:
        head, _, rest = part.partition("\n")
        out.append((head.strip(), rest.strip()))
    return out


def parse_concept(path: Path, root: Path) -> OkfConcept | None:
    raw = path.read_text(encoding="utf-8")
    m = _FM.match(raw)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    ctype = str(fm.get("type") or "")
    if ctype in _SKIP_TYPES:
        return None

    ent = fm.get("entities") or {}
    subj = ent.get("subject") or {}
    keys: list[str] = []
    if subj.get("key"):
        keys.append(str(subj["key"]))
    keys += [str(k) for k in (ent.get("mentions") or [])]

    period = fm.get("period") or {}
    prov = fm.get("provenance") or {}
    as_of = str(period.get("as_of") or "")
    published = str(period.get("published") or "")
    year = (as_of or published)[:4]

    # 요약(description)과 원문만 색인 대상으로 삼는다. '관계'와 '출처' 섹션은 링크와
    # 식별자라서 별도 컬럼으로 다루는 편이 낫고, 본문에 섞으면 모든 문서에 공통으로
    # 들어간 노이즈가 된다.
    sections = [(h, normalize(t)) for h, t in _split_sections(raw[m.end():])
                if h in ("원문",) and t.strip() and not t.strip().startswith("_본문 미확보")]

    return OkfConcept(
        concept_id=path.stem,
        path=str(path.relative_to(root.parent)),
        okf_type=ctype,
        title=str(fm.get("title") or ""),
        description=str(fm.get("description") or ""),
        status=str(fm.get("status") or "stable"),
        capture=str(fm.get("capture") or "full"),
        language=str(fm.get("language") or ""),
        tags=[str(t) for t in (fm.get("tags") or [])],
        resource=str(fm.get("resource") or ""),
        published=published,
        period_year=year,
        fiscal=str(period.get("fiscal") or ""),
        entity_keys=keys,
        subject_name=str(subj.get("name") or ""),
        source_system=str(prov.get("system") or ""),
        native_id=str(prov.get("native_id") or ""),
        sections=sections,
    )


def load_bundle(root: Path) -> Iterator[OkfConcept]:
    for path in sorted(root.rglob("*.md")):
        if path.name == "index.md":
            continue
        c = parse_concept(path, root)
        if c is not None:
            yield c
