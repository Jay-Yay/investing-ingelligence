from __future__ import annotations

from pydantic import BaseModel

from investor_intel.models.common import ConfidenceLevel, Direction, FactOrOpinion


class Claim(BaseModel):
    claim: str
    evidence: list[str]
    counter_evidence: list[str] = []
    assets: list[str] = []
    fact_or_opinion: FactOrOpinion
    direction: Direction
    confidence: ConfidenceLevel


class ExtractionResult(BaseModel):
    claims: list[Claim]
