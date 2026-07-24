from pathlib import Path

import httpx
import respx
from typer.testing import CliRunner

from investor_intel.cli import app

runner = CliRunner()

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


def test_collect_with_no_config_files_is_a_noop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    result = runner.invoke(
        app,
        [
            "collect",
            "--config-dir",
            str(config_dir),
            "--vault-path",
            str(tmp_path / "vault"),
            "--sqlite-path",
            str(tmp_path / "index.sqlite3"),
        ],
    )
    assert result.exit_code == 0
    assert "총 0건 저장" in result.output


@respx.mock
def test_collect_persists_naver_source_end_to_end(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
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
    respx.get("https://rss.blog.naver.com/testblog.xml").mock(
        return_value=httpx.Response(200, text=_RSS_FEED)
    )

    vault_path = tmp_path / "vault"
    result = runner.invoke(
        app,
        [
            "collect",
            "--config-dir",
            str(config_dir),
            "--vault-path",
            str(vault_path),
            "--sqlite-path",
            str(tmp_path / "index.sqlite3"),
        ],
    )

    assert result.exit_code == 0
    assert "naver_testblog" in result.output
    assert "총 1건 저장" in result.output
    assert list(vault_path.rglob("*.md"))
