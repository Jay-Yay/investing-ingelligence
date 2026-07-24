from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from investor_intel.llm.client import AnthropicClient
from investor_intel.models.analysis import ExtractionResult
from investor_intel.security.untrusted_content import PROMPT_INJECTION_GUARD, wrap_untrusted

EXTRACTION_TOOL_SCHEMA: dict[str, Any] = {
    "name": "record_claims",
    "description": (
        "Record extracted claims with their evidence, counter-evidence, mentioned assets, "
        "fact/opinion/forecast classification, direction, and confidence."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "evidence": {"type": "array", "items": {"type": "string"}},
                        "counter_evidence": {"type": "array", "items": {"type": "string"}},
                        "assets": {"type": "array", "items": {"type": "string"}},
                        "fact_or_opinion": {
                            "type": "string",
                            "enum": ["fact", "opinion", "forecast"],
                        },
                        "direction": {
                            "type": "string",
                            "enum": ["bullish", "bearish", "neutral"],
                        },
                        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    },
                    "required": ["claim", "evidence", "fact_or_opinion", "direction", "confidence"],
                },
            }
        },
        "required": ["claims"],
    },
}


class ExtractionError(Exception):
    pass


def extract_claims(
    client: AnthropicClient,
    document_body: str,
    system_prompt: str,
    max_retries: int = 2,
) -> ExtractionResult:
    wrapped_content = f"{PROMPT_INJECTION_GUARD}\n\n{wrap_untrusted(document_body)}"
    messages = [{"role": "user", "content": wrapped_content}]

    last_error: str | None = None
    for _ in range(max_retries + 1):
        response = client.create_message(
            system=system_prompt,
            messages=messages,
            tools=[EXTRACTION_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "record_claims"},
        )
        tool_use_block = next(
            (block for block in response.content if block.type == "tool_use"), None
        )
        if tool_use_block is None:
            last_error = "no tool_use block in response"
            continue
        try:
            return ExtractionResult.model_validate(tool_use_block.input)
        except ValidationError as exc:
            last_error = str(exc)
            continue

    raise ExtractionError(
        f"failed to extract valid claims after {max_retries + 1} attempts: {last_error}"
    )
