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


@respx.mock
@freeze_time("2024-06-01")
def test_10q_captures_full_text_and_tags_title(tmp_path) -> None:
    _mock_submissions()
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1664703/000166470324000010/form10q.htm"
    ).mock(
        return_value=httpx.Response(200, text="<html><body><p>테스트 10-Q 본문</p></body></html>")
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = SECFilingsCollector(_company(), client, CheckpointStore(conn))

    result = collector.backfill(days=45)
    client.close()

    item = result.items[0]
    assert item.title.startswith("[분기보고서] ")
    assert item.content_capture_mode == "full"
    assert "테스트 10-Q 본문" in item.body_text


@respx.mock
@freeze_time("2024-06-01")
def test_8k_captures_transcript_when_exhibit_matches_call_cues(tmp_path) -> None:
    _mock_submissions()
    archive = "https://www.sec.gov/Archives/edgar/data/1664703/000166470324000005"
    respx.get(f"{archive}/index.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "directory": {
                    "item": [
                        {"name": "form8k.htm", "type": "text.gif"},
                        {"name": "ex992transcript.htm", "type": "text.gif"},
                    ]
                }
            },
        )
    )
    respx.get(f"{archive}/ex992transcript.htm").mock(
        return_value=httpx.Response(
            200,
            text=(
                "<html><body>Operator: welcome to the call. "
                "question-and-answer session begins now.</body></html>"
            ),
        )
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = SECFilingsCollector(_company(), client, CheckpointStore(conn))

    result = collector.collect_incremental()
    client.close()

    eightk = next(item for item in result.items if item.filing_type == "8-K")
    assert eightk.title.startswith("[컨퍼런스콜] ")
    assert eightk.content_capture_mode == "full"
    assert "question-and-answer" in eightk.body_text.lower()


@respx.mock
@freeze_time("2024-06-01")
def test_8k_stays_metadata_only_when_no_transcript_exhibit(tmp_path) -> None:
    _mock_submissions()
    archive = "https://www.sec.gov/Archives/edgar/data/1664703/000166470324000005"
    respx.get(f"{archive}/index.json").mock(
        return_value=httpx.Response(
            200, json={"directory": {"item": [{"name": "form8k.htm", "type": "text.gif"}]}}
        )
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = SECFilingsCollector(_company(), client, CheckpointStore(conn))

    result = collector.collect_incremental()
    client.close()

    eightk = next(item for item in result.items if item.filing_type == "8-K")
    assert eightk.content_capture_mode == "metadata_only"
    assert not eightk.title.startswith("[컨퍼런스콜]")


@respx.mock
@freeze_time("2024-06-01")
def test_8k_captures_press_release_when_results_item_present_but_no_transcript_cues(
    tmp_path,
) -> None:
    """실사례(AMZN)에서 발견된 회귀: 8-K 항목 2.02(실적/재무상태 결과)가 있는데 exhibit이
    Operator/Q&A 패턴에 맞지 않으면(순수 보도자료) 이전 로직은 아무것도 캡처하지 않고
    metadata_only로 남겨 실적 디테일을 통째로 놓쳤다. 이제는 그 보도자료 원문을 캡처해야 한다.
    """
    _mock_submissions()
    archive = "https://www.sec.gov/Archives/edgar/data/1664703/000166470324000005"
    respx.get(f"{archive}/index.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "directory": {
                    "item": [
                        {"name": "form8k.htm", "type": "text.gif"},
                        {"name": "ex991pressrelease.htm", "type": "text.gif"},
                    ]
                }
            },
        )
    )
    respx.get(f"{archive}/ex991pressrelease.htm").mock(
        return_value=httpx.Response(
            200, text="<html><body>2분기 매출 5억 달러, 순이익 4천만 달러 발표</body></html>"
        )
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = SECFilingsCollector(_company(), client, CheckpointStore(conn))

    result = collector.collect_incremental()
    client.close()

    eightk = next(item for item in result.items if item.filing_type == "8-K")
    assert eightk.title.startswith("[실적발표 보도자료] ")
    assert eightk.content_capture_mode == "full"
    assert "매출" in eightk.body_text


def _fpi_company() -> CompanyConfig:
    return CompanyConfig(
        ticker="NBIS",
        cik="0001513845",
        name="Nebius Group",
        filing_types=["20-F", "6-K"],
        is_foreign_private_issuer=True,
    )


@respx.mock
@freeze_time("2026-08-12")
def test_6k_with_period_of_report_captures_earnings_exhibit_without_item_codes(
    tmp_path,
) -> None:
    """실사례(NBIS): FPI의 6-K는 8-K 항목 코드가 없어 이전 로직으로는 exhibit을 절대 찾지
    않았다(filing.form == "8-K" 분기에만 들어갔으므로). period_of_report가 채워진 6-K는
    실적 관련으로 간주해 exhibit을 캡처해야 한다.
    """
    respx.get("https://data.sec.gov/submissions/CIK0001513845.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "cik": "1513845",
                "name": "Nebius Group",
                "filings": {
                    "recent": {
                        "accessionNumber": ["0001104659-26-094568"],
                        "filingDate": ["2026-08-12"],
                        "reportDate": ["2026-06-30"],
                        "form": ["6-K"],
                        "primaryDocument": ["tm2622968d1_6k.htm"],
                        "primaryDocDescription": ["6-K"],
                        "items": [""],
                    }
                },
            },
        )
    )
    archive = "https://www.sec.gov/Archives/edgar/data/1513845/000110465926094568"
    respx.get(f"{archive}/index.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "directory": {
                    "item": [
                        {"name": "tm2622968d1_6k.htm", "type": "text.gif"},
                        {"name": "tm2622968d1_ex99-1.htm", "type": "text.gif"},
                    ]
                }
            },
        )
    )
    respx.get(f"{archive}/tm2622968d1_ex99-1.htm").mock(
        return_value=httpx.Response(200, text="<html><body>2분기 매출 5억 달러 발표</body></html>")
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    client = SECClient(user_agent="Investor Intel test@example.com")
    collector = SECFilingsCollector(_fpi_company(), client, CheckpointStore(conn))

    result = collector.collect_incremental()
    client.close()

    sixk = next(item for item in result.items if item.filing_type == "6-K")
    assert sixk.title.startswith("[실적발표 보도자료] ")
    assert sixk.content_capture_mode == "full"
    assert "매출" in sixk.body_text
