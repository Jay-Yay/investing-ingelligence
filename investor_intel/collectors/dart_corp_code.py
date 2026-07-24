from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass


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
