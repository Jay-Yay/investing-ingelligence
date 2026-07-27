from __future__ import annotations

from datetime import UTC, datetime

from investor_intel.collectors.base import CollectItem, CollectResult
from investor_intel.llm.client import AnthropicClient

WEB_SEARCH_TOOL: dict = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}

DEFAULT_WEB_RESEARCH_SYSTEM_PROMPT = (
    "역할: 리서치 스크래퍼. web_search 도구로 아래 종목에 대한 최근 뉴스·기사·분석글을 찾아라.\n"
    "이 단계는 스크랩 전용이다 - 절대 투자 의견, 강세/약세 판단, 요약 해석을 달지 마라. "
    "분석은 별도 단계(analyze)에서 수행한다.\n\n"
    "찾은 자료를 아래 형식으로만 나열하라:\n"
    "- [기사 제목](URL) — 매체/출처, 날짜\n"
    "  원문 핵심 문장 1~2개 그대로 인용\n\n"
    "검색 결과가 없으면 '검색 결과 없음'이라고만 답하라."
)


class WebResearchError(Exception):
    pass


def collect_web_research(
    client: AnthropicClient,
    symbol: str,
    name: str,
    system_prompt: str = DEFAULT_WEB_RESEARCH_SYSTEM_PROMPT,
) -> tuple[CollectResult, int, int]:
    """지정 종목에 대해 실시간 웹 검색을 1회 실행하고, 원문 스크랩만 CollectItem 1건으로 담아
    반환한다.

    검색 자체가 Claude API의 web_search 도구를 통하므로 ANTHROPIC_API_KEY와 토큰 비용이 든다 -
    무인 collect 크론에는 포함하지 않고, run_daily의 analyze 이후 별도 단계로만 호출한다. 이 함수는
    LLM에 주장 추출/판단을 시키지 않으므로(scrape only), 저장된 문서는 llm_processed=false 상태로
    남아 다음 analyze 실행에서 다른 문서와 동일하게 처리된다.
    """
    query = f"{symbol} {name} 최근 뉴스"
    response = client.create_message(
        system=system_prompt,
        messages=[{"role": "user", "content": query}],
        tools=[WEB_SEARCH_TOOL],
        max_tokens=2048,
    )
    text_blocks = [block.text for block in response.content if block.type == "text"]
    body_text = "\n".join(text_blocks).strip()
    if not body_text:
        raise WebResearchError(f"{symbol}: web_search 응답에 텍스트 블록이 없음")

    now = datetime.now(UTC)
    today = now.date().isoformat()
    item = CollectItem(
        source_specific_id=f"{symbol}-{today}",
        canonical_url=f"web-search://{symbol}/{today}",
        title=f"{symbol} 웹 검색 스크랩 ({today})",
        author=None,
        published_at=now,
        updated_at=None,
        language="ko",
        body_text=body_text,
        content_capture_mode="full",
        document_type="web_search_digest",
    )
    result = CollectResult(source_id=f"web_search_{symbol}", success=True, items=[item], errors=[])
    return result, response.usage.input_tokens, response.usage.output_tokens
