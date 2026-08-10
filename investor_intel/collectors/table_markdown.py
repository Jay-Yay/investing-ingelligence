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
    문제되지 않는다. DART는 데이터 셀에 TD 외에도 TE(XBRL 태깅된 셀)/TU(기간·단위 셀)를 섞어
    쓴다 - 실제 재무제표 표에서 확인된 태그셋이며, 헤더는 TH만 쓴다.
    """

    _DATA_CELL_TAGS = ("td", "te", "tu")

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
        elif tag == "th" or tag in self._DATA_CELL_TAGS:
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
        if (tag == "th" or tag in self._DATA_CELL_TAGS) and self._cell_parts is not None:
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


def _split_off_captions(rows: list[_Row], captions: list[str]) -> list[_Row]:
    """1개 이하의 비어있지 않은 셀을 가진 행을 걸러낸다.

    셀이 0개면(SEC iXBRL의 컬럼폭 정의용 "고스트 행" - 모든 <td>가 빈 self-closing 태그) 그냥
    버린다. 정확히 1개면 캡션/섹션제목 행(예: DART "(단위: 백만원)", XBRL "Abstract" 그룹 라벨)
    으로 보고 captions에 담아 표 위에 굵게 붙인다. 2개 이상이면 실제 그리드(헤더 또는 데이터)
    행이므로 그대로 반환 목록에 남긴다.
    """
    grid_rows: list[_Row] = []
    for row in rows:
        non_empty = [c.text for c in row.cells if c.text.strip()]
        if len(non_empty) <= 1:
            if non_empty:
                captions.append(non_empty[0])
            continue
        grid_rows.append(row)
    return grid_rows


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
    if thead_rows:
        header_rows = _split_off_captions(thead_rows, captions)
        data_rows_src = _split_off_captions(body_rows, captions)
    else:
        # thead가 없는 SEC 스타일 표: 셀이 2개 이상인 첫 행을 헤더로 쓰고 나머지를 데이터로 본다.
        grid_rows = _split_off_captions(body_rows, captions)
        if not grid_rows:
            return None
        header_rows, data_rows_src = grid_rows[:1], grid_rows[1:]

    if not header_rows:
        return None

    # 헤더와 데이터 행 전체를 한 좌표계에서 colspan/rowspan 기준으로 컬럼 위치를 매긴다. SEC
    # iXBRL 재무제표 표는 행마다 "$" 기호·숫자·순수 여백을 별도 <td>로 쪼개고 그 개수가 행마다
    # 다른 경우가 흔한데, 예전 방식(행별로 빈 셀만 걸러내고 남은 셀을 왼쪽부터 채움)은 그 결과
    # 같은 의미의 값이 행마다 다른 컬럼으로 밀려 표가 뒤섞이거나(가장 폭이 넓은 행 기준으로
    # 나머지 행을 오른쪽 빈칸으로 채우면서) 컬럼 수십 개짜리 표가 되어 대부분 비어 렌더링이
    # 깨졌다(AMZN 10-Q "Effect of Foreign Exchange Rates" 표 실사례 - 세로로 한 글자씩 쌓여
    # 보이는 버그로 나타남). colspan 기준 위치 매핑은 행마다 셀 개수가 달라도 실제 컬럼 폭
    # 배수 관계(예: 9=3x3)만 맞으면 값이 올바른 컬럼에 정렬된다.
    positioned = _positioned_texts(header_rows + data_rows_src)
    header_positioned = positioned[: len(header_rows)]
    data_positioned = positioned[len(header_rows) :]

    max_col = max((max(r.keys(), default=-1) for r in positioned), default=-1) + 1
    active_cols = [
        col for col in range(max_col) if any(r.get(col, "").strip() for r in positioned)
    ]
    if not active_cols:
        return None

    def _row_texts(row_map: dict[int, str]) -> list[str]:
        return [row_map.get(col, "") for col in active_cols]

    if len(header_positioned) == 1:
        header = _row_texts(header_positioned[0])
    else:
        header = []
        for col in active_cols:
            parts = [r[col] for r in header_positioned if col in r and r[col].strip()]
            deduped = list(dict.fromkeys(parts))  # rowspan 반영으로 같은 텍스트 중복 방지
            header.append(" ".join(deduped))

    data_rows = [
        row for row in (_row_texts(r) for r in data_positioned) if any(c.strip() for c in row)
    ]
    if not data_rows:
        return None

    col_count = len(active_cols)
    lines = [f"**{_escape_cell(c)}**" for c in captions]
    if captions:
        # 캡션과 표 사이에 빈 줄이 없으면 Obsidian/CommonMark가 표를 표로 인식하지 못하고
        # 앞 문단에 이어붙은 순수 텍스트로 렌더링한다.
        lines.append("")
    lines.append("| " + " | ".join(_escape_cell(c) for c in header) + " |")
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for row_cells in data_rows:
        lines.append("| " + " | ".join(_escape_cell(c) for c in row_cells) + " |")

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
