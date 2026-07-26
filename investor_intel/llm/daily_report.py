from __future__ import annotations

from dataclasses import dataclass

from investor_intel.llm.client import AnthropicClient


class DailyReportError(Exception):
    pass


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class DailyNarrativeOutcome:
    text: str
    usage: TokenUsage


def synthesize_daily_narrative(
    client: AnthropicClient, summary: str, system_prompt: str
) -> DailyNarrativeOutcome:
    response = client.create_message(
        system=system_prompt,
        messages=[{"role": "user", "content": summary}],
    )
    text_block = next((block for block in response.content if block.type == "text"), None)
    if text_block is None:
        raise DailyReportError("no text block in daily report synthesis response")
    usage = TokenUsage(
        input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens
    )
    return DailyNarrativeOutcome(text=text_block.text, usage=usage)
