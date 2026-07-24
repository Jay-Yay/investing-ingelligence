from __future__ import annotations

from investor_intel.collectors.telethon_client import TelethonMessage
from investor_intel.models.config import SourceConfig

TELEGRAM_PRIVATE_LIMITATIONS_NOTE = (
    "- 이 컬렉터는 Telethon(MTProto)을 통해 사용자가 실제로 접근 권한을 가진 채널의 메시지를 "
    "수집하며, 공개 웹 미리보기(t.me/s/{channel})와 달리 인증된 사용자 세션이 필요하다.\n"
    "- 한 번에 최대 200개 메시지만 조회하며, 그 이상의 과거 히스토리는 이 단계에서 수집하지 "
    "않는다.\n"
    "- 이미지, 동영상 등 미디어 전용 메시지(텍스트 없음)는 캡처하지 않는다.\n"
)


def render_telethon_message_body(
    message: TelethonMessage,
    source: SourceConfig,
    canonical_url: str,
) -> str:
    sections = [
        "## 원문",
        "",
        f"{source.name} — {message.date.isoformat()}",
        "",
        message.text,
        "",
        "## 텔레그램 수집 시 유의사항",
        "",
        TELEGRAM_PRIVATE_LIMITATIONS_NOTE,
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
