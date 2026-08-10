from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from investor_intel.storage.sqlite_index import export_collector_state, import_collector_state


def load_checkpoints(conn: sqlite3.Connection, path: Path) -> None:
    if not path.exists():
        return
    states = json.loads(path.read_text(encoding="utf-8"))
    import_collector_state(conn, states)


def save_checkpoints(conn: sqlite3.Connection, path: Path) -> None:
    states = export_collector_state(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(states, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
