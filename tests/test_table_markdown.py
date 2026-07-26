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


def test_dart_style_table_keeps_row_and_column_aligned() -> None:
    # regression: naive tag-stripping used to turn every cell into its own line with no way to
    # tell which fiscal period a number belonged to - this asserts the row label and both period
    # values stay on the same markdown table row, in the same order as the header.
    result = convert_tables_to_markdown(_DART_TABLE)
    lines = [line for line in result.splitlines() if line.startswith("|")]
    header_cols = lines[0].split("|")
    liability_row_cols = [line for line in lines if "유동부채" in line][0].split("|")
    assert len(header_cols) == len(liability_row_cols)


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


def test_non_table_content_is_unaffected() -> None:
    html = "<div><p>본문 내용</p></div>"
    assert convert_tables_to_markdown(html) == html
