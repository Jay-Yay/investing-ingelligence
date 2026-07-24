import json
from pathlib import Path

import pytest

from investor_intel.collectors.dart_filings_parser import (
    DartAPIError,
    parse_dart_list_response,
)

FIXTURES = Path(__file__).parent / "fixtures" / "dart"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parses_success_response() -> None:
    refs = parse_dart_list_response(_load("list_success.json"))
    assert len(refs) == 2

    first = refs[0]
    assert first.rcept_no == "20240315000001"
    assert first.rcept_dt.isoformat() == "2024-03-15"
    assert first.report_nm == "사업보고서 (2023.12)"
    assert first.corp_name == "삼성전자"
    assert first.corp_code == "00126380"
    assert first.flr_nm == "삼성전자"
    assert first.corp_cls == "Y"


def test_no_data_status_returns_empty_list() -> None:
    refs = parse_dart_list_response(_load("list_no_data.json"))
    assert refs == []


def test_error_status_raises() -> None:
    with pytest.raises(DartAPIError, match="사용한도"):
        parse_dart_list_response(_load("list_error.json"))
