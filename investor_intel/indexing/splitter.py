from __future__ import annotations

import re
from dataclasses import dataclass

from investor_intel.indexing.loader import LoadedDocument, Section

_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
# 한국어 종결어미와 영문 문장부호를 모두 문장 경계로 본다.
_SENT_END = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s+|(?<=요\.)\s+|\n")


@dataclass
class Chunk:
    doc_id: str
    ord: int
    heading_path: str
    text: str
    kind: str  # prose | table | metadata


def _blocks(text: str) -> list[tuple[str, str]]:
    """섹션 본문을 의미 단위 블록으로 나눈다: 표는 표끼리, 문단은 문단끼리."""
    out: list[tuple[str, str]] = []
    buf: list[str] = []
    mode = "prose"

    def flush() -> None:
        nonlocal buf, mode
        body = "\n".join(buf).strip()
        if body:
            out.append((mode, body))
        buf = []

    for line in text.split("\n"):
        is_row = bool(_TABLE_ROW.match(line))
        if is_row and mode != "table":
            flush()
            mode = "table"
        elif not is_row and mode == "table":
            flush()
            mode = "prose"
        if not is_row and not line.strip() and mode == "prose":
            flush()
            continue
        buf.append(line)
    flush()
    return out


def _split_table(block: str, max_chars: int) -> list[str]:
    """표를 자를 때 헤더 행을 매 조각에 다시 붙인다.

    안 붙이면 두 번째 조각부터는 '이 숫자가 무슨 항목인지' 알 수 없는 숫자 나열이 되어,
    검색으로 찾아도 LLM이 쓸 수 없는 근거가 된다.
    """
    lines = [l for l in block.split("\n") if l.strip()]
    header: list[str] = []
    body = lines
    if len(lines) >= 2 and _TABLE_SEP.match(lines[1]):
        header, body = lines[:2], lines[2:]
    head_txt = "\n".join(header)
    out, cur = [], list(header)
    cur_len = len(head_txt)
    for row in body:
        if cur_len + len(row) > max_chars and len(cur) > len(header):
            out.append("\n".join(cur))
            cur, cur_len = list(header), len(head_txt)
        cur.append(row)
        cur_len += len(row) + 1
    if len(cur) > len(header):
        out.append("\n".join(cur))
    return out or [block[:max_chars]]


def _split_prose(block: str, max_chars: int, overlap: int) -> list[str]:
    sents = [s for s in _SENT_END.split(block) if s and s.strip()]
    out: list[str] = []
    cur = ""
    for s in sents:
        if len(s) > max_chars:  # 문장 하나가 상한을 넘으면 강제 절단
            if cur:
                out.append(cur)
                cur = ""
            for i in range(0, len(s), max_chars - overlap):
                out.append(s[i : i + max_chars])
            continue
        if len(cur) + len(s) + 1 > max_chars:
            out.append(cur)
            cur = (cur[-overlap:] + " " + s) if overlap else s
        else:
            cur = f"{cur} {s}".strip()
    if cur.strip():
        out.append(cur)
    return out


def split_document(
    doc: LoadedDocument,
    *,
    chunking: bool,
    target_chars: int = 700,
    max_chars: int = 1200,
    overlap_chars: int = 120,
) -> list[Chunk]:
    """문서를 검색 단위로 자른다.

    chunking=False면 문서 전체가 하나의 검색 단위다(현행 수준 재현용).
    chunking=True면 마크다운 구조(섹션 -> 표/문단)를 먼저 존중하고, 그래도 상한을 넘는
    블록만 문장 경계에서 자른다. 길이를 먼저 자르고 구조를 무시하면 표의 헤더와 값이
    분리되거나 문장이 중간에서 끊긴다.
    """
    if not chunking:
        text = doc.body.strip()
        if not text:
            return []
        return [Chunk(doc.doc_id, 0, "", text, "prose")]

    chunks: list[Chunk] = []
    n = 0
    for sec in doc.sections:
        path = sec.heading
        cur = ""
        for kind, block in _blocks(sec.text):
            pieces = (
                _split_table(block, max_chars)
                if kind == "table"
                else ([block] if len(block) <= max_chars else _split_prose(block, max_chars, overlap_chars))
            )
            for piece in pieces:
                if kind == "table":
                    if cur.strip():
                        chunks.append(Chunk(doc.doc_id, n, path, cur.strip(), "prose")); n += 1; cur = ""
                    chunks.append(Chunk(doc.doc_id, n, path, piece.strip(), "table")); n += 1
                    continue
                if len(cur) + len(piece) + 1 > target_chars and cur.strip():
                    chunks.append(Chunk(doc.doc_id, n, path, cur.strip(), "prose")); n += 1
                    cur = (cur[-overlap_chars:] + "\n" + piece) if overlap_chars else piece
                else:
                    cur = f"{cur}\n{piece}".strip()
        if cur.strip():
            chunks.append(Chunk(doc.doc_id, n, path, cur.strip(), "prose")); n += 1

    if not chunks:  # 본문이 없는 문서도 메타데이터만으로 하나의 레코드를 남긴다
        meta = " ".join(filter(None, [doc.title, doc.source_name, doc.filing_type or "", doc.document_type]))
        if meta.strip():
            chunks.append(Chunk(doc.doc_id, 0, "", meta.strip(), "metadata"))
    return chunks


def context_header(doc: LoadedDocument, chunk: Chunk) -> str:
    """청크 앞에 붙일 문맥 문자열을 메타데이터에서 결정론적으로 만든다.

    Anthropic의 Contextual Retrieval은 문서 전체를 LLM에 넣어 청크별 설명을 '생성'한다.
    여기서는 LLM 없이 frontmatter와 섹션 경로를 투영한다. 이 코퍼스는 수집기가 구조화된
    메타데이터를 이미 붙여두기 때문에 생성형 문맥이 만들어낼 정보의 상당 부분(출처, 종목,
    공시유형, 기간, 섹션)이 이미 확정값으로 존재한다. 대신 '이 청크가 문서의 논지에서
    어떤 역할인지' 같은 생성형만 만들 수 있는 문맥은 얻지 못한다 - 비용 0의 대가다.
    """
    bits = [f"출처 {doc.source_type}", doc.source_name]
    if doc.companies:
        bits.append("종목 " + " ".join(doc.companies))
    if doc.filing_type:
        bits.append(doc.filing_type)
    if doc.reporting_period:
        bits.append("기준일 " + doc.reporting_period)
    if doc.published_at:
        bits.append("발행 " + doc.published_at[:10])
    if doc.title:
        bits.append(doc.title)
    if chunk.heading_path:
        bits.append("섹션 " + chunk.heading_path)
    return " · ".join(b for b in bits if b)
