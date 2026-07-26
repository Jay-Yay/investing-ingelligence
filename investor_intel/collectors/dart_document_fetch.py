from __future__ import annotations

import zipfile
from io import BytesIO

from investor_intel.collectors.dart_client import DartClient
from investor_intel.collectors.text_extract import strip_markup, truncate

_DOCUMENT_URL = (
    "https://opendart.fss.or.kr/api/document.xml?crtfc_key={api_key}&rcept_no={rcept_no}"
)


def fetch_full_text(client: DartClient, api_key: str, rcept_no: str) -> str | None:
    """OpenDART document.xml에서 공시 원문 전체 텍스트를 가져온다.

    document.xml은 원문 XML을 담은 ZIP을 반환한다. 실패(네트워크 오류, 잘못된 ZIP, 빈 본문 등)
    시 예외를 던지지 않고 None을 반환한다 - 호출부가 metadata_only로 폴백할 수 있도록.
    """
    try:
        zip_bytes = client.get_bytes(_DOCUMENT_URL.format(api_key=api_key, rcept_no=rcept_no))
        with zipfile.ZipFile(BytesIO(zip_bytes)) as archive:
            xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
            if not xml_names:
                return None
            raw_xml = archive.read(xml_names[0]).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None

    text = strip_markup(raw_xml)
    if not text:
        return None
    return truncate(text)
