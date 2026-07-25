from investor_intel.collectors.ib_insights_parser import (
    parse_bofa_insights_index,
    parse_gs_insights_index,
    parse_jpm_insights_index,
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
