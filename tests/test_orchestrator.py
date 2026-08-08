from types import SimpleNamespace

import httpx
import pytest
import respx

from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.config.settings import AppSettings
from investor_intel.llm.client import AnthropicClient
from investor_intel.market_data.coingecko_adapter import CoinGeckoAdapter
from investor_intel.market_data.yfinance_adapter import YahooFinanceAdapter
from investor_intel.pipeline import orchestrator
from investor_intel.pipeline.analyze import AnalyzeResult
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

_VALID_POSITION_SIGNALS_INPUT = {
    "signals": [
        {
            "symbol": "NBIS",
            "new_facts": [],
            "thesis_shift": "neutral",
            "causal_chain": "특이사항 없음",
            "expectation_vs_price": "확인 불가",
            "counter_evidence": [],
            "decision_status": "pending",
            "signal_strength": 0,
            "action_conditions": "추가 정보 대기",
            "next_check_conditions": "다음 실행 시 재확인",
        }
    ]
}

_VALID_TENBAGGER_CANDIDATES_INPUT: dict = {"candidates": []}

_TOOL_INPUT_BY_NAME = {
    "record_claims": _VALID_CLAIMS_INPUT,
    "record_position_signals": _VALID_POSITION_SIGNALS_INPUT,
    "record_tenbagger_candidates": _VALID_TENBAGGER_CANDIDATES_INPUT,
}


class _FakeAnthropicSDKClient:
    def __init__(self):
        self.messages = SimpleNamespace(create=self._create)
        self.calls = 0

    def _create(self, **kwargs):
        self.calls += 1
        usage = SimpleNamespace(input_tokens=100, output_tokens=50)
        tool_choice = kwargs.get("tool_choice")
        if tool_choice:
            tool_input = _TOOL_INPUT_BY_NAME[tool_choice["name"]]
            return SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", input=tool_input)],
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


def _write_single_position_portfolio_yaml(vault_path) -> None:
    (vault_path / "30_Portfolio").mkdir(parents=True, exist_ok=True)
    (vault_path / "30_Portfolio" / "portfolio.yaml").write_text(
        """as_of: 2026-07-26
base_currency: USD
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
    thesis: "AI 인프라 확장 수혜"
    target_price: null
    stop_loss_price: null
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
    _write_single_position_portfolio_yaml(vault_path)
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
    report_body = report_files[0].read_text(encoding="utf-8")
    assert "오늘의 종합 요약." in report_body
    assert "NBIS" in report_body
    # 포트폴리오 모니터가 낸 판단이 vault 신호 로그(다음날 "전일 판단" 입력)에 기록됐는지 확인
    signal_log = vault_path / "40_Analysis" / "Claims" / "NBIS.md"
    assert signal_log.exists()
    assert "decision_status: pending" in signal_log.read_text(encoding="utf-8")


@respx.mock
def test_run_daily_scrapes_web_research_without_analyzing_it_same_day(tmp_path) -> None:
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
    _write_single_position_portfolio_yaml(vault_path)
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
    web_search_files = list(
        (vault_path / "10_Sources" / "WebSearch" / "NBIS").rglob("*.md")
    )
    assert len(web_search_files) == 1
    # 오늘 스크랩된 문서는 오늘 analyze의 대상이 아니었으므로 llm_processed=false로 남아
    # 있어야 한다 - "scrape only, 오늘은 분석하지 않음" 요구사항의 회귀 방지 검증.
    assert "llm_processed: false" in web_search_files[0].read_text(encoding="utf-8")


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


def test_run_daily_passes_large_doc_client_to_analyze(tmp_path, monkeypatch) -> None:
    """`anthropic_large_doc_model` 설정이 run_daily 경로에서 死코드가 되지 않도록 한다.

    run_daily가 large_doc_client를 넘기지 않으면 analyze는 모든 문서를 기본 모델(sonnet,
    3배 가격)로 돌린다 - 미처리 백로그 대부분이 SEC/central_bank 같은 대형 문서라
    비용 차이가 크다. CLI `analyze`는 이미 넘기고 있었고 run_daily만 누락돼 있었다.
    """
    captured: dict = {}

    def _capture(conn, vault_path, client, cost_tracker, system_prompt, **kwargs):
        captured["client"] = client
        captured.update(kwargs)
        return AnalyzeResult(processed=0)

    monkeypatch.setattr(orchestrator, "analyze_pending_documents", _capture)

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    vault_path = tmp_path / "vault"
    settings = AppSettings(_env_file=None, anthropic_api_key="test-key")
    anthropic_client = AnthropicClient(
        api_key="test-key", model="claude-sonnet-5", client=_FakeAnthropicSDKClient()
    )

    run_daily(
        config_dir=config_dir,
        vault_path=vault_path,
        sqlite_path=tmp_path / "index.sqlite3",
        settings=settings,
        anthropic_client=anthropic_client,
    )

    large_doc_client = captured.get("large_doc_client")
    assert large_doc_client is not None
    assert large_doc_client.model == settings.anthropic_large_doc_model
    assert captured["large_doc_char_threshold"] == settings.large_doc_char_threshold
