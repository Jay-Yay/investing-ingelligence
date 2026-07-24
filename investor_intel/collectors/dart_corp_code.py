from __future__ import annotations

import io
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

from investor_intel.collectors.dart_client import DartClient
from investor_intel.storage.sqlite_index import (
    find_dart_corp_code,
    is_dart_corp_code_cache_populated,
    replace_dart_corp_codes,
)

_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={api_key}"


@dataclass
class CorpCodeEntry:
    corp_code: str
    corp_name: str
    stock_code: str | None
    modify_date: str


def parse_corp_code_xml(xml_text: str) -> list[CorpCodeEntry]:
    root = ET.fromstring(xml_text)
    entries: list[CorpCodeEntry] = []
    for item in root.findall("./list"):
        stock_code = item.findtext("stock_code") or ""
        entries.append(
            CorpCodeEntry(
                corp_code=item.findtext("corp_code") or "",
                corp_name=item.findtext("corp_name") or "",
                stock_code=stock_code or None,
                modify_date=item.findtext("modify_date") or "",
            )
        )
    return entries


def unzip_corp_code_xml(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        member = zf.namelist()[0]
        return zf.read(member).decode("utf-8")


def _refresh_cache(conn: sqlite3.Connection, client: DartClient, api_key: str) -> None:
    zip_bytes = client.get_bytes(_CORP_CODE_URL.format(api_key=api_key))
    entries = parse_corp_code_xml(unzip_corp_code_xml(zip_bytes))
    replace_dart_corp_codes(
        conn, [(e.corp_code, e.corp_name, e.stock_code, e.modify_date) for e in entries]
    )


def resolve_corp_code(
    conn: sqlite3.Connection, client: DartClient, api_key: str, *, ticker: str, name: str
) -> str | None:
    if not is_dart_corp_code_cache_populated(conn):
        _refresh_cache(conn, client, api_key)

    corp_code = find_dart_corp_code(conn, stock_code=ticker, name=name)
    if corp_code is not None:
        return corp_code

    _refresh_cache(conn, client, api_key)
    return find_dart_corp_code(conn, stock_code=ticker, name=name)
