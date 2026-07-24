from __future__ import annotations

from investor_intel.collectors.telegram_parser import TelegramMessage
from investor_intel.models.config import SourceConfig

TELEGRAM_LIMITATIONS_NOTE = (
    "- 이 컬렉터는 공개 웹 미리보기(t.me/s/{channel})만 수집하며, 비공개 채널이나 "
    "Telethon 기반 전체 히스토리 수집은 이 단계에서 구현하지 않는다.\n"
    "- 웹 미리보기는 최근 메시지 일부(단일 페이지)만 노출하며, 페이지네이션은 구현하지 않는다.\n"
    "- 이미지, 동영상 등 미디어 전용 메시지(텍스트 없음)는 캡처하지 않는다.\n"
)


def render_telegram_message_body(
    message: TelegramMessage,
    source: SourceConfig,
    canonical_url: str,
) -> str:
    sections = [
        "## 원문",
        "",
        f"{source.name} (@{message.channel}) — {message.published_at.isoformat()}",
        "",
        message.text,
        "",
        "## 텔레그램 수집 시 유의사항",
        "",
        TELEGRAM_LIMITATIONS_NOTE,
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
        f"- [원문]({canonical_url})",
        "",
    ]
    return "\n".join(sections)
