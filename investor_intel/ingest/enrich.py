"""이미 vault에 있는 문서에 품질 측정값과 종목 관계를 채운다.

## 왜 별도 명령이 필요한가

`ingest.quality`와 `ingest.entities`는 수집 시점에 동작하므로, 이 계층이 생기기 전에 모은
문서(실측 4,818건)에는 그 필드가 없다. 수집기를 다시 돌려도 채워지지 않는다 - 증분
체크포인트(`last_seen_id`)가 과거 문서를 다시 보지 않기 때문이다.

그런데 이 두 값은 **본문만 있으면 다시 계산할 수 있다.** 재수집 없이 vault를 한 번 훑어
frontmatter만 갱신하면 된다. 그래서 재수집이 필요한 항목(본문 미확보 stub, 인코딩이 깨진
원문)과 달리 이건 로컬 작업으로 끝난다.

## 무엇을 하지 않는가

본문은 건드리지 않는다. `content_hash`도 그대로다 - 본문이 안 바뀌었으므로 바꿀 이유가 없고,
바꾸면 중복 판정(`find_duplicate`)이 모든 문서를 새 문서로 보게 된다. 갱신하는 것은
frontmatter의 측정값·관계 필드뿐이다.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from investor_intel.ingest.entities import EntityResolver, merge_mentions
from investor_intel.ingest.quality import is_corrupt, readable_ratio, truncation_of
from investor_intel.models.source_document import DocumentEntities, SourceDocument
from investor_intel.storage.obsidian_repo import list_documents, read_document, render_document


@dataclass
class EnrichStats:
    scanned: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)
    # 관측 결과. 재수집이 필요한 문서가 몇 건인지가 이 명령의 부산물로 나온다.
    corrupt: int = 0
    truncated: int = 0
    # 수집기가 이미 확정해 둔 종목(공시·13F)을 관계로 옮긴 건수.
    mentions_from_metadata: int = 0
    # 원본에 종목 정보가 없어 본문 매칭으로 새로 찾아낸 건수. 이 명령의 핵심 성과다.
    mentions_recovered: int = 0
    analyst_houses_split: int = 0
    docs_with_recovered_mentions: int = 0
    by_source: Counter[str] = field(default_factory=Counter)


def enriched_document(
    doc: SourceDocument, body: str, resolver: EntityResolver | None
) -> tuple[SourceDocument, bool]:
    """본문에서 다시 계산할 수 있는 필드만 채운 사본과, 본문 매칭을 썼는지를 돌려준다."""
    truncated, original_chars = truncation_of(body)
    entities = doc.entities
    recovered = False
    if not entities.mentions and not entities.analyst_house:
        # 중복 제거는 반드시 한다 - 옛 13F 문서는 같은 종목이 보유 행 수만큼 반복돼 있다
        # (실측 121개 항목 = 37개 종목).
        declared = list(dict.fromkeys(doc.companies))
        if resolver is not None and not resolver.is_empty:
            entities = resolver.resolve(body, subject=doc.source_name)
            recovered = len(entities.mentions) > 0 or len(entities.analyst_house) > 0
            entities = entities.model_copy(
                update={"mentions": merge_mentions(declared, entities.mentions)}
            )
        else:
            entities = DocumentEntities(subject=doc.source_name, mentions=declared)
    return (
        doc.model_copy(
            update={
                "readable_ratio": readable_ratio(body),
                "truncated": truncated,
                "original_chars": original_chars,
                "entities": entities,
            }
        ),
        recovered,
    )


def enrich_vault(
    vault_path: Path,
    conn: sqlite3.Connection | None = None,
    apply: bool = False,
) -> EnrichStats:
    """vault 전체를 훑어 품질 측정값과 종목 관계를 채운다.

    `apply=False`면 파일을 쓰지 않고 무엇이 바뀌는지만 센다(기본값) - `dedupe-vault`와 같은
    관례다.
    """
    stats = EnrichStats()
    resolver = EntityResolver.from_connection(conn) if conn is not None else None

    for path in list_documents(vault_path):
        try:
            doc, body = read_document(path)
        except Exception as exc:  # noqa: BLE001
            stats.errors.append(f"{path.name}: {exc}")
            continue

        stats.scanned += 1
        updated, recovered = enriched_document(doc, body, resolver)

        if is_corrupt(updated.readable_ratio):
            stats.corrupt += 1
            stats.by_source[f"{doc.source_type.value}:corrupt"] += 1
        if updated.truncated:
            stats.truncated += 1
        declared_count = len(dict.fromkeys(doc.companies))
        new_mentions = len(updated.entities.mentions) - len(doc.entities.mentions)
        stats.mentions_from_metadata += min(declared_count, new_mentions)
        if recovered:
            body_matched = new_mentions - min(declared_count, new_mentions)
            stats.mentions_recovered += body_matched
            stats.docs_with_recovered_mentions += int(body_matched > 0)
            stats.by_source[f"{doc.source_type.value}:recovered"] += int(body_matched > 0)
        stats.analyst_houses_split += len(updated.entities.analyst_house) - len(
            doc.entities.analyst_house
        )

        if updated == doc:
            continue
        stats.updated += 1
        if apply:
            path.write_text(render_document(updated, body), encoding="utf-8")

    return stats
