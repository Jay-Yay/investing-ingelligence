import yaml

from investor_intel.collectors.base import CheckpointStore
from investor_intel.collectors.essay import EssayCollector
from investor_intel.collectors.sec_thirteenf import ThirteenFCollector
from investor_intel.config.settings import AppSettings
from investor_intel.models.common import SourceType
from investor_intel.pipeline.collect import build_collect_entries
from investor_intel.storage.sqlite_index import connect, init_db


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

    entries, setup_errors = build_collect_entries(tmp_path, settings, checkpoint_store)

    assert setup_errors == []

    essay_entries = [e for e in entries if isinstance(e[0], EssayCollector)]
    assert len(essay_entries) == 1
    essay_collector, source_type, source_name = essay_entries[0]
    assert source_type == SourceType.ESSAY
    assert source_name == "situational_awareness"
    assert essay_collector.source_id == "essay_situational_awareness"

    thirteenf_entries = [e for e in entries if isinstance(e[0], ThirteenFCollector)]
    assert len(thirteenf_entries) == 2
