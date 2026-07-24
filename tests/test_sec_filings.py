from pathlib import Path

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.sec_client import SECClient
from investor_intel.collectors.sec_filings import SECFilingsCollector
from investor_intel.models.config import CompanyConfig
from investor_intel.storage.sqlite_index import connect, init_db

FIXTURES = Path(__file__).parent / "fixtures" / "sec"


def _company() -> CompanyConfig:
    return CompanyConfig(
        ticker="BE",
        cik="0001664703",
        name="Bloom Energy",
        filing_types=["10-K", "10-Q", "8-K"],
        is_foreign_private_issuer=False,
    )


def _mock_submissions() -> None:
    respx.get("https://data.sec.gov/submissions/CIK0001664703.json").mock(
        return_value=httpx.Response(
            200,
            text=(FIXTURES / "submissions_company_test.json").read_text(encoding="utf-8"),
        )
    )


def _mock_companyfacts(status_code: int = 200) -> respx.Route:
    return respx.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0001664703.json").mock(
        return_value=httpx.Response(
            status_code,
            text=(
                (FIXTURES / "companyfacts_be_test.json").read_text(encoding="utf-8")
                if status_code == 200
                else ""
            ),
        )
    )


@respx.mock
@freeze_time("2024-06-01")
def test_backfill_returns_only_in_window_filing(tmp_path) -> None:
    _mock_submissions()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = SECFilingsCollector(_company(), client, CheckpointStore(conn))

    result = collector.backfill(days=45)
    client.close()

    assert result.success
    assert result.new_count == 1
    item = result.items[0]
    assert item.accession_number == "0001664703-24-000010"
    assert item.filing_type == "10-Q"
    assert item.reporting_period == "2024-03-31"
    assert item.content_capture_mode == "metadata_only"


@respx.mock
@freeze_time("2024-06-01")
def test_collect_incremental_excludes_unconfigured_form_and_is_idempotent(tmp_path) -> None:
    _mock_submissions()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    checkpoint_store = CheckpointStore(conn)

    first_collector = SECFilingsCollector(_company(), client, checkpoint_store)
    first_result = first_collector.collect_incremental()
    # 4 filings in the fixture, but "SC 13G" is not in company.filing_types
    assert first_result.new_count == 3
    assert all(item.filing_type != "SC 13G" for item in first_result.items)

    second_collector = SECFilingsCollector(_company(), client, checkpoint_store)
    second_result = second_collector.collect_incremental()
    client.close()

    assert second_result.new_count == 0
    assert second_result.items == []


@respx.mock
@freeze_time("2024-06-01")
def test_source_id_uses_lowercased_ticker(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = SECFilingsCollector(_company(), client, CheckpointStore(conn))
    client.close()
    assert collector.source_id == "sec_filings_be"


@respx.mock
@freeze_time("2024-06-01")
def test_backfill_appends_financial_snapshot_when_companyfacts_available(tmp_path) -> None:
    _mock_submissions()
    _mock_companyfacts()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = SECFilingsCollector(_company(), client, CheckpointStore(conn))

    result = collector.backfill(days=45)
    client.close()

    item = result.items[0]
    assert item.accession_number == "0001664703-24-000010"
    assert "## 재무 데이터 (XBRL)" in item.body_text
    assert "330,000,000" in item.body_text


@respx.mock
@freeze_time("2024-06-01")
def test_companyfacts_fetched_only_once_per_collect_call(tmp_path) -> None:
    _mock_submissions()
    route = _mock_companyfacts()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = SECFilingsCollector(_company(), client, CheckpointStore(conn))

    result = collector.collect_incremental()
    client.close()

    # 3 filings collected (SC 13G excluded), but companyfacts should be fetched exactly once
    assert result.new_count == 3
    assert route.call_count == 1


@respx.mock
@freeze_time("2024-06-01")
def test_missing_companyfacts_degrades_gracefully_without_failing_collection(tmp_path) -> None:
    _mock_submissions()
    _mock_companyfacts(status_code=404)
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = SECFilingsCollector(_company(), client, CheckpointStore(conn))

    result = collector.backfill(days=45)
    client.close()

    assert result.success
    assert result.new_count == 1
    assert "## 재무 데이터 (XBRL)" not in result.items[0].body_text


@respx.mock
@freeze_time("2024-06-01")
def test_8k_item_without_report_date_still_produces_item(tmp_path) -> None:
    _mock_submissions()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = SECFilingsCollector(_company(), client, CheckpointStore(conn))

    result = collector.collect_incremental()
    client.close()

    eightk = next(item for item in result.items if item.filing_type == "8-K")
    assert eightk.reporting_period is None
    assert "2.02" in eightk.body_text
