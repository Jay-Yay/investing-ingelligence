from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from investor_intel.llm.client import AnthropicClient
from investor_intel.models.analysis import ExtractionResult
from investor_intel.security.untrusted_content import PROMPT_INJECTION_GUARD, wrap_untrusted


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class ExtractionOutcome:
    result: ExtractionResult
    usage: TokenUsage


@dataclass
class BatchExtractionOutcome:
    results: dict[str, ExtractionResult]
    usage: TokenUsage

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


BATCH_EXTRACTION_TOOL_SCHEMA: dict[str, Any] = {
    "name": "record_claims_batch",
    "description": (
        "Record extracted claims for each document in the batch, keyed by its document_id. "
        "Return exactly one entry per document_id given in the input, using an empty claims "
        "array for documents with no substantive claims."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "documents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string"},
                        "claims": EXTRACTION_TOOL_SCHEMA["input_schema"]["properties"]["claims"],
                    },
                    "required": ["document_id", "claims"],
                },
            }
        },
        "required": ["documents"],
    },
}


class ExtractionError(Exception):
    pass


def extract_claims(
    client: AnthropicClient,
    document_body: str,
    system_prompt: str,
    max_retries: int = 2,
) -> ExtractionOutcome:
    wrapped_content = f"{PROMPT_INJECTION_GUARD}\n\n{wrap_untrusted(document_body)}"
    messages = [{"role": "user", "content": wrapped_content}]

    last_error: str | None = None
    total_input_tokens = 0
    total_output_tokens = 0
    for _ in range(max_retries + 1):
        response = client.create_message(
            system=system_prompt,
            messages=messages,
            tools=[EXTRACTION_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "record_claims"},
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
            result = ExtractionResult.model_validate(tool_use_block.input)
        except ValidationError as exc:
            last_error = str(exc)
            continue
        usage = TokenUsage(input_tokens=total_input_tokens, output_tokens=total_output_tokens)
        return ExtractionOutcome(result=result, usage=usage)

    raise ExtractionError(
        f"failed to extract valid claims after {max_retries + 1} attempts: {last_error}"
    )


def _wrap_batch_documents(documents: list[tuple[str, str]]) -> str:
    parts = [
        f'--- 문서 시작 (document_id="{doc_id}") ---\n'
        f"{wrap_untrusted(body)}\n"
        f'--- 문서 끝 (document_id="{doc_id}") ---'
        for doc_id, body in documents
    ]
    return "\n\n".join(parts)


def extract_claims_batch(
    client: AnthropicClient,
    documents: list[tuple[str, str]],
    system_prompt: str,
    max_retries: int = 2,
) -> BatchExtractionOutcome:
    """여러 개의 (주로 짧은) 문서를 한 번의 LLM 호출로 묶어서 처리한다.

    문서별로 개별 호출하면 스키마/지시문 오버헤드를 문서 수만큼 반복해서 지불하게 된다 -
    텔레그램/네이버처럼 본문이 짧은 문서가 다수일 때 이 오버헤드가 실제 콘텐츠 분석 비용을
    압도할 수 있다(2026-08 수동 backlog 분석 실측 참고). documents는 (document_id, body)
    튜플 리스트이고, 응답의 document_id 집합이 입력과 정확히 일치하지 않으면 ExtractionError를
    던진다 - 호출부가 개별 처리로 폴백할 수 있게 하기 위함이다.
    """
    if not documents:
        raise ValueError("documents must not be empty")

    batch_system_prompt = (
        f"{system_prompt}\n\n"
        "이번 호출에는 서로 무관한 여러 개의 원문 문서가 함께 주어진다. 각 문서를 독립적으로 "
        "분석하고, 입력에 주어진 document_id 각각에 대해 정확히 하나의 결과 항목을 반환하라 "
        "(핵심 주장이 없으면 claims를 빈 배열로 반환하고, 문서 간 내용을 섞지 마라)."
    )
    wrapped_content = f"{PROMPT_INJECTION_GUARD}\n\n{_wrap_batch_documents(documents)}"
    messages = [{"role": "user", "content": wrapped_content}]

    expected_ids = {doc_id for doc_id, _ in documents}
    last_error: str | None = None
    total_input_tokens = 0
    total_output_tokens = 0
    for _ in range(max_retries + 1):
        response = client.create_message(
            system=batch_system_prompt,
            messages=messages,
            tools=[BATCH_EXTRACTION_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "record_claims_batch"},
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
            raw_documents = tool_use_block.input["documents"]
            results = {
                item["document_id"]: ExtractionResult.model_validate(
                    {"claims": item["claims"]}
                )
                for item in raw_documents
            }
        except (KeyError, TypeError, ValidationError) as exc:
            last_error = str(exc)
            continue
        if set(results.keys()) != expected_ids:
            last_error = (
                f"document_id mismatch: expected {sorted(expected_ids)}, "
                f"got {sorted(results.keys())}"
            )
            continue
        usage = TokenUsage(input_tokens=total_input_tokens, output_tokens=total_output_tokens)
        return BatchExtractionOutcome(results=results, usage=usage)

    raise ExtractionError(
        f"failed to extract valid batch claims after {max_retries + 1} attempts: {last_error}"
    )
