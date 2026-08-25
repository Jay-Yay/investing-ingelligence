from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from investor_intel.indexing.okf_loader import load_bundle

# 4주차 자료의 "다양한 Index 유형" 중 두 번째 줄에 해당하는 인덱스다.
#   비정형 문서 내용        -> Vector Store, BM25, Hybrid Search
#   매출·건수·상태 등 표 데이터 -> SQL Database, Text-to-SQL     <- 여기
# 13F 보유 현황과 공시 카탈로그는 원래 표다. 표를 문서로 취급해 청킹하고 BM25로 훑으면
# "보유 종목이 몇 개냐" 같은 질문에 원리적으로 답할 수 없다. 세는 연산이 없기 때문이다.

_SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
    concept_id   TEXT NOT NULL,
    investor_key TEXT NOT NULL,
    investor     TEXT NOT NULL,
    as_of        TEXT,
    published    TEXT,
    security     TEXT NOT NULL,
    cusip        TEXT,
    shares       INTEGER,
    value_k      INTEGER,
    weight_pct   REAL,
    change       TEXT
);
CREATE INDEX IF NOT EXISTS idx_holdings_inv ON holdings(investor_key, as_of);
CREATE INDEX IF NOT EXISTS idx_holdings_sec ON holdings(security);

-- 13F 본문 머리글에 있는 "총 보고 가치 / 보유 종목 수 / 상위 5종목 집중도"는
-- 표와 별개로 보고서가 직접 밝힌 값이다. 수집기가 표를 잘라 저장하기 때문에
-- 표 행을 세면 실제 보유 종목 수와 다르다(실측: 198건 중 93건에서 잘림, 보고된
-- 48,065개 중 58.7%가 표에 없음). 둘을 다른 컬럼으로 두고 불일치를 표시한다.
CREATE TABLE IF NOT EXISTS snapshots (
    concept_id      TEXT PRIMARY KEY,
    investor_key    TEXT,
    investor        TEXT,
    as_of           TEXT,
    published       TEXT,
    total_value_k   INTEGER,
    reported_count  INTEGER,
    top5_pct        REAL,
    captured_rows   INTEGER,
    truncated       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_snap_inv ON snapshots(investor_key, published);

CREATE TABLE IF NOT EXISTS filings (
    concept_id   TEXT PRIMARY KEY,
    entity_key   TEXT,
    entity       TEXT,
    system       TEXT NOT NULL,
    filing_type  TEXT,
    as_of        TEXT,
    published    TEXT,
    fiscal_year  TEXT,
    pub_year     TEXT,
    native_id    TEXT,
    title        TEXT,
    resource     TEXT,
    status       TEXT
);
CREATE INDEX IF NOT EXISTS idx_filings_ent ON filings(entity_key, pub_year);
CREATE INDEX IF NOT EXISTS idx_filings_native ON filings(native_id);
"""

_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_HEADER_FACTS = re.compile(
    r"총 보고 가치:\s*([\d,]+)천 달러\s*/\s*보유 종목 수:\s*(\d+)"
    r"(?:\s*/\s*상위 5종목 집중도:\s*([\d.]+)%)?")
_NUM = re.compile(r"[^0-9.\-]")


def _num(s: str) -> float | None:
    s = _NUM.sub("", s or "")
    if not s or s in {".", "-"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_holdings_table(body: str) -> list[dict]:
    """13F 본문의 마크다운 표를 행 목록으로 되돌린다."""
    out: list[dict] = []
    header: list[str] | None = None
    for line in body.split("\n"):
        m = _ROW.match(line)
        if not m:
            if header and out:
                break          # 표가 끝나면 중단
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if header is None:
            if "종목" in cells[0]:
                header = cells
            continue
        if set("".join(cells)) <= set("-: "):
            continue           # 구분선
        if len(cells) < 5:
            continue
        out.append({
            "security": cells[0], "cusip": cells[1] or None,
            "shares": int(_num(cells[2]) or 0) or None,
            "value_k": int(_num(cells[3]) or 0) or None,
            "weight_pct": _num(cells[4]),
            "change": cells[5] if len(cells) > 5 else None,
        })
    return out


def build_structured_index(bundle: Path, db_path: Path) -> dict:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.execute("DELETE FROM holdings")
    conn.execute("DELETE FROM snapshots")
    conn.execute("DELETE FROM filings")

    n_hold = n_rows = n_filing = n_trunc = 0
    for c in load_bundle(bundle):
        if c.okf_type == "HoldingsSnapshot":
            rows = _parse_holdings_table(c.body)
            if not rows:
                continue
            n_hold += 1
            n_rows += len(rows)
            key = c.entity_keys[0] if c.entity_keys else ""
            hm = _HEADER_FACTS.search(c.body)
            reported = int(hm.group(2)) if hm else None
            truncated = bool(reported and len(rows) < reported)
            n_trunc += int(truncated)
            conn.execute(
                "INSERT OR REPLACE INTO snapshots (concept_id,investor_key,investor,as_of,"
                "published,total_value_k,reported_count,top5_pct,captured_rows,truncated)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (c.concept_id, key, c.subject_name, c.fiscal, c.published,
                 int((hm.group(1) or "0").replace(",", "")) if hm else None,
                 reported, float(hm.group(3)) if (hm and hm.group(3)) else None,
                 len(rows), int(truncated)))
            conn.executemany(
                "INSERT INTO holdings (concept_id,investor_key,investor,as_of,published,"
                "security,cusip,shares,value_k,weight_pct,change) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(c.concept_id, key, c.subject_name, c.period_year and c.fiscal or "",
                  c.published, r["security"], r["cusip"], r["shares"], r["value_k"],
                  r["weight_pct"], r["change"]) for r in rows])
        elif c.okf_type in ("DartFiling", "SecFiling"):
            n_filing += 1
            conn.execute(
                "INSERT OR REPLACE INTO filings (concept_id,entity_key,entity,system,"
                "filing_type,as_of,published,fiscal_year,pub_year,native_id,title,resource,status)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (c.concept_id, c.entity_keys[0] if c.entity_keys else "", c.subject_name,
                 c.source_system, (c.tags[1] if len(c.tags) > 1 else None), c.fiscal,
                 c.published, c.period_year, c.published[:4], c.native_id, c.title,
                 c.resource, c.status))
    conn.commit()
    size = db_path.stat().st_size
    conn.close()
    return {"holdings_snapshots": n_hold, "holding_rows": n_rows,
            "truncated_snapshots": n_trunc, "filings": n_filing, "db_bytes": size}
