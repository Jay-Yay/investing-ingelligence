import json
from pathlib import Path

import httpx
import respx
from typer.testing import CliRunner

from investor_intel.cli import app
from investor_intel.storage.sqlite_index import connect, get_collector_state, init_db

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
    respx.get("https://blog.naver.com/PostView.naver?blogId=testblog&logNo=1").mock(
        return_value=httpx.Response(200, text=_POST_VIEW_HTML)
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


@respx.mock
def test_collect_sources_filter_excludes_unmatched_source_types(
    tmp_path: Path, monkeypatch
) -> None:
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
            "--sources",
            "sec_filing,dart",
        ],
    )

    assert result.exit_code == 0
    assert "naver_testblog" not in result.output
    assert "총 0건 저장" in result.output


@respx.mock
def test_collect_checkpoint_survives_a_rebuilt_sqlite_index(tmp_path: Path, monkeypatch) -> None:
    """GH Actions rebuilds index.sqlite3 from scratch every run (it's gitignored on the data
    branch), which used to wipe collector_state and make every source re-walk its full history
    each day. checkpoints.json is what's supposed to survive that rebuild - assert it does."""
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
    respx.get("https://blog.naver.com/PostView.naver?blogId=testblog&logNo=1").mock(
        return_value=httpx.Response(200, text=_POST_VIEW_HTML)
    )

    vault_path = tmp_path / "vault"
    sqlite_path = tmp_path / "index.sqlite3"
    result = runner.invoke(
        app,
        [
            "collect",
            "--config-dir",
            str(config_dir),
            "--vault-path",
            str(vault_path),
            "--sqlite-path",
            str(sqlite_path),
        ],
    )
    assert result.exit_code == 0

    checkpoints_path = sqlite_path.parent / "checkpoints.json"
    assert checkpoints_path.exists()
    checkpoints = json.loads(checkpoints_path.read_text(encoding="utf-8"))
    assert checkpoints["naver_testblog"]["last_seen_id"] is not None

    # simulate the daily-collect workflow: index.sqlite3 is deleted/rebuilt fresh every run,
    # but checkpoints.json (committed to the data branch) stays on disk.
    sqlite_path.unlink()
    fresh_conn = connect(sqlite_path)
    init_db(fresh_conn)
    assert get_collector_state(fresh_conn, "naver_testblog") is None
    fresh_conn.close()

    result = runner.invoke(
        app,
        [
            "collect",
            "--config-dir",
            str(config_dir),
            "--vault-path",
            str(vault_path),
            "--sqlite-path",
            str(sqlite_path),
        ],
    )
    assert result.exit_code == 0
    # already collected in run 1 and the checkpoint carried forward, so run 2 finds nothing new
    assert "총 0건 저장" in result.output


def test_collect_sources_filter_rejects_unknown_value(tmp_path: Path, monkeypatch) -> None:
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
            "--sources",
            "not_a_real_source",
        ],
    )

    assert result.exit_code == 1
    assert "not_a_real_source" in result.output
