from pathlib import Path

import httpx
import respx
from freezegun import freeze_time

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.sec_client import SECClient
from investor_intel.collectors.sec_thirteenf import ThirteenFCollector
from investor_intel.models.config import InvestorConfig
from investor_intel.storage.sqlite_index import connect, init_db

FIXTURES = Path(__file__).parent / "fixtures" / "sec"


def _investor() -> InvestorConfig:
    return InvestorConfig(
        id="duquesne_family_office",
        name="Stanley Druckenmiller",
        fund_name="Duquesne Family Office LLC",
        cik="0001536411",
    )


def _mock_sec_routes() -> None:
    respx.get("https://data.sec.gov/submissions/CIK0001536411.json").mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "submissions_1536411.json").read_text(encoding="utf-8")
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1536411/000153641124000007/index.json"
    ).mock(
        return_value=httpx.Response(
            200,
            text=(FIXTURES / "index_0001536411-24-000007.json").read_text(encoding="utf-8"),
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1536411/000153641124000007/form13fInfoTable.xml"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "form13fInfoTable_current.xml").read_text(encoding="utf-8")
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1536411/000153641123000004/index.json"
    ).mock(
        return_value=httpx.Response(
            200,
            text=(FIXTURES / "index_0001536411-23-000004.json").read_text(encoding="utf-8"),
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1536411/000153641123000004/form13fInfoTable.xml"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "form13fInfoTable_previous.xml").read_text(encoding="utf-8")
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1536411/000153641122000002/index.json"
    ).mock(
        return_value=httpx.Response(
            200,
            text=(FIXTURES / "index_0001536411-22-000002.json").read_text(encoding="utf-8"),
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1536411/000153641122000002/form13fInfoTable.xml"
    ).mock(
        return_value=httpx.Response(
            200, text=(FIXTURES / "form13fInfoTable_oldest.xml").read_text(encoding="utf-8")
        )
    )


@respx.mock
@freeze_time("2024-06-01")
def test_backfill_returns_only_in_window_filing_with_computed_changes(tmp_path) -> None:
    _mock_sec_routes()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = ThirteenFCollector(_investor(), client, CheckpointStore(conn))

    result = collector.backfill(days=180)
    client.close()

    assert result.success
    assert result.new_count == 1
    item = result.items[0]
    assert item.accession_number == "0001536411-24-000007"
    assert item.reporting_period == "2024-03-31"
    assert item.filing_type == "13F-HR"
    assert "ALPHABET INC" in item.body_text
    assert "new" in item.body_text  # ALPHABET is NEW vs previous quarter
    assert "sold_out" in item.body_text  # MICROSOFT sold out vs previous quarter
    assert "increased" in item.body_text  # NVIDIA increased vs previous quarter


@respx.mock
@freeze_time("2024-06-01")
def test_backfill_caches_previous_filing_fetch(tmp_path) -> None:
    _mock_sec_routes()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = ThirteenFCollector(_investor(), client, CheckpointStore(conn))

    collector.backfill(days=180)
    client.close()

    previous_xml_route = respx.get(
        "https://www.sec.gov/Archives/edgar/data/1536411/000153641123000004/form13fInfoTable.xml"
    )
    assert previous_xml_route.call_count == 1


@respx.mock
@freeze_time("2024-06-01")
def test_collect_incremental_advances_checkpoint_and_is_idempotent(tmp_path) -> None:
    _mock_sec_routes()
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    checkpoint_store = CheckpointStore(conn)

    first_collector = ThirteenFCollector(_investor(), client, checkpoint_store)
    first_result = first_collector.collect_incremental()
    assert first_result.new_count == 3  # all 3 filings are new on first run

    second_collector = ThirteenFCollector(_investor(), client, checkpoint_store)
    second_result = second_collector.collect_incremental()
    client.close()

    assert second_result.new_count == 0
    assert second_result.items == []


@respx.mock
@freeze_time("2024-06-01")
def test_source_id_includes_investor_id(tmp_path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = ThirteenFCollector(_investor(), client, CheckpointStore(conn))
    client.close()
    assert collector.source_id == "sec_13f_duquesne_family_office"
