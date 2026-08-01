from __future__ import annotations

from datetime import UTC, date, datetime

from investor_intel.collectors.base import CollectItem, CollectResult
from investor_intel.llm.client import AnthropicClient

WEB_SEARCH_TOOL: dict = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}

_NOT_FOUND_MARKER = "전문 찾지 못함"

DEFAULT_EARNINGS_TRANSCRIPT_SYSTEM_PROMPT = (
    "역할: 리서치 스크래퍼. web_search 도구로 아래 종목의 지정된 분기 실적발표 컨퍼런스콜"
    "(어닝콜) 녹취록을 찾아라.\n\n"
    "저작권 주의: 찾은 원문을 통째로 옮겨 적지 마라. 문단 단위로 길게 인용하지 말고, 인용은 "
    "문장 1~2개로 제한한다. 대신 아래 형식으로 핵심 요지를 구조적으로 요약하라:\n\n"
    "## 경영진 발언 핵심 요지\n"
    "- (요지 불릿, 필요시 1~2문장 짧은 인용 포함)\n\n"
    "## Q&A 핵심 문답\n"
    "- Q: (질문 요지) / A: (답변 요지, 필요시 1~2문장 짧은 인용 포함)\n\n"
    "맨 끝에 반드시 `출처: [매체명](URL)` 형식으로 원문 링크를 밝혀라 - 전문이 필요하면 "
    "독자가 원문 링크에서 직접 확인하게 한다.\n\n"
    f'실제로 그 분기의 녹취록(경영진 발언+Q&A)을 찾지 못했으면, 다른 말 없이 정확히 '
    f'"{_NOT_FOUND_MARKER}"라고만 답하라. 실적 관련 뉴스 기사만 있고 컨퍼런스콜 녹취록/'
    "스크립트 자체가 없으면 이것도 못 찾은 것으로 간주한다."
)


class EarningsTranscriptError(Exception):
    pass


def collect_earnings_transcript_web(
    client: AnthropicClient,
    ticker: str,
    name: str,
    reporting_period: date,
    system_prompt: str = DEFAULT_EARNINGS_TRANSCRIPT_SYSTEM_PROMPT,
) -> tuple[CollectResult | None, int, int]:
    """지정 종목의 지정 분기 실적발표 컨퍼런스콜을 웹서치로 찾아 구조적 요약 1건을 CollectItem으로
    담아 반환한다. 못 찾으면 (None, 입력토큰, 출력토큰)을 반환한다 - 호출부(pipeline/
    earnings_transcript.py)는 이걸 "이 분기는 처리 완료(못 찾음)"로 체크포인트에 기록하고,
    문서는 만들지 않는다.

    SEC 8-K exhibit 스캔(sec_document_fetch.find_transcript_exhibit)이 못 잡는 나머지 갭
    (약 70~80%, 8-K 자체가 없는 20-F/6-K 외국민간발행인은 100%)을 채우는 보완 경로다.
    Claude API의 web_search 도구를 쓰므로 토큰 비용이 든다 - collectors/web_research.py와
    동일한 이유로 무인 collect 크론(.github/workflows/daily-collect.yml)에는 포함하지 않는다.

    전문(verbatim) 대신 구조적 요약만 캡처한다: (1) 무료로 진짜 전문을 공개하는 사이트는
    ToS상 대량 스크래핑 대상이 아니고(Motley Fool 등 - vault/00_System/Runbook.md가 한국
    매체 스크립트에 대해 이미 그은 선과 동일), (2) 전문 verbatim을 매번 릴레이하면 출력 토큰이
    커져 실적 시즌 하루치 LLM 예산을 이 단계 하나로 다 태울 수 있다.
    """
    period_label = reporting_period.isoformat()
    query = (
        f"{ticker} {name} {period_label} 분기 실적발표 컨퍼런스콜 (Q&A) earnings call transcript"
    )
    response = client.create_message(
        system=system_prompt,
        messages=[{"role": "user", "content": query}],
        tools=[WEB_SEARCH_TOOL],
        max_tokens=3072,
    )
    text_blocks = [block.text for block in response.content if block.type == "text"]
    body_text = "\n".join(text_blocks).strip()
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens

    if not body_text:
        raise EarningsTranscriptError(f"{ticker}: web_search 응답에 텍스트 블록이 없음")

    if _NOT_FOUND_MARKER in body_text:
        return None, input_tokens, output_tokens

    now = datetime.now(UTC)
    item = CollectItem(
        source_specific_id=f"{ticker}-{period_label}",
        canonical_url=f"earnings-transcript-search://{ticker}/{period_label}",
        title=f"[컨퍼런스콜-웹서치] {name} {period_label} 실적발표 컨퍼런스콜",
        author=None,
        published_at=now,
        updated_at=None,
        language="en",
        body_text=body_text,
        content_capture_mode="excerpt",
        content_capture_reason=(
            "저작권 보호로 전문 대신 구조적 요약(경영진 발언 핵심 요지 + Q&A 핵심 문답)만 "
            "캡처 - 전문은 본문 하단 출처 링크 참고"
        ),
        companies=[ticker],
        document_type="earnings_call_transcript",
        reporting_period=period_label,
    )
    result = CollectResult(
        source_id=f"earnings_transcript_web_{ticker.lower()}",
        success=True,
        items=[item],
        errors=[],
        new_count=1,
    )
    return result, input_tokens, output_tokens
