import httpx
import respx
import yaml

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.dart import DartCollector
from investor_intel.collectors.essay import EssayCollector
from investor_intel.collectors.sec_thirteenf import ThirteenFCollector
from investor_intel.config.settings import AppSettings
from investor_intel.models.common import SourceType
from investor_intel.pipeline.collect import build_collect_entries
from investor_intel.storage.sqlite_index import connect, init_db

_CORP_CODE_XML = (
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


def _corp_code_zip_bytes() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("CORPCODE.xml", _CORP_CODE_XML)
    return buffer.getvalue()


def _write_investors_yaml(config_dir) -> None:
    (config_dir).mkdir(parents=True, exist_ok=True)
    data = {
        "investors": [
            {
                "id": "situational_awareness",
                "name": "Leopold Aschenbrenner",
                "fund_name": "Situational Awareness LP",
                "cik": "0001234567",
                "related_essay_url": "https://situational-awareness.ai/",
            },
            {
                "id": "berkshire",
                "name": "Warren Buffett",
                "fund_name": "Berkshire Hathaway",
                "cik": "0000010001",
            },
        ]
    }
    (config_dir / "investors.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def test_build_collect_entries_adds_essay_collector_only_for_investor_with_url(
    tmp_path,
) -> None:
    _write_investors_yaml(tmp_path)
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    checkpoint_store = CheckpointStore(conn)
    settings = AppSettings(sec_user_agent="Test test@example.com")

    entries, setup_errors = build_collect_entries(tmp_path, settings, checkpoint_store, conn)

    assert setup_errors == []

    essay_entries = [e for e in entries if isinstance(e[0], EssayCollector)]
    assert len(essay_entries) == 1
    essay_collector, source_type, source_name = essay_entries[0]
    assert source_type == SourceType.ESSAY
    assert source_name == "situational_awareness"
    assert essay_collector.source_id == "essay_situational_awareness"

    thirteenf_entries = [e for e in entries if isinstance(e[0], ThirteenFCollector)]
    assert len(thirteenf_entries) == 2


def _write_dart_companies_yaml(config_dir, companies: list[dict]) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "dart_companies.yaml").write_text(
        yaml.safe_dump({"dart_companies": companies}), encoding="utf-8"
    )


@respx.mock
def test_build_collect_entries_resolves_missing_dart_corp_code(tmp_path) -> None:
    respx.get(
        "https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=test-dart-key"
    ).mock(return_value=httpx.Response(200, content=_corp_code_zip_bytes()))

    _write_dart_companies_yaml(
        tmp_path,
        [
            {"ticker": "005930", "name": "삼성전자"},
            {"ticker": "999999", "name": "존재하지않음"},
        ],
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    checkpoint_store = CheckpointStore(conn)
    settings = AppSettings(dart_api_key="test-dart-key")

    entries, setup_errors = build_collect_entries(tmp_path, settings, checkpoint_store, conn)

    dart_entries = [e for e in entries if isinstance(e[0], DartCollector)]
    assert len(dart_entries) == 1
    assert dart_entries[0][2] == "005930"
    assert any("999999" in error for error in setup_errors)


@respx.mock
def test_build_collect_entries_skips_resolution_when_corp_code_already_set(tmp_path) -> None:
    _write_dart_companies_yaml(
        tmp_path, [{"ticker": "005930", "corp_code": "00126380", "name": "삼성전자"}]
    )
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    checkpoint_store = CheckpointStore(conn)
    settings = AppSettings(dart_api_key="test-dart-key")

    # no respx route registered at all - a real network call here would raise
    entries, setup_errors = build_collect_entries(tmp_path, settings, checkpoint_store, conn)

    assert setup_errors == []
    dart_entries = [e for e in entries if isinstance(e[0], DartCollector)]
    assert len(dart_entries) == 1


def _write_sources_yaml(config_dir, sources: list[dict]) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "sources.yaml").write_text(
        yaml.safe_dump({"sources": sources}), encoding="utf-8"
    )


_PRIVATE_SOURCE = {
    "id": "telegram_private_allbareun",
    "type": "telegram_private",
    "name": "allbareun (비공개)",
    "enabled": True,
    "url": "https://t.me/allbareun_private",
    "author": None,
}


def test_build_collect_entries_skips_telegram_private_without_credentials(tmp_path) -> None:
    _write_sources_yaml(tmp_path, [_PRIVATE_SOURCE])
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    checkpoint_store = CheckpointStore(conn)
    settings = AppSettings()

    entries, setup_errors = build_collect_entries(tmp_path, settings, checkpoint_store, conn)

    assert entries == []
    assert any("telegram_private_allbareun" in error for error in setup_errors)


def test_build_collect_entries_adds_telegram_private_when_credentials_present(
    tmp_path, monkeypatch
) -> None:
    from investor_intel.collectors.telegram_private import TelethonPrivateChannelCollector

    class _FakeRealTelethonClient:
        def __init__(self, session: str, api_id: int, api_hash: str) -> None:
            self.session = session
            self.api_id = api_id
            self.api_hash = api_hash

    monkeypatch.setattr(
        "investor_intel.collectors.telethon_client.RealTelethonClient",
        _FakeRealTelethonClient,
    )

    _write_sources_yaml(tmp_path, [_PRIVATE_SOURCE])
    conn = connect(tmp_path / "index.sqlite3")
    init_db(conn)
    checkpoint_store = CheckpointStore(conn)
    settings = AppSettings(
        telegram_api_id="12345",
        telegram_api_hash="test-hash",
        telegram_session="test-session-string",
    )

    entries, setup_errors = build_collect_entries(tmp_path, settings, checkpoint_store, conn)

    assert setup_errors == []
    telethon_entries = [e for e in entries if isinstance(e[0], TelethonPrivateChannelCollector)]
    assert len(telethon_entries) == 1
    collector, source_type, source_name = telethon_entries[0]
    assert source_type == SourceType.TELEGRAM
    assert source_name == "allbareun (비공개)"
    assert collector.source_id == "telegram_private_allbareun"
