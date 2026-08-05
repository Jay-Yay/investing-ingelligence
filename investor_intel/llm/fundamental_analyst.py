from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from investor_intel.llm.client import AnthropicClient
from investor_intel.models.analysis import FundamentalAnalystAssessment
from investor_intel.security.untrusted_content import PROMPT_INJECTION_GUARD, wrap_untrusted

_DRIVER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claim": {"type": "string", "description": "한 줄 요약"},
        "rationale": {
            "type": "string",
            "description": "이 근거가 투자 판단에 왜/어떻게 영향을 주는지 3-5줄 배경 설명",
        },
        "source_url": {
            "type": "string",
            "description": (
                "이 주장의 근거가 된 evidence_context 항목의 URL을 그대로 사용한다 - "
                "URL을 새로 만들거나 추측하지 않는다"
            ),
        },
    },
    "required": ["claim", "rationale", "source_url"],
}

_TOOL_SCHEMA: dict[str, Any] = {
    "name": "record_fundamental_assessment",
    "description": (
        "Judge how new evidence changes the 12-month earnings outlook and investment thesis. "
        "Do not assign a numeric score - scoring/pipeline.py computes the total score from "
        "structured features separately."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "thesis_shift": {"type": "string", "enum": ["strengthened", "neutral", "weakened"]},
            "impacted_categories": {"type": "array", "items": {"type": "string"}},
            "causal_chain": {"type": "string"},
            "consensus_comparison": {
                "type": "string",
                "description": "예상보다 긍정적/예상 수준/예상보다 부정적, 그 이유",
            },
            "new_positive_drivers": {"type": "array", "items": _DRIVER_SCHEMA},
            "new_negative_drivers": {"type": "array", "items": _DRIVER_SCHEMA},
            "next_catalysts": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["thesis_shift", "causal_chain", "consensus_comparison"],
    },
}


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class FundamentalAnalystOutcome:
    result: FundamentalAnalystAssessment
    usage: TokenUsage


class FundamentalAnalystError(Exception):
    pass


def assess_fundamentals(
    client: AnthropicClient,
    ticker: str,
    evidence_context: str,
    prior_assessment_context: str,
    system_prompt: str,
    max_retries: int = 2,
) -> FundamentalAnalystOutcome:
    content = (
        f"## 종목: {ticker}\n\n"
        f"## 직전 판단 (있으면)\n\n{prior_assessment_context}\n\n"
        f"{PROMPT_INJECTION_GUARD}\n\n"
        f"## 이번에 수집된 근거 (Evidence Collector 출력 - 외부 원문 아님, 이미 구조화됨)\n\n"
        f"{wrap_untrusted(evidence_context)}"
    )
    messages = [{"role": "user", "content": content}]

    last_error: str | None = None
    total_input = 0
    total_output = 0
    for _ in range(max_retries + 1):
        response = client.create_message(
            system=system_prompt,
            messages=messages,
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "record_fundamental_assessment"},
            max_tokens=4096,
        )
        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens
        tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use_block is None:
            last_error = "no tool_use block in response"
            continue
        try:
            result = FundamentalAnalystAssessment.model_validate(
                {"ticker": ticker, **tool_use_block.input}
            )
        except ValidationError as exc:
            last_error = str(exc)
            continue
        usage = TokenUsage(input_tokens=total_input, output_tokens=total_output)
        return FundamentalAnalystOutcome(result=result, usage=usage)

    raise FundamentalAnalystError(
        f"failed to produce a valid assessment after {max_retries + 1} attempts: {last_error}"
    )
