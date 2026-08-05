from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from investor_intel.llm.client import AnthropicClient
from investor_intel.security.untrusted_content import PROMPT_INJECTION_GUARD, wrap_untrusted


class GuidanceDirection(StrEnum):
    UP = "up"
    DOWN = "down"
    MAINTAINED = "maintained"
    UNCLEAR = "unclear"


class HyperscalerAiRevenueExtraction(BaseModel):
    """SEC 10-Q/10-K 원문에서 뽑아낸 클라우드/AI 세그먼트 매출 + CapEx 가이던스 방향.

    원문에 명시적으로 없는 숫자 필드는 None으로 남긴다(추정하지 않는다) - guidance_quote/
    source_quote는 근거 없는 숫자를 방지하기 위해 항상 원문 그대로의 인용을 요구한다.
    """

    cloud_or_ai_revenue: float | None = None
    cloud_or_ai_revenue_unit: str | None = None
    reporting_period: str | None = None
    yoy_growth_pct: float | None = None
    guidance_direction: GuidanceDirection
    guidance_quote: str
    source_quote: str


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class AiRevenueExtractionOutcome:
    result: HyperscalerAiRevenueExtraction
    usage: TokenUsage


class AiRevenueExtractionError(Exception):
    pass


AI_METRICS_TOOL_SCHEMA: dict[str, Any] = {
    "name": "record_ai_revenue_metrics",
    "description": (
        "Record the company's cloud/AI-related segment revenue and forward capex/AI "
        "investment guidance direction found in the filing text, only if explicitly stated."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "cloud_or_ai_revenue": {
                "type": "number",
                "description": "Cloud or AI-related segment revenue figure, if disclosed.",
            },
            "cloud_or_ai_revenue_unit": {
                "type": "string",
                "description": "Unit/currency of cloud_or_ai_revenue, e.g. 'USD millions'.",
            },
            "reporting_period": {
                "type": "string",
                "description": "Fiscal period the figure covers, e.g. 'Q2 FY2026'.",
            },
            "yoy_growth_pct": {
                "type": "number",
                "description": (
                    "Year-over-year growth rate of the cloud/AI revenue, in percent, if stated."
                ),
            },
            "guidance_direction": {
                "type": "string",
                "enum": ["up", "down", "maintained", "unclear"],
                "description": "Direction of forward capex/AI-investment guidance in this filing.",
            },
            "guidance_quote": {
                "type": "string",
                "description": (
                    "Verbatim quote from the filing supporting guidance_direction. "
                    "Empty string if none found."
                ),
            },
            "source_quote": {
                "type": "string",
                "description": (
                    "Verbatim quote from the filing supporting cloud_or_ai_revenue. "
                    "Empty string if none found."
                ),
            },
        },
        "required": ["guidance_direction", "guidance_quote", "source_quote"],
    },
}


def extract_ai_revenue_metrics(
    client: AnthropicClient,
    document_body: str,
    system_prompt: str,
    max_retries: int = 2,
) -> AiRevenueExtractionOutcome:
    """llm.extraction.extract_claims과 동일한 tool-calling 패턴 - 다만 주장(claim) 목록이
    아니라 지표 하나(HyperscalerAiRevenueExtraction)를 뽑는다."""
    wrapped_content = f"{PROMPT_INJECTION_GUARD}\n\n{wrap_untrusted(document_body)}"
    messages = [{"role": "user", "content": wrapped_content}]

    last_error: str | None = None
    total_input_tokens = 0
    total_output_tokens = 0
    for _ in range(max_retries + 1):
        response = client.create_message(
            system=system_prompt,
            messages=messages,
            tools=[AI_METRICS_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "record_ai_revenue_metrics"},
        )
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        tool_use_block = next(
            (block for block in response.content if block.type == "tool_use"), None
        )
        if tool_use_block is None:
            last_error = "no tool_use block in response"
            continue
        try:
            result = HyperscalerAiRevenueExtraction.model_validate(tool_use_block.input)
        except ValidationError as exc:
            last_error = str(exc)
            continue
        usage = TokenUsage(input_tokens=total_input_tokens, output_tokens=total_output_tokens)
        return AiRevenueExtractionOutcome(result=result, usage=usage)

    raise AiRevenueExtractionError(
        f"failed to extract AI revenue metrics after {max_retries + 1} attempts: {last_error}"
    )
