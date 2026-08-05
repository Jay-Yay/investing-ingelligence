from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from investor_intel.llm.client import AnthropicClient
from investor_intel.models.analysis import BearCaseCritique
from investor_intel.security.untrusted_content import PROMPT_INJECTION_GUARD, wrap_untrusted

_TOOL_SCHEMA: dict[str, Any] = {
    "name": "record_bear_case_critique",
    "description": (
        "Critique the Fundamental Analyst's assessment from the opposite side. Find missing "
        "risks, optimism bias, and whether the current price already reflects the good news."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "counter_arguments": {"type": "array", "items": {"type": "string"}},
            "missing_risks": {"type": "array", "items": {"type": "string"}},
            "optimism_bias_detected": {"type": "boolean"},
            "conflated_growth_with_price": {
                "type": "boolean",
                "description": "산업 성장과 주가 상승을 동일시했는지",
            },
            "conflated_correlation_with_causation": {"type": "boolean"},
            "priced_in_assessment": {
                "type": "string",
                "description": "이미 반영됨 / 부분 반영 / 미반영 중 하나와 그 근거",
            },
            "revised_invalidation_conditions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["priced_in_assessment"],
    },
}


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class BearCaseCriticOutcome:
    result: BearCaseCritique
    usage: TokenUsage


class BearCaseCriticError(Exception):
    pass


def critique(
    client: AnthropicClient,
    ticker: str,
    fundamental_assessment_context: str,
    evidence_context: str,
    system_prompt: str,
    max_retries: int = 2,
) -> BearCaseCriticOutcome:
    content = (
        f"## 종목: {ticker}\n\n"
        f"## Fundamental Analyst의 판단 (반론 대상)\n\n{fundamental_assessment_context}\n\n"
        f"{PROMPT_INJECTION_GUARD}\n\n"
        f"## 근거 자료\n\n{wrap_untrusted(evidence_context)}"
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
            tool_choice={"type": "tool", "name": "record_bear_case_critique"},
            max_tokens=4096,
        )
        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens
        tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use_block is None:
            last_error = "no tool_use block in response"
            continue
        try:
            result = BearCaseCritique.model_validate({"ticker": ticker, **tool_use_block.input})
        except ValidationError as exc:
            last_error = str(exc)
            continue
        usage = TokenUsage(input_tokens=total_input, output_tokens=total_output)
        return BearCaseCriticOutcome(result=result, usage=usage)

    raise BearCaseCriticError(
        f"failed to produce a valid critique after {max_retries + 1} attempts: {last_error}"
    )
