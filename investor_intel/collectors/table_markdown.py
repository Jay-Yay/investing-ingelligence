from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_TABLE_BLOCK_RE = re.compile(r"<table\b.*?</table\s*>", re.IGNORECASE | re.DOTALL)


@dataclass
class _Cell:
    text: str
    colspan: int
    rowspan: int


@dataclass
class _Row:
    cells: list[_Cell] = field(default_factory=list)
    section: str = "body"  # "thead" | "body"


class _TableParser(HTMLParser):
    """<table> 하나의 내부 구조(행/셀/컬스팬/로우스팬, thead 여부)를 파싱한다.

    DART document.xml(THEAD/TBODY/TH/TD 명시)과 SEC iXBRL HTML(태그 전부 소문자 td, thead 없음)
    둘 다 이 파서로 처리한다 - HTMLParser는 태그명을 자동으로 소문자화하므로 대소문자 차이는
    문제되지 않는다.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_Row] = []
        self._section_stack: list[str] = []
        self._current_row: _Row | None = None
        self._cell_parts: list[str] | None = None
        self._cell_colspan = 1
        self._cell_rowspan = 1
        self._skip_depth = 0  # <script>/<style> 내부 텍스트는 절대 셀 내용으로 취급하지 않는다

    def _current_section(self) -> str:
        for section in reversed(self._section_stack):
            if section == "thead":
                return "thead"
        return "body"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        attr_map = dict(attrs)
        if tag in ("thead", "tbody"):
            self._section_stack.append(tag)
        elif tag == "tr":
            self._current_row = _Row(section=self._current_section())
        elif tag in ("td", "th"):
            self._cell_parts = []
            self._cell_colspan = _safe_int(attr_map.get("colspan"), 1)
            self._cell_rowspan = _safe_int(attr_map.get("rowspan"), 1)
        elif tag == "br" and self._cell_parts is not None:
            self._cell_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in ("td", "th") and self._cell_parts is not None:
            text = " ".join("".join(self._cell_parts).split())
            if self._current_row is not None:
                self._current_row.cells.append(
                    _Cell(text=text, colspan=self._cell_colspan, rowspan=self._cell_rowspan)
                )
            self._cell_parts = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None
        elif tag in ("thead", "tbody") and self._section_stack:
            self._section_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._cell_parts is not None:
            self._cell_parts.append(data)


def _safe_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value else default
    except ValueError:
        return default


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def _positioned_texts(rows: list[_Row]) -> list[dict[int, str]]:
    """각 행의 셀을 colspan/rowspan을 반영한 컬럼 위치에 배치한다."""
    pending: dict[int, tuple[str, int]] = {}
    positioned: list[dict[int, str]] = []
    for row in rows:
        col = 0
        row_map: dict[int, str] = {}
        for cell in row.cells:
            while col in pending:
                text, remaining = pending[col]
                row_map[col] = text
                if remaining > 1:
                    pending[col] = (text, remaining - 1)
                else:
                    del pending[col]
                col += 1
            row_map[col] = cell.text
            if cell.rowspan > 1:
                pending[col] = (cell.text, cell.rowspan - 1)
            col += max(cell.colspan, 1)
        # 이 행 안에서 아직 안 채워진 pending 컬럼(로우스팬으로 이어지는 뒤쪽 컬럼)도 채운다
        while col in pending:
            text, remaining = pending[col]
            row_map[col] = text
            if remaining > 1:
                pending[col] = (text, remaining - 1)
            else:
                del pending[col]
            col += 1
        positioned.append(row_map)
    return positioned


def _merge_header_rows(thead_rows: list[_Row]) -> tuple[list[str], list[str]]:
    """thead 행들을 캡션(단일 셀짜리 행)과 실제 헤더 그리드로 나눠, 그리드는 컬럼별로 합친다."""
    captions: list[str] = []
    grid_rows: list[_Row] = []
    for row in thead_rows:
        non_empty = [c.text for c in row.cells if c.text.strip()]
        if len(non_empty) <= 1:
            if non_empty:
                captions.append(non_empty[0])
            continue
        grid_rows.append(row)

    if not grid_rows:
        return captions, []

    positioned = _positioned_texts(grid_rows)
    max_col = max((max(r.keys(), default=-1) for r in positioned), default=-1) + 1
    header: list[str] = []
    for col in range(max_col):
        parts = [r[col] for r in positioned if col in r and r[col].strip()]
        deduped = list(dict.fromkeys(parts))  # rowspan 반영으로 같은 텍스트가 중복되는 것 방지
        header.append(" ".join(deduped))
    return captions, header


def _table_to_markdown(table_html: str) -> str | None:
    parser = _TableParser()
    try:
        parser.feed(table_html)
        parser.close()
    except Exception:  # noqa: BLE001
        return None

    thead_rows = [r for r in parser.rows if r.section == "thead"]
    body_rows = [r for r in parser.rows if r.section != "thead"]

    captions: list[str] = []
    header: list[str] = []
    if thead_rows:
        captions, header = _merge_header_rows(thead_rows)

    if not header:
        # thead가 없거나(SEC) 그리드를 못 만든 경우: 셀이 2개 이상인 첫 행을 헤더로 쓴다
        for i, row in enumerate(body_rows):
            non_empty = [c.text for c in row.cells if c.text.strip()]
            if len(non_empty) >= 2:
                header = non_empty
                body_rows = body_rows[i + 1 :]
                break

    if not header:
        return None

    data_rows: list[list[str]] = []
    for row in body_rows:
        non_empty = [c.text for c in row.cells if c.text.strip()]
        if non_empty:
            data_rows.append(non_empty)

    if not data_rows:
        return None

    col_count = max(len(header), max(len(r) for r in data_rows))
    header = header + [""] * (col_count - len(header))

    lines = [f"**{_escape_cell(c)}**" for c in captions]
    lines.append("| " + " | ".join(_escape_cell(c) for c in header) + " |")
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for row_cells in data_rows:
        padded = row_cells + [""] * (col_count - len(row_cells))
        lines.append("| " + " | ".join(_escape_cell(c) for c in padded) + " |")

    return "\n".join(lines)


def convert_tables_to_markdown(raw: str) -> str:
    """원문(HTML/XML)에 있는 <table> 블록을 마크다운 표로 치환한다.

    치환하지 못한(구조를 못 알아본) 표는 원문 그대로 남겨두고 이후 태그 제거 단계
    (`text_extract.strip_markup`)로 넘어간다 - 표를 완전히 잃어버리는 대신 최소한 텍스트는
    보존된다. 표가 아닌 나머지 태그는 이 함수가 건드리지 않는다.
    """

    def _replace(match: re.Match[str]) -> str:
        markdown = _table_to_markdown(match.group(0))
        if markdown is None:
            return match.group(0)
        return f"\n\n{markdown}\n\n"

    return _TABLE_BLOCK_RE.sub(_replace, raw)
