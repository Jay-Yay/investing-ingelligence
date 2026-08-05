from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from investor_intel.llm.client import AnthropicClient
from investor_intel.models.analysis import ModelChangeProposal
from investor_intel.security.untrusted_content import PROMPT_INJECTION_GUARD, wrap_untrusted

_TOOL_SCHEMA: dict[str, Any] = {
    "name": "record_model_change_proposal",
    "description": (
        "Propose ONE concrete change to scoring rules/weights/thresholds based on historical "
        "evaluation results. Never apply the change yourself - status is always "
        "pending_human_approval."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "proposal": {"type": "string"},
            "current_rule": {"type": "string"},
            "proposed_rule": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "backtest_plan": {"type": "string"},
            "expected_benefit": {"type": "string"},
            "possible_side_effect": {"type": "string"},
        },
        "required": [
            "proposal",
            "current_rule",
            "proposed_rule",
            "backtest_plan",
            "expected_benefit",
            "possible_side_effect",
        ],
    },
}


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class ModelReviewerOutcome:
    result: ModelChangeProposal
    usage: TokenUsage


class ModelReviewerError(Exception):
    pass


def review_model_performance(
    client: AnthropicClient,
    evaluation_summary_context: str,
    system_prompt: str,
    max_retries: int = 2,
) -> ModelReviewerOutcome:
    """섹션 16 Model Reviewer + 섹션 19 제안 형식. evaluation_summary_context는
    scoring/evaluation.py가 계산한 점수구간별 실적/오탐 사례 요약이다 - 이 함수는 그 요약을
    읽고 규칙 변경 "제안"만 만든다. 제안을 champion.yaml에 반영하는 것은 사람의 몫이다."""
    content = (
        f"{PROMPT_INJECTION_GUARD}\n\n"
        f"## 과거 평가 성과 요약\n\n{wrap_untrusted(evaluation_summary_context)}"
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
            tool_choice={"type": "tool", "name": "record_model_change_proposal"},
            max_tokens=4096,
        )
        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens
        tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use_block is None:
            last_error = "no tool_use block in response"
            continue
        try:
            result = ModelChangeProposal.model_validate(tool_use_block.input)
        except ValidationError as exc:
            last_error = str(exc)
            continue
        # LLM이 status를 다르게 채워도 항상 pending_human_approval로 강제한다 - 자동 승격 방지.
        result = result.model_copy(update={"status": "pending_human_approval"})
        usage = TokenUsage(input_tokens=total_input, output_tokens=total_output)
        return ModelReviewerOutcome(result=result, usage=usage)

    raise ModelReviewerError(
        f"failed to produce a valid proposal after {max_retries + 1} attempts: {last_error}"
    )
