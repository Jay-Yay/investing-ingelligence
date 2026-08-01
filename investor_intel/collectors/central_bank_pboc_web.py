from __future__ import annotations

from datetime import UTC, datetime

from investor_intel.collectors.base import CollectItem, CollectResult
from investor_intel.llm.client import AnthropicClient

WEB_SEARCH_TOOL: dict = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}

_NOT_FOUND_MARKER = "공보 찾지 못함"

# PBOC(중국인민은행)는 나머지 5개국과 달리 (1) 서구식 회의록(minutes) 자체를 공개하지 않고
# 분기별 통화정책위원회 例会(정례회의) 공보만 내며, (2) robots.txt가 Baidu를 제외한 전체
# 크롤러를 차단(`Disallow: /`)해 collectors/central_bank.py의 직접 스크래핑 방식을 쓸 수 없다
# - pbc.gov.cn을 우리가 직접 크롤링하지 않고 Claude의 web_search 도구로 최신 공보를 찾게
# 한다(collectors/web_research.py, earnings_transcript_web.py와 동일한 이유로 무인 collect
# 크론에는 포함하지 않는다).
DEFAULT_PBOC_MPC_SYSTEM_PROMPT = (
    "역할: 리서치 스크래퍼. web_search 도구로 중국인민은행(中国人民银行, PBOC) 통화정책위원회"
    "(货币政策委员会)의 가장 최근 정례회의(例会) 공보(公报/新闻稿)를 찾아라. "
    "pbc.gov.cn의 '沟通交流' 섹션(예: goutongjiaoliu 경로) 공식 발표문을 우선 신뢰하라.\n\n"
    "찾은 공보의 핵심 내용을 아래 형식으로 한국어로 정리하라 (전문을 그대로 옮기지 말고 "
    "핵심 판단·문구 위주로 구조화):\n\n"
    "## 회의 개요\n"
    "- 몇 년 몇 분기 정례회의인지, 개최일\n\n"
    "## 통화정책 기조 핵심 문구\n"
    "- 완화적/중립적/긴축적 등 스탠스 표현, 지준율(存款准备金率)·정책금리(LPR/MLF 등) 관련 "
    "언급이 있으면 원문 표현 그대로 1~2개 인용\n\n"
    "## 경기 판단\n"
    "- 국내외 경제 정세에 대한 평가 요지\n\n"
    "맨 끝에 반드시 `출처: [매체명](URL)` 형식으로 원문 링크를 밝혀라.\n\n"
    f'해당 분기의 공보를 찾지 못했으면, 다른 말 없이 정확히 "{_NOT_FOUND_MARKER}"라고만 답하라.'
)


class PbocMpcWebError(Exception):
    pass


def collect_pboc_mpc_web(
    client: AnthropicClient,
    quarter_label: str,
    system_prompt: str = DEFAULT_PBOC_MPC_SYSTEM_PROMPT,
) -> tuple[CollectResult | None, int, int]:
    """PBOC 통화정책위원회 최신 분기 정례회의 공보를 웹서치로 찾아 구조적 요약 1건을
    CollectItem으로 담아 반환한다. 못 찾으면 (None, 입력토큰, 출력토큰)을 반환한다 -
    호출부(pipeline/central_bank_pboc.py)는 이걸 "이번 분기는 처리 완료(못 찾음)"로
    체크포인트에 기록한다.
    """
    query = f"中国人民银行 货币政策委员会 {quarter_label} 例会 公报"
    response = client.create_message(
        system=system_prompt,
        messages=[{"role": "user", "content": query}],
        tools=[WEB_SEARCH_TOOL],
        max_tokens=2048,
    )
    text_blocks = [block.text for block in response.content if block.type == "text"]
    body_text = "\n".join(text_blocks).strip()
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens

    if not body_text:
        raise PbocMpcWebError("PBOC MPC 웹서치 응답에 텍스트 블록이 없음")

    if _NOT_FOUND_MARKER in body_text:
        return None, input_tokens, output_tokens

    now = datetime.now(UTC)
    item = CollectItem(
        source_specific_id=f"pboc-mpc-{quarter_label}",
        canonical_url=f"pboc-mpc-web-search://{quarter_label}",
        title=f"[PBOC 정례회의 공보-웹서치] {quarter_label}",
        author="PBOC",
        published_at=now,
        updated_at=None,
        language="ko",
        body_text=body_text,
        content_capture_mode="excerpt",
        content_capture_reason=(
            "pbc.gov.cn robots.txt(Disallow: /)로 직접 스크래핑 불가 - web_search 도구로 찾은 "
            "공보를 구조적으로 요약(전문 아님) - 전문은 본문 하단 출처 링크 참고"
        ),
        companies=[],
        themes=["macro", "central_bank", "CN"],
        document_type="central_bank_minutes",
        reporting_period=quarter_label,
    )
    result = CollectResult(
        source_id="central_bank_pboc_mpc", success=True, items=[item], errors=[], new_count=1
    )
    return result, input_tokens, output_tokens
