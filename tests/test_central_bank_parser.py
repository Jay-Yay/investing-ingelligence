from datetime import date

from investor_intel.collectors import central_bank_parser as p


def _fed_meeting_block(statement_href: str | None) -> str:
    statement_html = (
        f'<strong>Statement:</strong><br><a href="{statement_href}">HTML</a>'
        if statement_href
        else ""
    )
    return f'<div class="row fomc-meeting">{statement_html}</div>'


def test_parse_fed_statements_index_extracts_a_suffix_only() -> None:
    html = (
        _fed_meeting_block("/newsevents/pressreleases/monetary20260617a.htm")
        + '<a href="/newsevents/pressreleases/monetary20260617a1.htm">Implementation Note</a>'
        + '<a href="/newsevents/pressreleases/monetary20260129b.htm">Other release</a>'
    )
    articles = p.parse_fed_statements_index(html)
    assert [a.meeting_date for a in articles] == [date(2026, 6, 17)]
    assert articles[0].url == (
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm"
    )
    assert articles[0].pdf_url is None


def test_parse_fed_statements_index_excludes_unlabeled_longer_run_goals_notation_vote() -> None:
    # regression: a periodic "Statement on Longer-Run Goals and Monetary Policy Strategy"
    # notation vote (e.g. 2025-08-22) shares the same href pattern as a real FOMC statement but
    # is not wrapped in a "<strong>Statement:</strong>" label - must not be picked up as one.
    html = (
        '<div class="fomc-meeting--shaded row fomc-meeting">'
        '<a href="/newsevents/pressreleases/monetary20250822a.htm">'
        "Statement on Longer-Run Goals and Monetary Policy Strategy</a></div>"
    )

    assert p.parse_fed_statements_index(html) == []


def test_parse_fed_minutes_index_sets_pdf_url() -> None:
    html = '<a href="/monetarypolicy/files/fomcminutes20260617.pdf">Minutes</a>'
    (article,) = p.parse_fed_minutes_index(html)
    assert article.meeting_date == date(2026, 6, 17)
    assert article.pdf_url == article.url
    assert article.url.endswith("fomcminutes20260617.pdf")


def test_extract_fed_statement_text_isolates_article_div() -> None:
    html = (
        "<div id='nav'>skip this nav text</div>"
        "<div id='article'>real statement text</div>"
        "<div id='footer'>skip footer</div>"
    )
    text = p.extract_fed_statement_text(html)
    assert text == "real statement text"


def test_dedupe_sorts_newest_first_and_drops_duplicate_urls() -> None:
    html = (
        _fed_meeting_block("/newsevents/pressreleases/monetary20260101a.htm")
        + _fed_meeting_block("/newsevents/pressreleases/monetary20260601a.htm")
    )
    articles = p.parse_fed_statements_index(html)
    assert [a.meeting_date for a in articles] == [date(2026, 6, 1), date(2026, 1, 1)]


def test_parse_ecb_snippet_urls_resolves_relative_paths() -> None:
    index_html = (
        "<dl id=\"lazyload-container\" data-snippets='../2026/html/index_include.en.html,"
        "../2025/html/index_include.en.html'></dl>"
    )
    urls = p.parse_ecb_snippet_urls(index_html, p.ECB_STATEMENTS_INDEX_URL)
    assert urls == [
        "https://www.ecb.europa.eu/press/press_conference/monetary-policy-statement/2026/html/index_include.en.html",
        "https://www.ecb.europa.eu/press/press_conference/monetary-policy-statement/2025/html/index_include.en.html",
    ]


def test_parse_ecb_statements_snippet_extracts_is_series_links() -> None:
    html = (
        '<a href="/press/press_conference/monetary-policy-statement/2026/html/'
        'ecb.is260723~b6fadd48f4.en.html">Statement</a>'
    )
    (article,) = p.parse_ecb_statements_snippet(html)
    assert article.meeting_date == date(2026, 7, 23)
    assert article.pdf_url is None


def test_parse_ecb_accounts_snippet_extracts_mg_series_links() -> None:
    html = '<a href="/press/accounts/2026/html/ecb.mg260709~0e7f8241c9.en.html">Accounts</a>'
    (article,) = p.parse_ecb_accounts_snippet(html)
    assert article.meeting_date == date(2026, 7, 9)


def test_extract_ecb_main_text_isolates_main_tag() -> None:
    html = (
        "<nav>skip</nav><main ><div class='section'>ecb body text</div></main>"
        "<footer>skip</footer>"
    )
    text = p.extract_ecb_main_text(html)
    assert text == "ecb body text"


def test_parse_boe_index_maps_month_names_and_dedupes() -> None:
    html = (
        '<a href="/monetary-policy-summary-and-minutes/2026/july-2026">July</a>'
        '<a href="/monetary-policy-summary-and-minutes/2026/june-2026">June</a>'
    )
    articles = p.parse_boe_index(html)
    assert [a.meeting_date for a in articles] == [date(2026, 7, 1), date(2026, 6, 1)]


def test_extract_boe_content_text_isolates_content_div() -> None:
    html = "<div id='nav'>skip</div><div id='content'>boe summary and minutes</div>"
    assert p.extract_boe_content_text(html) == "boe summary and minutes"


def test_parse_boj_statements_index_matches_k_a_suffix_only() -> None:
    html = (
        '<a href="/en/mopo/mpmdeci/mpr_2026/k260731a.pdf">Statement</a>'
        '<a href="/en/mopo/mpmdeci/mpr_2026/k260616b.pdf">Same-day annex</a>'
        '<a href="/en/mopo/mpmdeci/mpr_2026/mpr260129a.pdf">Unrelated outlook doc</a>'
    )
    (article,) = p.parse_boj_statements_index(html)
    assert article.meeting_date == date(2026, 7, 31)
    assert article.pdf_url == article.url


def test_parse_boj_minutes_index_matches_g_prefix() -> None:
    html = '<a href="/en/mopo/mpmsche_minu/minu_2026/g260428.pdf">Minutes</a>'
    (article,) = p.parse_boj_minutes_index(html)
    assert article.meeting_date == date(2026, 4, 28)


_BOK_ROW = """
<tr>
<th scope="row">07월 16일(목)</th>
<td>
<a href="/portal/cmmn/file/fileDown.do?menuNo=200755&amp;atchFileId=abc123&amp;fileSn=1"
   title="국문보도자료(2607).hwp">국문보도자료(2607).hwp</a>
<a href="/portal/cmmn/file/fileDown.do?menuNo=200755&amp;atchFileId=abc123&amp;fileSn=2"
   title="국문보도자료(2607).pdf">국문보도자료(2607).pdf</a>
</td>
<td class="tal"></td>
<td>
<a href="/portal/cmmn/file/fileDown.do?menuNo=200755&amp;atchFileId=abc123&amp;fileSn=13"
   title="2026년도 제5차 금통위 의사록.pdf">2026년도 제5차 금통위 의사록.pdf</a>
</td>
</tr>
"""


def test_parse_bok_statements_index_finds_press_release_pdf_and_unescapes_query() -> None:
    (article,) = p.parse_bok_statements_index(_BOK_ROW, 2026)
    assert article.meeting_date == date(2026, 7, 16)
    assert "&amp;" not in article.url
    assert "atchFileId=abc123&fileSn=2" in article.url


def test_parse_bok_minutes_index_finds_minutes_pdf() -> None:
    (article,) = p.parse_bok_minutes_index(_BOK_ROW, 2026)
    assert article.meeting_date == date(2026, 7, 16)
    assert "fileSn=13" in article.url


def test_parse_bok_statements_index_skips_rows_without_a_matching_file() -> None:
    row = """
    <tr>
    <th scope="row">07월 16일(목)</th>
    <td><a href="/portal/cmmn/file/fileDown.do?fileSn=1" title="참고자료(2607).pdf">x</a></td>
    </tr>
    """
    assert p.parse_bok_statements_index(row, 2026) == []


def test_boj_statements_index_url_uses_state_folder_not_mpr() -> None:
    # BOJ moved statements from HTML (state_{year}) to PDF (mpr_{year}) partway through 2026;
    # state_{year} is the one index page that lists both eras (mpr_{year} alone would silently
    # drop every pre-2026 - and Jan-2026 - HTML-format statement), so it must be fetched.
    assert p.boj_statements_index_url(2025) == (
        "https://www.boj.or.jp/en/mopo/mpmdeci/state_2025/index.htm"
    )


def test_parse_boj_statements_index_matches_both_pdf_and_htm_eras() -> None:
    html = (
        '<a href="/en/mopo/mpmdeci/mpr_2026/k260731a.pdf">Statement on Monetary Policy [PDF]</a>'
        '<a href="/en/mopo/mpmdeci/state_2026/k260123a.htm">Statement on Monetary Policy</a>'
    )

    articles = p.parse_boj_statements_index(html)

    by_date = {a.meeting_date: a for a in articles}
    assert set(by_date) == {date(2026, 7, 31), date(2026, 1, 23)}
    assert by_date[date(2026, 7, 31)].pdf_url is not None
    assert by_date[date(2026, 1, 23)].pdf_url is None


def test_parse_boj_minutes_index_matches_htm_era_too() -> None:
    html = '<a href="/en/mopo/mpmsche_minu/minu_2025/g251030.htm">Meeting on Oct 29-30, 2025</a>'

    (article,) = p.parse_boj_minutes_index(html)

    assert article.meeting_date == date(2025, 10, 30)
    assert article.pdf_url is None


def test_extract_boj_text_stops_before_second_outline_div_in_footer() -> None:
    # regression: the container extractor previously re-opened capture on *every* element
    # matching the target class, not just the first - BOJ's page footer also carries
    # `class="outline"`, so real statement text was getting real footer nav/address text
    # silently appended after it.
    html = (
        '<div class="outline mod_outer"><p>Real statement content.</p></div>'
        '<footer><div class="outline"><p>Bank of Japan footer nav text.</p></div></footer>'
    )

    text = p.extract_boj_text(html)

    assert text == "Real statement content."


def test_extract_container_text_only_opens_on_first_match() -> None:
    html = '<main class="x">first</main><main class="x">second</main>'

    text = p.extract_container_text(html, "main", "class", "x")

    assert text == "first"
