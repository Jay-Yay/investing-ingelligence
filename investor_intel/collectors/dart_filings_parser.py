from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

_STATUS_SUCCESS = "000"
_STATUS_NO_DATA = "013"


class DartAPIError(Exception):
    pass


@dataclass
class DartFilingRef:
    rcept_no: str
    rcept_dt: date
    report_nm: str
    corp_name: str
    corp_code: str
    flr_nm: str
    corp_cls: str


def parse_dart_list_response(response: dict[str, Any]) -> list[DartFilingRef]:
    status = response.get("status")
    if status == _STATUS_NO_DATA:
        return []
    if status != _STATUS_SUCCESS:
        message = response.get("message", "unknown OpenDART error")
        raise DartAPIError(f"OpenDART list.json returned status {status}: {message}")

    return [
        DartFilingRef(
            rcept_no=item["rcept_no"],
            rcept_dt=date(
                int(item["rcept_dt"][0:4]),
                int(item["rcept_dt"][4:6]),
                int(item["rcept_dt"][6:8]),
            ),
            report_nm=item["report_nm"],
            corp_name=item["corp_name"],
            corp_code=item["corp_code"],
            flr_nm=item["flr_nm"],
            corp_cls=item["corp_cls"],
        )
        for item in response.get("list", [])
    ]
