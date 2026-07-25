from investor_intel.collectors.ib_insights_parser import (
    find_citi_pdf_link,
    find_pdf_href,
    parse_blackrock_insights_index,
    parse_bofa_insights_index,
    parse_citi_insights_index,
    parse_gs_insights_index,
    parse_jpm_insights_index,
    parse_naver_research_index,
    parse_vanguard_insights_index,
)

_GS_HTML = """
<html><body>
<a data-gs-uitk-component="card" href="/insights/articles/stock-valuations">
  <div><h3>Markets</h3>
    <h4 data-gs-uitk-component="card-title">
      <span data-gs-uitk-component="text">Are US Stock Valuations Outpacing Fundamentals?</span>
    </h4>
    <div data-gs-uitk-component="card-meta">
      <span data-gs-uitk-component="text">Jul 10, 2026</span>
    </div>
  </div>
</a>
<a data-gs-uitk-component="card" href="https://www.goldmansachs.com/insights/space-economy">
  <h4 data-gs-uitk-component="card-title">
    <span data-gs-uitk-component="text">How Falling Launch Costs Are Driving Space</span>
  </h4>
</a>
<a href="/insights/not-a-card">Not a tracked card (no data-gs-uitk-component=card)</a>
</body></html>
"""

_JPM_HTML = """
<html><body>
<div class="one-up-content">
  <h3><a class="card-headline" href="/insights/global-research/outlook/mid-year-outlook">
    Mid-year market outlook 2026: The tug of war continues
  </a></h3>
  <p class="date">Jul 01, 2026</p>
  <p class="info">While the global expansion stands on solid ground, markets need balance.</p>
  <a href="/insights/global-research/outlook/mid-year-outlook" class="btn">Read more</a>
</div>
<div class="card">
  <h3><a class="card-headline" href="/insights/markets/second-article">Second Research Note</a></h3>
  <p class="date">Jun 15, 2026</p>
  <p class="info">A shorter teaser for the second note.</p>
</div>
<a href="/insights/banking">Banking (not a card-headline link)</a>
</body></html>
"""

_BOFA_URL = (
    "https://business.bofa.com/content/boaml/en_us/flagship/global-research/"
    "ai-10-secret-ingredients.html"
)
_BOFA_HTML = f"""
<html><body>
<a class="tile-anchor js-tile-anchor" href="{_BOFA_URL}">
  <div class="tile">
    <h4 class="tile__headline">Matter Over Mind: AI's 10 Secret Ingredients</h4>
    <div class="tile__body">
      <p>It's well known that AI requires semiconductors and power to build.</p>
    </div>
    <div class="tile__metadata"><div class="tile__metadata-text">2 min read</div></div>
  </div>
</a>
<a class="tile-anchor" href="/en-us/content/economic-micro-themes.html">
  <h4 class="tile__headline">10 Micro Themes for 2026</h4>
  <div class="tile__body"><p>From M&amp;A and AI to industrial and consumer trends.</p></div>
</a>
<a href="/en-us/content/not-a-tile.html">Not a tile-anchor card</a>
</body></html>
"""

_CITI_HTML = """
<html><body>
<article data-id="gpa-card">
  <div><h3 class="citigroup-h3 title___wHYWs">Sizing the ETF Opportunity</h3>
  <p class="Summary citigroup-h6 summary___MGwOO"><p>Citi Research explores US ETFs.</p></p>
  <a href="/global/insights/sizing-the-etf-opportunity" target="_blank">Learn More</a>
  </div>
</article>
<article data-id="gpa-card">
  <h3 class="title___abc">Middle East Turmoil</h3>
  <p class="Summary summary___xyz">An energy-led supply shock.</p>
  <a href="/global/insights/middle-east-turmoil">Learn More</a>
</article>
<article data-id="not-a-gpa-card"><h3 class="title___zzz">Ignored</h3></article>
</body></html>
"""

_BLACKROCK_HTML = """
<html><body>
<li class="article-cntnr tile-box">
<a href="https://www.blackrock.com/us/individual/insights/fixed-income-outlook"
   title="Fixed Income Outlook" class="cta link article-wrapper-link skip-animation">
  <h2 class="title">Fixed Income Outlook</h2>
  <div class="attribution-text date ">
    <div class="attribution-text">
      <span>Jul 23, 2026</span>
      <span class="separator">|</span>
      <span>By</span>
      <span class="author-name">BlackRock</span>
    </div>
  </div>
  <div class="description">Q3 2026 Fixed Income Outlook from BlackRock.</div>
</a>
</li>
<li class="article-cntnr tile-box">
<a href="https://www.blackrock.com/us/individual/insights/whats-driving-gold"
   title="What is going on with gold?" class="cta link article-wrapper-link skip-animation">
  <div class="attribution-text date ">
    <div class="attribution-text"><span>Jul 22, 2026</span></div>
  </div>
  <div class="description">Russ Koesterich explains gold's recent fall.</div>
</a>
</li>
<a href="/us/individual/insights">Not a card (no article-wrapper-link class)</a>
</body></html>
"""

_VANGUARD_HTML = """
<html><body>
<div class="cmp-articlecard-content">
  <h3 class="cmp-articlecard__heading">
    <a href="/investor-resources-education/retirement/rmd-rules-for-inherited-iras"
       title="Inherited IRA RMD rules" class="cmp-articlecard-content__link" target="_self">
      <div class="cmp-articlecard__title">Inherited IRA RMD rules<span></span></div>
    </a>
  </h3>
  <div class="cmp-articlecard-content__description">Learn inherited IRA RMD rules.</div>
</div>
<div class="cmp-articlecard-content">
  <h3 class="cmp-articlecard__heading">
    <a href="/investor-resources-education/article/how-to-set-up-backdoor-ira"
       title="Backdoor Roth IRA" class="cmp-articlecard-content__link" target="_self">
      <div class="cmp-articlecard__title">Backdoor Roth IRA</div>
    </a>
  </h3>
  <div class="cmp-articlecard-content__description">What is a backdoor Roth IRA?</div>
</div>
<a href="/investor-resources-education/other">Not a card (no matching class)</a>
</body></html>
"""


def test_parse_gs_insights_index_extracts_title_and_absolutizes_relative_url() -> None:
    articles = parse_gs_insights_index(_GS_HTML)

    assert len(articles) == 2
    assert articles[0].title == "Are US Stock Valuations Outpacing Fundamentals?"
    assert articles[0].url == "https://www.goldmansachs.com/insights/articles/stock-valuations"
    assert articles[0].published_at is None
    assert articles[0].summary is None
    assert articles[1].url == "https://www.goldmansachs.com/insights/space-economy"


def test_parse_jpm_insights_index_extracts_title_date_and_summary() -> None:
    articles = parse_jpm_insights_index(_JPM_HTML)

    assert len(articles) == 2
    first = articles[0]
    assert first.title == "Mid-year market outlook 2026: The tug of war continues"
    assert first.url == (
        "https://www.jpmorgan.com/insights/global-research/outlook/mid-year-outlook"
    )
    assert first.published_at.isoformat() == "2026-07-01"
    assert "global expansion" in first.summary

    second = articles[1]
    assert second.title == "Second Research Note"
    assert second.published_at.isoformat() == "2026-06-15"


def test_parse_bofa_insights_index_extracts_title_and_summary_without_date() -> None:
    articles = parse_bofa_insights_index(_BOFA_HTML)

    assert len(articles) == 2
    first = articles[0]
    assert first.title == "Matter Over Mind: AI's 10 Secret Ingredients"
    assert first.url == _BOFA_URL
    assert first.published_at is None
    assert "semiconductors" in first.summary

    second = articles[1]
    assert second.url == "https://business.bofa.com/en-us/content/economic-micro-themes.html"
    assert "M&A" in second.summary


def test_parse_citi_insights_index_handles_malformed_nested_summary_p() -> None:
    articles = parse_citi_insights_index(_CITI_HTML)

    assert len(articles) == 2
    first = articles[0]
    assert first.title == "Sizing the ETF Opportunity"
    assert first.url == "https://www.citigroup.com/global/insights/sizing-the-etf-opportunity"
    assert first.published_at is None
    assert "Citi Research" in first.summary

    second = articles[1]
    assert second.title == "Middle East Turmoil"
    assert second.url == "https://www.citigroup.com/global/insights/middle-east-turmoil"


def test_parse_blackrock_insights_index_extracts_title_date_and_summary() -> None:
    articles = parse_blackrock_insights_index(_BLACKROCK_HTML)

    assert len(articles) == 2
    first = articles[0]
    assert first.title == "Fixed Income Outlook"
    assert first.url == "https://www.blackrock.com/us/individual/insights/fixed-income-outlook"
    assert first.published_at.isoformat() == "2026-07-23"
    assert "Q3 2026" in first.summary

    second = articles[1]
    assert second.title == "What is going on with gold?"
    assert second.published_at.isoformat() == "2026-07-22"
    assert "Koesterich" in second.summary


def test_parse_vanguard_insights_index_extracts_title_and_summary() -> None:
    articles = parse_vanguard_insights_index(_VANGUARD_HTML)

    assert len(articles) == 2
    first = articles[0]
    assert first.title == "Inherited IRA RMD rules"
    assert first.url == (
        "https://investor.vanguard.com/investor-resources-education/retirement/"
        "rmd-rules-for-inherited-iras"
    )
    assert first.published_at is None
    assert "RMD rules" in first.summary

    second = articles[1]
    assert second.title == "Backdoor Roth IRA"
    assert "backdoor Roth IRA" in second.summary


def test_find_pdf_href_matches_and_absolutizes_relative_link() -> None:
    html = '<a href="/content/dam/flagship/global-research/report.pdf">Download</a>'
    link = find_pdf_href(html, "https://business.bofa.com")
    assert link == "https://business.bofa.com/content/dam/flagship/global-research/report.pdf"


def test_find_pdf_href_leaves_absolute_link_unchanged() -> None:
    html = '<a href="https://www.blackrock.com/literature/outlook.pdf">Download</a>'
    link = find_pdf_href(html, "https://www.blackrock.com")
    assert link == "https://www.blackrock.com/literature/outlook.pdf"


def test_find_pdf_href_returns_none_when_no_pdf_link_present() -> None:
    html = '<a href="/insights/some-article">Read more</a>'
    assert find_pdf_href(html, "https://x.com") is None


def test_find_citi_pdf_link_extracts_ir_redirect_url() -> None:
    html = (
        '{"type":"TextAndImageWithCTA","content":{"title":"Must C",'
        '"buttonName":"Download Here",'
        '"buttonLink":"https://ir.citi.com/abcDEF123%3D"},"bodyText":""}'
    )
    link = find_citi_pdf_link(html, "https://www.citigroup.com")
    assert link == "https://ir.citi.com/abcDEF123%3D"


def test_find_citi_pdf_link_returns_none_when_absent() -> None:
    assert find_citi_pdf_link("no download button here", "https://www.citigroup.com") is None


_NAVER_RESEARCH_HTML = """
<html><body><table>
<tr>
  <td style="padding-left:10">
    <a href="/item/main.naver?code=017670" title="SK텔레콤" class="stock_item">SK텔레콤</a>
  </td>
  <td>
    <a href="company_read.naver?nid=94484&page=1">AIDC 사업개발 전문회사 SK하이퍼 설립 관련</a>
  </td>
  <td>신한투자증권</td>
  <td class="file"></td>
  <td class="date" style="padding-left:5px">26.07.24</td>
  <td class="date">6138</td>
</tr>
<tr>
  <td style="padding-left:10">
    <a href="/item/main.naver?code=251970" title="펌텍코리아" class="stock_item">펌텍코리아</a>
  </td>
  <td><a href="company_read.naver?nid=94483&page=1">정상화, 개선 그리고 추가 증설</a></td>
  <td>한화투자증권</td>
  <td class="file">
    <a href="https://stock.pstatic.net/stock-research/company/16/report.pdf" target="_blank">
      <img src="https://ssl.pstatic.net/imgstock/images5/down.gif" alt="pdf">
    </a>
  </td>
  <td class="date" style="padding-left:5px">26.07.24</td>
  <td class="date">3664</td>
</tr>
</table></body></html>
"""


def test_parse_naver_research_index_extracts_rows_with_and_without_pdf() -> None:
    articles = parse_naver_research_index(_NAVER_RESEARCH_HTML)

    assert len(articles) == 2
    first = articles[0]
    assert first.title == "[SK텔레콤] AIDC 사업개발 전문회사 SK하이퍼 설립 관련"
    assert first.url == "https://finance.naver.com/research/company_read.naver?nid=94484"
    assert first.author == "신한투자증권"
    assert first.published_at.isoformat() == "2026-07-24"
    assert first.pdf_url is None

    second = articles[1]
    assert second.title == "[펌텍코리아] 정상화, 개선 그리고 추가 증설"
    assert second.author == "한화투자증권"
    assert second.pdf_url == "https://stock.pstatic.net/stock-research/company/16/report.pdf"
