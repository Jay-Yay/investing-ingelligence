from types import SimpleNamespace

import httpx
import respx

from investor_intel.config.settings import AppSettings
from investor_intel.llm.client import AnthropicClient
from investor_intel.pipeline.orchestrator import run_daily

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
