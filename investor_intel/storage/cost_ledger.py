from __future__ import annotations

import sqlite3
from datetime import datetime


def init_cost_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost_usd REAL NOT NULL
        )
        """
    )
    conn.commit()


def record_usage(
    conn: sqlite3.Connection,
    timestamp: datetime,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
) -> None:
    conn.execute(
        "INSERT INTO llm_usage (timestamp, model, input_tokens, output_tokens, cost_usd) "
        "VALUES (?, ?, ?, ?, ?)",
        (timestamp.isoformat(), model, input_tokens, output_tokens, cost_usd),
    )
    conn.commit()


def sum_cost_between(conn: sqlite3.Connection, start: datetime, end: datetime) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0.0) FROM llm_usage WHERE timestamp >= ? AND timestamp < ?",
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    return float(row[0])
