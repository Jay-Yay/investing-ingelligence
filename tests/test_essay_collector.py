from pathlib import Path

import httpx
import pytest
import respx
from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.essay import EssayCollector
from investor_intel.collectors.http_client import SimpleHttpClient
from investor_intel.models.config import InvestorConfig
from investor_intel.storage.sqlite_index import connect, init_db

FIXTURES = Path(__file__).parent / "fixtures" / "essay"
_ESSAY_URL = "https://situational-awareness.ai/"


def _investor(related_essay_url: str | None = _ESSAY_URL) -> InvestorConfig:
    return InvestorConfig(
        id="situational_awareness",
        name="Leopold Aschenbrenner",
        fund_name="Situational Awareness LP",
        cik="0001234567",
        related_essay_url=related_essay_url,
    )


def _mock_essay_page() -> None:
    respx.get(_ESSAY_URL).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "wordpress_essay.html").read_text(encoding="utf-8")
        )
    )


def test_constructor_rejects_investor_without_essay_url(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    with pytest.raises(ValueError):
        EssayCollector(_investor(related_essay_url=None), client, CheckpointStore(conn))
    client.close()


@respx.mock
@freeze_time("2026-07-24T10:00:00+00:00")
def test_collect_incremental_returns_one_item(tmp_path) -> None:
    _mock_essay_page()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    collector = EssayCollector(_investor(), client, CheckpointStore(conn))

    result = collector.collect_incremental()
    client.close()

    assert result.success
    assert result.new_count == 1
    item = result.items[0]
    assert item.canonical_url == _ESSAY_URL
    assert item.title == "SITUATIONAL AWARENESS: The Decade Ahead"
    assert item.document_type == "essay"
    assert item.published_at.isoformat() == "2026-07-24T10:00:00+00:00"


@respx.mock
def test_published_at_is_pinned_across_runs(tmp_path) -> None:
    _mock_essay_page()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    checkpoint_store = CheckpointStore(conn)

    with freeze_time("2026-07-24T10:00:00+00:00"):
        first_result = EssayCollector(_investor(), client, checkpoint_store).collect_incremental()

    with freeze_time("2026-07-25T10:00:00+00:00"):
        second_result = EssayCollector(_investor(), client, checkpoint_store).collect_incremental()

    client.close()

    assert first_result.items[0].published_at == second_result.items[0].published_at
    assert second_result.items[0].published_at.isoformat() == "2026-07-24T10:00:00+00:00"


@respx.mock
@freeze_time("2026-07-24T10:00:00+00:00")
def test_backfill_delegates_to_same_collect(tmp_path) -> None:
    _mock_essay_page()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SimpleHttpClient()
    collector = EssayCollector(_investor(), client, CheckpointStore(conn))

    result = collector.backfill(days=30)
    client.close()

    assert result.success
    assert result.new_count == 1
