from __future__ import annotations

from investor_intel.llm.client import AnthropicClient


class DailyReportError(Exception):
    pass


def synthesize_daily_narrative(
    client: AnthropicClient, summary: str, system_prompt: str
) -> str:
    response = client.create_message(
        system=system_prompt,
        messages=[{"role": "user", "content": summary}],
    )
    text_block = next((block for block in response.content if block.type == "text"), None)
    if text_block is None:
        raise DailyReportError("no text block in daily report synthesis response")
    return text_block.text
