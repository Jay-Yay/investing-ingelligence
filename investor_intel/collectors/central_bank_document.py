from __future__ import annotations

# ib_insights_document.py와 동일한 "## 핵심 주장/근거/반대 근거/언급 자산" 빈 섹션 템플릿을
# 씌운다 - pipeline/claims_splice.py는 이 헤더가 본문에 이미 있어야만 analyze가 추출한 claim을
# 그 자리에 채워 넣는다(헤더가 없으면 splice_claims_into_body가 조용히 아무 것도 안 하고
# 원문을 그대로 반환한다).
CENTRAL_BANK_LIMITATIONS_NOTE = (
    "- 원문(성명서/의사록)을 중앙은행 공식 사이트에서 직접 수집한 것이다.\n"
    "- `published_at`은 실제 회의일이 아니라 수집 시각이다 - 회의록은 보통 회의일로부터\n"
    "  몇 주 뒤에야 공개되므로, 실제 회의일은 `reporting_period`를 참고한다.\n"
    "- 본문 추출에 실패하면 제목/링크만 캡처(metadata_only)한다 - 원문은 출처 링크 참고.\n"
)


def render_central_bank_body(
    title: str, source_url: str, body_text: str, mode: str, reason: str | None
) -> str:
    header = [title]
    if mode != "full":
        header.append(f"(본문 미확보: {reason})")

    sections = [
        "## 원문",
        "",
        *header,
        "",
        body_text,
        "",
        "## 수집 시 유의사항",
        "",
        CENTRAL_BANK_LIMITATIONS_NOTE,
        "## 핵심 주장",
        "",
        "## 근거",
        "",
        "## 반대 근거",
        "",
        "## 언급 자산",
        "",
        "## 포트폴리오 관련성",
        "",
        "## 출처",
        "",
        f"- [원문]({source_url})",
        "",
    ]
    return "\n".join(sections)
