from types import SimpleNamespace

import httpx
import pytest
import respx

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.config.settings import AppSettings
from investor_intel.llm.client import AnthropicClient
from investor_intel.market_data.coingecko_adapter import CoinGeckoAdapter
from investor_intel.market_data.yfinance_adapter import YahooFinanceAdapter
from investor_intel.pipeline.orchestrator import run_daily, run_portfolio_stage

_RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>테스트 포스트</title>
      <link>https://blog.naver.com/testblog/1</link>
      <description>&lt;p&gt;본문 내용&lt;/p&gt;</description>
      <author>testblog</author>
      <pubDate>Wed, 01 Jul 2026 09:00:00 +0900</pubDate>
      <guid>https://blog.naver.com/testblog/1</guid>
    </item>
  </channel>
</rss>
"""

_POST_VIEW_HTML = """<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"></head>
<body>
<div class="se-viewer">
  <div class="blog_content">
    <span class="setting">
      <span class="desc">
        <span class="se_publishDate pcol2">2026. 7. 1. 09:00</span>
      </span>
    </span>
  </div>
  <div class="se-module se-module-text se-title-text">
    <p class="se-text-paragraph"><span>테스트 포스트</span></p>
  </div>
  <div class="se-main-container">
    <div class="se-component se-text se-l-default">
      <div class="se-component-content">
        <div class="se-section se-section-text se-l-default">
          <div class="se-module se-module-text">
            <p class="se-text-paragraph"><span>본문 전체 내용</span></p>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>"""

_VALID_CLAIMS_INPUT = {
    "claims": [
        {
            "claim": "테스트 주장",
            "evidence": ["근거"],
            "counter_evidence": [],
            "assets": [],
            "fact_or_opinion": "fact",
            "direction": "bullish",
            "confidence": "high",
        }
    ]
}


class _FakeAnthropicSDKClient:
    def __init__(self):
        self.messages = SimpleNamespace(create=self._create)
        self.calls = 0

    def _create(self, **kwargs):
        self.calls += 1
        usage = SimpleNamespace(input_tokens=100, output_tokens=50)
        tools = kwargs.get("tools")
        if tools:
            return SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", input=_VALID_CLAIMS_INPUT)],
                usage=usage,
            )
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="오늘의 종합 요약.")], usage=usage
        )


def _write_sources_yaml(config_dir) -> None:
    (config_dir / "sources.yaml").write_text(
        """sources:
  - id: naver_testblog
    type: naver
    name: testblog
    enabled: true
    url: https://m.blog.naver.com/testblog
    author: testblog
""",
        encoding="utf-8",
    )


@respx.mock
def test_run_daily_happy_path_produces_report(tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_sources_yaml(config_dir)
    respx.get("https://rss.blog.naver.com/testblog.xml").mock(
        return_value=httpx.Response(200, text=_RSS_FEED)
    )
    respx.get("https://blog.naver.com/PostView.naver?blogId=testblog&logNo=1").mock(
        return_value=httpx.Response(200, text=_POST_VIEW_HTML)
    )

    vault_path = tmp_path / "vault"
    settings = AppSettings(_env_file=None)
    fake_sdk_client = _FakeAnthropicSDKClient()
    anthropic_client = AnthropicClient(
        api_key="test-key", model="claude-sonnet-5", client=fake_sdk_client
    )

    result = run_daily(
        config_dir=config_dir,
        vault_path=vault_path,
        sqlite_path=tmp_path / "index.sqlite3",
        settings=settings,
        anthropic_client=anthropic_client,
    )

    assert result.success is True
    assert result.report_path is not None
    assert result.collect_errors == []
    assert result.analyze_errors == []
    report_files = list((vault_path / "50_Reports" / "Daily").glob("*.md"))
    assert "오늘의 종합 요약." in report_files[0].read_text(encoding="utf-8")


@respx.mock
def test_run_daily_collect_failure_does_not_block_report(tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _write_sources_yaml(config_dir)
    # RSS endpoint intentionally NOT mocked -> the naver collector will fail

    vault_path = tmp_path / "vault"
    settings = AppSettings(_env_file=None)
    fake_sdk_client = _FakeAnthropicSDKClient()
    anthropic_client = AnthropicClient(
        api_key="test-key", model="claude-sonnet-5", client=fake_sdk_client
    )

    result = run_daily(
        config_dir=config_dir,
        vault_path=vault_path,
        sqlite_path=tmp_path / "index.sqlite3",
        settings=settings,
        anthropic_client=anthropic_client,
    )

    assert len(result.collect_errors) == 1
    assert result.success is True
    assert result.report_path is not None


def test_run_daily_without_llm_client_skips_analysis_but_still_reports(tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    vault_path = tmp_path / "vault"
    settings = AppSettings(_env_file=None, anthropic_api_key=None)

    result = run_daily(
        config_dir=config_dir,
        vault_path=vault_path,
        sqlite_path=tmp_path / "index.sqlite3",
        settings=settings,
    )

    assert any("ANTHROPIC_API_KEY" in error for error in result.analyze_errors)
    assert result.success is True
    assert result.report_path is not None


_PORTFOLIO_YAML = """as_of: 2026-07-26
base_currency: KRW
constraints:
  horizon_max_months: 6
  max_single_position_weight: 0.60
  max_sector_weight: 0.60
  leverage_allowed: false
  short_selling_allowed: false
  options_allowed: false
positions:
  - symbol: NBIS
    name: Nebius Group
    asset_type: us_equity
    sector: AI Infrastructure
    quantity: 10
    average_cost: 40.0
    cost_currency: USD
    thesis: ""
    target_price: null
    stop_loss_price: null
  - symbol: "005930"
    name: 삼성전자
    asset_type: kr_equity
    sector: Technology
    quantity: 1
    average_cost: 250000
    cost_currency: KRW
    thesis: ""
    target_price: null
    stop_loss_price: null
"""


@respx.mock
def test_run_portfolio_stage_converts_kr_and_us_positions_to_a_common_currency(tmp_path) -> None:
    # regression: mixing raw USD and KRW market values (no FX conversion) produced nonsense
    # portfolio_weight values once the portfolio held both currencies at once.
    respx.get("https://query1.finance.yahoo.com/v8/finance/chart/NBIS?interval=1d&range=1d").mock(
        return_value=httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "currency": "USD",
                                "symbol": "NBIS",
                                "regularMarketPrice": 50.0,
                                "regularMarketTime": 1753500000,
                            }
                        }
                    ],
                    "error": None,
                }
            },
        )
    )
    respx.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/005930.KS?interval=1d&range=1d"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "currency": "KRW",
                                "symbol": "005930.KS",
                                "regularMarketPrice": 260000.0,
                                "regularMarketTime": 1753500000,
                            }
                        }
                    ],
                    "error": None,
                }
            },
        )
    )
    respx.get(
        "https://query1.finance.yahoo.com/v8/finance/chart/KRW=X?interval=1d&range=1d"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "currency": "KRW",
                                "symbol": "KRW=X",
                                "regularMarketPrice": 1460.0,
                                "regularMarketTime": 1753500000,
                            }
                        }
                    ],
                    "error": None,
                }
            },
        )
    )

    vault_path = tmp_path / "vault"
    (vault_path / "30_Portfolio").mkdir(parents=True)
    (vault_path / "30_Portfolio" / "portfolio.yaml").write_text(
        _PORTFOLIO_YAML, encoding="utf-8"
    )
    yahoo = YahooFinanceAdapter(SimpleHttpClient())
    coingecko = CoinGeckoAdapter(SimpleHttpClient())

    position_rows, violations = run_portfolio_stage(vault_path, yahoo, coingecko)

    by_symbol = {row["symbol"]: row for row in position_rows}
    # NBIS: 10 * 50 USD * 1460 KRW/USD = 730,000 KRW-equivalent; Samsung: 1 * 260,000 KRW
    total_weight = sum(row["portfolio_weight"] for row in position_rows)
    assert total_weight == pytest.approx(1.0)
    assert by_symbol["NBIS"]["portfolio_weight"] == pytest.approx(730_000 / (730_000 + 260_000))
    assert by_symbol["005930"]["portfolio_weight"] == pytest.approx(
        260_000 / (730_000 + 260_000)
    )
    # NBIS's converted weight (~73.7%) breaches both max_single_position_weight and
    # max_sector_weight (60% each) - proving the guardrail check now operates on correctly
    # currency-normalized weights, not raw numbers that happened to look "under 60%" only
    # because USD and KRW were never converted.
    assert {v.rule for v in violations} == {"max_single_position_weight", "max_sector_weight"}
    assert all(v.symbol == "NBIS" for v in violations)
