from __future__ import annotations

from pydantic import BaseModel


class MacroIndicatorDef(BaseModel):
    """config/macro_theses.yaml에 정의되는 지표 하나의 스펙 - 무엇을, 왜 보는지."""

    id: str
    label: str
    unit: str = ""
    baseline: str = ""
    bullish_threshold: str = ""
    bearish_threshold: str = ""
    source_hint: str = ""


class MacroThesisDef(BaseModel):
    id: str
    title: str
    summary: str = ""
    created: str = ""
    indicators: list[MacroIndicatorDef] = []


class MacroThesesConfig(BaseModel):
    theses: list[MacroThesisDef] = []


class IndicatorSnapshot(BaseModel):
    """지표 하나에 대한 한 시점 관측값. record-indicators가 넘겨받는 JSON의 값 형태."""

    value: str
    note: str = ""
    source_url: str = ""
