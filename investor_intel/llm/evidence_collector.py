from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from investor_intel.llm.client import AnthropicClient
from investor_intel.scoring.models import FactType, Feature, SourceTier
from investor_intel.security.untrusted_content import PROMPT_INJECTION_GUARD, wrap_untrusted

# 주간+이벤트 전용 - 일간 실행에는 배선하지 않는다(README/CLAUDE.md 답변: 기존 하루 $1.5 LLM
# 예산과 충돌하지 않도록, 새 LLM 4역할은 daily가 아니라 score run-weekly / event 재평가에서만
# 호출된다).


class _ExtractedItem(BaseModel):
    metric: str
    value: float | None = None
    trend: str | None = None  # qualitative_trend류 metric_spec에서만 사용 ("개선"/"악화"/"횡보")
    unit: str
    period: str
    fact_type: str
    source_tier: str
    confidence: float


class EvidenceCollectorResult(BaseModel):
    items: list[_ExtractedItem]


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class EvidenceCollectorOutcome:
    features: list[Feature]
    usage: TokenUsage


class EvidenceCollectorError(Exception):
    pass


def _tool_schema(allowed_metrics: list[str]) -> dict[str, Any]:
    return {
        "name": "record_evidence",
        "description": (
            "Extract only numbers and key stated facts from the source text. Do not estimate, "
            "infer, or make investment judgments - if a metric isn't explicitly stated, omit it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "metric": {"type": "string", "enum": allowed_metrics},
                            "value": {
                                "type": "number",
                                "description": "정량 수치(질적 trend류는 생략, trend만 채움)",
                            },
                            "trend": {
                                "type": "string",
                                "enum": ["개선", "악화", "횡보"],
                                "description": "정성적 판단만 가능한 metric에 한해 사용",
                            },
                            "unit": {"type": "string"},
                            "period": {
                                "type": "string",
                                "description": "예: 2026Q2, FY2026, 2026-07-28",
                            },
                            "fact_type": {
                                "type": "string",
                                "enum": [
                                    "reported_fact",
                                    "company_guidance",
                                    "consensus",
                                    "estimate",
                                    "opinion",
                                    "rumor",
                                ],
                            },
                            "source_tier": {
                                "type": "string",
                                "enum": ["official", "industry", "news", "broker", "social"],
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                                "description": "근거의 직접성/출처 명확성 (사실일 확률이 아니다)",
                            },
                        },
                        "required": [
                            "metric", "unit", "period", "fact_type", "source_tier", "confidence",
                        ],
                    },
                }
            },
            "required": ["items"],
        },
    }


def extract_evidence(
    client: AnthropicClient,
    ticker: str,
    source_name: str,
    source_url: str,
    published_at: datetime,
    document_text: str,
    system_prompt: str,
    allowed_metrics: list[str],
    max_retries: int = 2,
) -> EvidenceCollectorOutcome:
    """섹션 16 Evidence Collector. 원문 하나에서 허용된 metric 어휘(allowed_metrics - 보통
    섹터 설정의 metric_specs 키 목록)로만 숫자/정성판단을 추출한다. ticker/source/발행일은
    LLM이 지어내지 않고 호출부가 실제 문서 메타데이터로 스탬프한다."""
    content = (
        f"## 종목: {ticker}\n허용된 metric 목록: {', '.join(allowed_metrics)}\n\n"
        f"{PROMPT_INJECTION_GUARD}\n\n"
        f"## 원문\n\n{wrap_untrusted(document_text)}"
    )
    messages = [{"role": "user", "content": content}]
    tool = _tool_schema(allowed_metrics)

    last_error: str | None = None
    total_input = 0
    total_output = 0
    for _ in range(max_retries + 1):
        response = client.create_message(
            system=system_prompt,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "tool", "name": "record_evidence"},
            max_tokens=4096,
        )
        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens
        tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_use_block is None:
            last_error = "no tool_use block in response"
            continue
        try:
            result = EvidenceCollectorResult.model_validate(tool_use_block.input)
        except ValidationError as exc:
            last_error = str(exc)
            continue

        retrieved_at = datetime.now(UTC)
        features = [
            Feature(
                ticker=ticker,
                metric=item.metric,
                value=item.value,
                unit=item.unit,
                period=item.period,
                published_at=published_at,
                retrieved_at=retrieved_at,
                source_name=source_name,
                source_url=source_url,
                source_tier=SourceTier(item.source_tier),
                fact_type=FactType(item.fact_type),
                confidence=item.confidence,
                details={"trend": item.trend} if item.trend else {},
            )
            for item in result.items
            if item.value is not None or item.trend is not None
        ]
        usage = TokenUsage(input_tokens=total_input, output_tokens=total_output)
        return EvidenceCollectorOutcome(features=features, usage=usage)

    raise EvidenceCollectorError(
        f"failed to extract valid evidence after {max_retries + 1} attempts: {last_error}"
    )
