from investor_intel.collectors.table_markdown import convert_tables_to_markdown

_DART_TABLE = """
<TABLE WIDTH="871" ACLASS="NORMAL" BORDER="1">
<COLGROUP WIDTH="871">
<COL WIDTH="291"></COL>
<COL WIDTH="194"></COL>
<COL WIDTH="198"></COL>
</COLGROUP>
<THEAD>
<TR><TH COLSPAN="3" ALIGN="RIGHT">(단위 : 백만원)</TH></TR>
<TR>
<TH ROWSPAN="2">구  분</TH>
<TH>제11기</TH>
<TH>제10기</TH>
</TR>
<TR>
<TH>2026년 1분기</TH>
<TH>2025년</TH>
</TR>
</THEAD>
<TBODY>
<TR>
<TD>[유동부채]</TD>
<TD ALIGN="RIGHT">63,008</TD>
<TD ALIGN="RIGHT">53,587</TD>
</TR>
<TR>
<TD>부채총계</TD>
<TD ALIGN="RIGHT">66,621</TD>
<TD ALIGN="RIGHT">56,780</TD>
</TR>
</TBODY>
</TABLE>
"""


def test_dart_style_table_becomes_markdown_with_merged_two_row_header() -> None:
    result = convert_tables_to_markdown(_DART_TABLE)

    assert "<TABLE" not in result
    assert "**(단위 : 백만원)**" in result
    assert "| 구 분 | 제11기 2026년 1분기 | 제10기 2025년 |" in result
    assert "| [유동부채] | 63,008 | 53,587 |" in result
    assert "| 부채총계 | 66,621 | 56,780 |" in result


def test_caption_is_separated_from_table_by_a_blank_line() -> None:
    # regression: a caption ("(단위 : 백만원)") directly adjacent to the header row (no blank
    # line between them) makes Obsidian/CommonMark render the whole thing as one text paragraph
    # instead of a table - only the *later* table in the same document (with no caption) rendered
    # correctly, which is what exposed this.
    result = convert_tables_to_markdown(_DART_TABLE)
    assert "**(단위 : 백만원)**\n\n| 구 분 |" in result


def test_dart_style_table_keeps_row_and_column_aligned() -> None:
    # regression: naive tag-stripping used to turn every cell into its own line with no way to
    # tell which fiscal period a number belonged to - this asserts the row label and both period
    # values stay on the same markdown table row, in the same order as the header.
    result = convert_tables_to_markdown(_DART_TABLE)
    lines = [line for line in result.splitlines() if line.startswith("|")]
    header_cols = lines[0].split("|")
    liability_row_cols = [line for line in lines if "유동부채" in line][0].split("|")
    assert len(header_cols) == len(liability_row_cols)


_DART_XBRL_TABLE = """
<TABLE ACLASS="NORMAL" AFIXTABLE="Y" WIDTH="600" BORDER="1" FRAME="BORDER" RULES="ALL">
<COLGROUP WIDTH="600">
<COL WIDTH="200"></COL>
<COL WIDTH="200"></COL>
<COL WIDTH="200"></COL>
</COLGROUP>
<THEAD>
<TR>
<TH>　</TH>
<TH ENG="FY 2026">제 11 기 1분기말</TH>
<TH ENG="FY 2025">제 10 기말</TH>
</TR>
</THEAD>
<TBODY>
<TR>
<TE ENG="Assets">자산</TE>
<TE ACODE="ifrs-full_AssetsAbstract">　</TE>
<TE ACODE="ifrs-full_AssetsAbstract">　</TE>
</TR>
<TR>
<TE ENG="　Current assets">　유동자산</TE>
<TE ACODE="ifrs-full_CurrentAssets" ADECIMAL="0">281,110,885,179</TE>
<TE ACODE="ifrs-full_CurrentAssets" ADECIMAL="0">239,109,582,847</TE>
</TR>
</TBODY>
</TABLE>
"""


def test_dart_xbrl_table_with_te_data_cells_becomes_markdown() -> None:
    # regression: some DART financial-statement tables (XBRL-tagged, ACODE attributes) use <TE>
    # instead of <TD> for data cells and <TU> for period/unit cells - the parser only recognized
    # <TD>/<TH>, so these tables silently produced zero data rows and fell through unconverted to
    # strip_markup, which flattened them into a bare list of numbers with no row/column context.
    result = convert_tables_to_markdown(_DART_XBRL_TABLE)

    assert "<TABLE" not in result
    assert "| 제 11 기 1분기말 | 제 10 기말 |" in result
    assert "| 유동자산 | 281,110,885,179 | 239,109,582,847 |" in result


_DART_TU_TABLE = """
<TABLE WIDTH="600" BORDER="1">
<TBODY>
<TR>
<TD ROWSPAN="2">사업연도</TD>
<TU AUNIT="PERIODFROM" AUNITVALUE="20260101">2026년 01월 01일</TU>
<TD>부터</TD>
</TR>
<TR>
<TU AUNIT="PERIODTO" AUNITVALUE="20260331">2026년 03월 31일</TU>
<TD>까지</TD>
</TR>
</TBODY>
</TABLE>
"""


def test_dart_table_with_tu_period_cells_becomes_markdown() -> None:
    result = convert_tables_to_markdown(_DART_TU_TABLE)
    assert "<TABLE" not in result
    assert "2026년 01월 01일" in result
    assert "2026년 03월 31일" in result


_SEC_STYLE_TABLE = (
    "<table><tr>"
    '<td colspan="2">Total current liabilities</td>'
    '<td style="padding:0 1pt 0 37pt"></td>'
    '<td style="text-align:right">786,804</td>'
    '<td style="text-align:right">623,832</td>'
    "</tr><tr>"
    '<td colspan="2">Total liabilities</td>'
    '<td style="padding:0 1pt 0 37pt"></td>'
    '<td style="text-align:right">1,000,000</td>'
    '<td style="text-align:right">900,000</td>'
    "</tr></table>"
)


def test_sec_style_table_without_thead_uses_first_row_as_header_and_drops_empty_spacer_cells() -> (
    None
):
    result = convert_tables_to_markdown(_SEC_STYLE_TABLE)

    assert "| Total current liabilities | 786,804 | 623,832 |" in result
    assert "| Total liabilities | 1,000,000 | 900,000 |" in result


def test_script_and_style_tags_inside_table_are_not_captured_as_cell_text() -> None:
    html = (
        "<table><tr><td>Revenue</td>"
        "<td><style>.x{color:red}</style>100</td>"
        "<td><script>alert(1)</script>200</td></tr>"
        "<tr><td>Cost</td><td>10</td><td>20</td></tr></table>"
    )
    result = convert_tables_to_markdown(html)
    assert "color:red" not in result
    assert "alert(1)" not in result
    assert "| Revenue | 100 | 200 |" in result


def test_cell_text_with_pipe_and_angle_brackets_is_escaped() -> None:
    html = (
        "<table><tr><td>label</td><td>value</td></tr>"
        "<tr><td>a | b</td><td>x &lt; y</td></tr></table>"
    )
    result = convert_tables_to_markdown(html)
    assert "a \\| b" in result
    assert "x &lt; y" in result


def test_table_with_no_usable_row_structure_is_left_untouched() -> None:
    html = "<table><tr><td>just one column, no header pattern</td></tr></table>"
    result = convert_tables_to_markdown(html)
    assert result == html


_SEC_SPARSE_SPACER_TABLE = (
    "<table>"
    # ghost width-definition row: every <td> is empty, used only to fix column widths in the
    # rendered HTML - must not become a degenerate all-blank data row.
    '<tr><td style="width:1%"/><td style="width:38%"/><td style="width:1%"/>'
    '<td style="width:13%"/><td style="width:1%"/><td style="width:13%"/></tr>'
    # header row: colspan=3 label wraps a 6-column grid; label sits every 3rd column start.
    '<tr><td colspan="3"/><td colspan="3">Q2 2025</td><td colspan="3"/>'
    '<td colspan="3">Q2 2026</td></tr>'
    # data row: uses a *different* colspan granularity (colspan=1 spacer + colspan=1 "$" +
    # colspan=1 number) - real SEC filings split "$" and the number into separate <td>s.
    '<tr><td colspan="3">Operating lease cost</td>'
    '<td colspan="1"/><td colspan="1">$</td><td colspan="1">1,234</td>'
    '<td colspan="1"/><td colspan="1">$</td><td colspan="1">2,345</td></tr>'
    "</table>"
)


def test_sec_table_with_sparse_spacer_columns_collapses_to_active_columns_only() -> None:
    """실사례 회귀: AMZN 10-Q의 "Effect of Foreign Exchange Rates" 표는 실제 값이 담긴 컬럼이
    몇 개뿐인데도 순수 여백용 <td>가 수십 개 섞여 있었다. 예전 로직(행마다 독립적으로 빈 셀만
    걸러내고 남은 값을 왼쪽부터 채움)은 이 여백 개수가 행마다 다르면 서로 다른 의미의 값이
    같은 컬럼에 밀려 들어가거나, 표 전체가 수십 컬럼짜리 표가 되어 대부분 빈 칸으로 렌더링이
    깨졌다(Obsidian에서 세로로 한 글자씩 쌓여 보이는 버그로 나타남). colspan 기준 위치 매핑
    으로 고쳐서, 실제로 값이 있는 컬럼만 남고 여백 컬럼은 모두 제거되며 헤더-데이터 간 정렬이
    깨지지 않아야 한다.
    """
    result = convert_tables_to_markdown(_SEC_SPARSE_SPACER_TABLE)

    lines = [line for line in result.splitlines() if line.startswith("|")]
    assert len(lines) == 3  # header + separator + one data row, no leftover ghost row

    header_cols = lines[0].split("|")
    data_cols = lines[2].split("|")
    assert len(header_cols) == len(data_cols)  # same column count, properly aligned
    # the old bug produced a column for *every* raw <td> including pure spacer cells (13 here,
    # would be dozens on a real filing) - collapsing to genuinely-used columns keeps this small.
    assert len(header_cols) <= 9

    assert "Q2 2025" in lines[0]
    assert "Q2 2026" in lines[0]
    # both dollar figures land under their correct period (2025's "$1,234" appears before
    # 2026's "$2,345" in row order, not scrambled or duplicated across columns)
    assert result.index("1,234") < result.index("2,345")
    assert "Operating lease cost" in lines[2]
    assert "$" in lines[2] and "1,234" in lines[2] and "2,345" in lines[2]


def test_non_table_content_is_unaffected() -> None:
    html = "<div><p>본문 내용</p></div>"
    assert convert_tables_to_markdown(html) == html
