import io
import zipfile
from pathlib import Path

import httpx
import respx

from investor_intel.collectors.dart_client import DartClient
from investor_intel.collectors.sec_client import SECClient
from investor_intel.config.loaders import (
    load_companies_yaml,
    load_dart_companies_yaml,
    load_investors_yaml,
    load_sources_yaml,
)
from investor_intel.pipeline.inbox import (
    InboxDeps,
    InboxResolveError,
    parse_inbox_lines,
    resolve_dart,
    resolve_ib_insights,
    resolve_investor,
    resolve_naver,
    resolve_sec,
    resolve_telegram,
    resolve_telegram_private,
    sync_inbox,
)
from investor_intel.storage.sqlite_index import connect, init_db, replace_dart_corp_codes

_SEC_TICKERS_JSON = {
    "0": {"cik_str": 1513845, "ticker": "NBIS", "title": "Nebius Group N.V."},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
}


def _sec_client() -> SECClient:
    return SECClient(user_agent="Investor Intel test@example.com")


def _dart_client() -> DartClient:
    return DartClient(api_key="test-api-key")


def _dart_corp_code_zip() -> bytes:
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<result>\n"
        "  <list>\n"
        "    <corp_code>00126380</corp_code>\n"
        "    <corp_name>삼성전자</corp_name>\n"
        "    <stock_code>005930</stock_code>\n"
        "    <modify_date>20260101</modify_date>\n"
        "  </list>\n"
        "</result>\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("CORPCODE.xml", xml)
    return buffer.getvalue()


# --- parsing -----------------------------------------------------------------


def test_parse_inbox_lines_extracts_type_value_and_extra() -> None:
    text = "\n".join(
        [
            "# 소스 Inbox",
            "",
            "- [ ] naver: https://m.blog.naver.com/foo",
            "- [x] telegram: https://t.me/s/bar",
            "- [ ] investor: 0001536411 | https://example.com/essay",
        ]
    )
    lines = parse_inbox_lines(text)

    assert len(lines) == 3
    assert lines[0].checked is False
    assert lines[0].type == "naver"
    assert lines[0].value == "https://m.blog.naver.com/foo"
    assert lines[1].checked is True
    assert lines[1].type == "telegram"
    assert lines[2].value == "0001536411"
    assert lines[2].extra == "https://example.com/essay"


def test_parse_inbox_lines_ignores_blank_and_prose_lines() -> None:
    text = "\n".join(
        [
            "# 소스 Inbox",
            "이 파일은 소스 등록용이다.",
            "",
            "```",
            "naver: https://m.blog.naver.com/example",
            "```",
        ]
    )
    lines = parse_inbox_lines(text)
    assert lines == []


def test_parse_inbox_lines_flags_malformed_checklist_item() -> None:
    text = "- [ ] this-has-no-colon"
    lines = parse_inbox_lines(text)
    assert len(lines) == 1
    assert lines[0].type is None
    assert lines[0].value is None


# --- pure resolvers (naver/telegram) ------------------------------------------


def test_resolve_naver_derives_id_and_name_from_url() -> None:
    entry = resolve_naver("https://m.blog.naver.com/engineerinvestor")
    assert entry.id == "naver_engineerinvestor"
    assert entry.type == "naver"
    assert entry.name == "engineerinvestor"
    assert entry.url == "https://m.blog.naver.com/engineerinvestor"
    # no display name supplied - falls back to the URL slug so `author` is never empty
    assert entry.author == "engineerinvestor"


def test_resolve_naver_uses_supplied_display_name_as_author() -> None:
    # lets a human-readable nickname (e.g. what the blogger is known as in investing
    # communities) resolve to the right source_id/folder later, instead of only the URL slug.
    entry = resolve_naver("https://m.blog.naver.com/tosoha1", "농구천재")
    assert entry.author == "농구천재"
    assert entry.name == "tosoha1"  # id/folder slug stays stable regardless of display name


def test_resolve_telegram_derives_id_from_last_path_segment() -> None:
    entry = resolve_telegram("https://t.me/s/allbareun")
    assert entry.id == "telegram_allbareun"
    assert entry.type == "telegram"
    assert entry.author is None


def test_resolve_telegram_normalizes_bare_channel_url_to_public_preview() -> None:
    # the public-preview collector only understands t.me/s/{channel} - a bare t.me/{channel}
    # link (what users naturally copy from the Telegram app/web) must be normalized to that
    # shape rather than stored as-is and silently breaking collection.
    entry = resolve_telegram("https://t.me/BRILLER_Research")
    assert entry.id == "telegram_BRILLER_Research"
    assert entry.url == "https://t.me/s/BRILLER_Research"


def test_resolve_telegram_uses_supplied_display_name_as_author() -> None:
    entry = resolve_telegram("https://t.me/s/getfeed", "자산증식 정보방")
    assert entry.author == "자산증식 정보방"


def test_resolve_telegram_private_uses_private_prefix() -> None:
    entry = resolve_telegram_private("https://t.me/someprivatechannel")
    assert entry.id == "telegram_private_someprivatechannel"
    assert entry.type == "telegram_private"
    assert entry.author is None


def test_resolve_telegram_private_uses_supplied_display_name_as_author() -> None:
    entry = resolve_telegram_private("https://t.me/someprivatechannel", "비공개방")
    assert entry.author == "비공개방"


def test_resolve_ib_insights_uses_fixed_index_url_per_bank() -> None:
    entry = resolve_ib_insights("jpm_insights", "jpmorgan")
    assert entry.id == "jpm_insights_jpmorgan"
    assert entry.type == "jpm_insights"
    assert entry.name == "jpmorgan"
    assert entry.url == "https://www.jpmorgan.com/insights/research"


def test_resolve_ib_insights_slugifies_free_text_label() -> None:
    entry = resolve_ib_insights("gs_insights", "Goldman Sachs!")
    assert entry.id == "gs_insights_goldman_sachs"
    assert entry.url == "https://www.goldmansachs.com/insights"


# --- sec resolver --------------------------------------------------------------


@respx.mock
def test_resolve_sec_looks_up_cik_and_name(tmp_path: Path) -> None:
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=_SEC_TICKERS_JSON)
    )
    client = _sec_client()
    cache_path = tmp_path / "sec_company_tickers.json"

    entry = resolve_sec("nbis", client, cache_path)
    client.close()

    assert entry.ticker == "NBIS"
    assert entry.cik == "0001513845"
    assert entry.name == "Nebius Group N.V."
    assert entry.filing_types == ["10-K", "10-Q", "8-K"]
    assert entry.is_foreign_private_issuer is False


@respx.mock
def test_resolve_sec_reuses_warm_cache_without_second_request(tmp_path: Path) -> None:
    route = respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=_SEC_TICKERS_JSON)
    )
    client = _sec_client()
    cache_path = tmp_path / "sec_company_tickers.json"

    resolve_sec("AAPL", client, cache_path)
    resolve_sec("NBIS", client, cache_path)
    client.close()

    assert route.call_count == 1


@respx.mock
def test_resolve_sec_raises_for_unknown_ticker(tmp_path: Path) -> None:
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=_SEC_TICKERS_JSON)
    )
    client = _sec_client()
    try:
        try:
            resolve_sec("NOPE", client, tmp_path / "cache.json")
            raise AssertionError("expected InboxResolveError")
        except InboxResolveError:
            pass
    finally:
        client.close()


# --- dart resolver ---------------------------------------------------------------


def test_resolve_dart_uses_warm_cache(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    replace_dart_corp_codes(
        conn, [("00126380", "삼성전자", "005930", "20260101")]
    )
    client = _dart_client()

    entry = resolve_dart("005930", conn, client, "test-api-key")
    client.close()

    assert entry.ticker == "005930"
    assert entry.corp_code == "00126380"
    assert entry.name == "삼성전자"
    assert entry.report_types == ["A", "B"]


@respx.mock
def test_resolve_dart_raises_when_not_found(tmp_path: Path) -> None:
    # cache miss triggers a refresh against OpenDART before giving up
    respx.get("https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=test-api-key").mock(
        return_value=httpx.Response(200, content=_dart_corp_code_zip())
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    replace_dart_corp_codes(conn, [("00126380", "삼성전자", "005930", "20260101")])
    client = _dart_client()

    try:
        resolve_dart("999999", conn, client, "test-api-key")
        raise AssertionError("expected InboxResolveError")
    except InboxResolveError:
        pass
    finally:
        client.close()


# --- investor resolver -------------------------------------------------------------


@respx.mock
def test_resolve_investor_looks_up_entity_name() -> None:
    respx.get("https://data.sec.gov/submissions/CIK0001536411.json").mock(
        return_value=httpx.Response(200, json={"name": "Duquesne Family Office LLC"})
    )
    client = _sec_client()

    entry = resolve_investor("1536411", "https://example.com/essay", client)
    client.close()

    assert entry.cik == "0001536411"
    assert entry.name == "Duquesne Family Office LLC"
    assert entry.fund_name == "Duquesne Family Office LLC"
    assert entry.id == "duquesne_family_office_llc"
    assert entry.related_essay_url == "https://example.com/essay"


def test_resolve_investor_rejects_non_numeric_value() -> None:
    client = _sec_client()
    try:
        resolve_investor("not-a-cik", None, client)
        raise AssertionError("expected InboxResolveError")
    except InboxResolveError:
        pass
    finally:
        client.close()


# --- sync_inbox integration ----------------------------------------------------


def _write_inbox(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_sync_inbox_adds_ib_insights_source_without_network_call(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    inbox_path = tmp_path / "vault" / "00_System" / "inbox_sources.md"
    _write_inbox(inbox_path, ["- [ ] jpm_insights: jpmorgan"])

    deps = InboxDeps(config_dir=config_dir)
    results, new_text = sync_inbox(inbox_path, deps)

    assert results[0].status == "added"
    assert "- [x] jpm_insights: jpmorgan" in new_text
    sources = load_sources_yaml(config_dir / "sources.yaml")
    assert sources[0].type == "jpm_insights"
    assert sources[0].url == "https://www.jpmorgan.com/insights/research"


def test_sync_inbox_adds_naver_and_telegram_sources(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    inbox_path = tmp_path / "vault" / "00_System" / "inbox_sources.md"
    _write_inbox(
        inbox_path,
        [
            "- [ ] naver: https://m.blog.naver.com/foo",
            "- [ ] telegram: https://t.me/s/bar",
        ],
    )

    deps = InboxDeps(config_dir=config_dir)
    results, new_text = sync_inbox(inbox_path, deps)

    statuses = {(r.type, r.status) for r in results}
    assert statuses == {("naver", "added"), ("telegram", "added")}
    assert "- [x] naver: https://m.blog.naver.com/foo" in new_text
    assert "- [x] telegram: https://t.me/s/bar" in new_text

    sources = load_sources_yaml(config_dir / "sources.yaml")
    assert {s.id for s in sources} == {"naver_foo", "telegram_bar"}


def test_sync_inbox_applies_pipe_separated_display_name_to_author(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    inbox_path = tmp_path / "vault" / "00_System" / "inbox_sources.md"
    _write_inbox(
        inbox_path,
        [
            "- [ ] naver: https://m.blog.naver.com/tosoha1 | 농구천재",
            "- [ ] telegram: https://t.me/s/getfeed | 자산증식 정보방",
        ],
    )

    deps = InboxDeps(config_dir=config_dir)
    sync_inbox(inbox_path, deps)

    sources = {s.id: s for s in load_sources_yaml(config_dir / "sources.yaml")}
    assert sources["naver_tosoha1"].author == "농구천재"
    assert sources["telegram_getfeed"].author == "자산증식 정보방"


def test_sync_inbox_skips_duplicate_and_checks_line(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "sources.yaml").write_text(
        "sources:\n"
        "  - id: naver_foo\n"
        "    type: naver\n"
        "    name: foo\n"
        "    enabled: true\n"
        "    url: https://m.blog.naver.com/foo\n"
        "    author: foo\n"
        "    weight: 1.0\n"
        "    collection_mode: full\n"
        "    backfill_days: 365\n"
        "    tags: [blog]\n",
        encoding="utf-8",
    )
    inbox_path = tmp_path / "vault" / "00_System" / "inbox_sources.md"
    _write_inbox(inbox_path, ["- [ ] naver: https://m.blog.naver.com/foo"])

    deps = InboxDeps(config_dir=config_dir)
    results, new_text = sync_inbox(inbox_path, deps)

    assert results[0].status == "skipped_duplicate"
    assert "- [x] naver: https://m.blog.naver.com/foo" in new_text


def test_sync_inbox_leaves_unresolvable_line_unchecked(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    inbox_path = tmp_path / "vault" / "00_System" / "inbox_sources.md"
    _write_inbox(inbox_path, ["- [ ] sec: NBIS"])

    deps = InboxDeps(config_dir=config_dir, sec_client=None)
    results, new_text = sync_inbox(inbox_path, deps)

    assert results[0].status == "failed"
    assert "SEC_USER_AGENT" in results[0].message
    assert "- [ ] sec: NBIS" in new_text
    assert not (config_dir / "companies.yaml").exists()


def test_sync_inbox_ignores_already_checked_lines(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    inbox_path = tmp_path / "vault" / "00_System" / "inbox_sources.md"
    _write_inbox(inbox_path, ["- [x] naver: https://m.blog.naver.com/foo"])

    deps = InboxDeps(config_dir=config_dir)
    results, new_text = sync_inbox(inbox_path, deps)

    assert results == []
    assert not (config_dir / "sources.yaml").exists()


@respx.mock
def test_sync_inbox_adds_sec_company_with_default_filing_types(tmp_path: Path) -> None:
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=_SEC_TICKERS_JSON)
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    inbox_path = tmp_path / "vault" / "00_System" / "inbox_sources.md"
    _write_inbox(inbox_path, ["- [ ] sec: NBIS"])

    client = _sec_client()
    deps = InboxDeps(
        config_dir=config_dir,
        sec_client=client,
        sec_ticker_cache_path=tmp_path / "sec_cache.json",
    )
    results, new_text = sync_inbox(inbox_path, deps)
    client.close()

    assert results[0].status == "added"
    assert "20-F" in results[0].message or "외국민간발행인" in results[0].message
    companies = load_companies_yaml(config_dir / "companies.yaml")
    assert companies[0].ticker == "NBIS"
    assert companies[0].filing_types == ["10-K", "10-Q", "8-K"]


def test_sync_inbox_adds_dart_company_preserving_header_comment(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "index.sqlite3"
    conn = connect(sqlite_path)
    init_db(conn)
    replace_dart_corp_codes(conn, [("00126380", "삼성전자", "005930", "20260101")])

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    inbox_path = tmp_path / "vault" / "00_System" / "inbox_sources.md"
    _write_inbox(inbox_path, ["- [ ] dart: 005930"])

    dart_client = _dart_client()
    deps = InboxDeps(
        config_dir=config_dir,
        dart_conn=conn,
        dart_client=dart_client,
        dart_api_key="test-api-key",
    )
    results, _ = sync_inbox(inbox_path, deps)
    dart_client.close()

    assert results[0].status == "added"
    dart_companies = load_dart_companies_yaml(config_dir / "dart_companies.yaml")
    assert dart_companies[0].ticker == "005930"
    assert dart_companies[0].name == "삼성전자"

    raw = (config_dir / "dart_companies.yaml").read_text(encoding="utf-8")
    assert "corp_code는 생략 가능" in raw


@respx.mock
def test_sync_inbox_adds_investor_with_essay_url(tmp_path: Path) -> None:
    respx.get("https://data.sec.gov/submissions/CIK0002045724.json").mock(
        return_value=httpx.Response(200, json={"name": "Situational Awareness LP"})
    )
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    inbox_path = tmp_path / "vault" / "00_System" / "inbox_sources.md"
    _write_inbox(
        inbox_path, ["- [ ] investor: 0002045724 | https://situational-awareness.ai/"]
    )

    client = _sec_client()
    deps = InboxDeps(config_dir=config_dir, sec_client=client)
    results, _ = sync_inbox(inbox_path, deps)
    client.close()

    assert results[0].status == "added"
    investors = load_investors_yaml(config_dir / "investors.yaml")
    assert investors[0].cik == "0002045724"
    assert investors[0].related_essay_url == "https://situational-awareness.ai/"


def test_sync_inbox_reports_unsupported_type(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    inbox_path = tmp_path / "vault" / "00_System" / "inbox_sources.md"
    _write_inbox(inbox_path, ["- [ ] youtube: https://youtube.com/foo"])

    deps = InboxDeps(config_dir=config_dir)
    results, new_text = sync_inbox(inbox_path, deps)

    assert results[0].status == "parse_error"
    assert "youtube" in results[0].message
    assert "- [ ] youtube: https://youtube.com/foo" in new_text
