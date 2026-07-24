from investor_intel.collectors.essay_document import ESSAY_LIMITATIONS_NOTE, render_essay_body
from investor_intel.collectors.essay_parser import EssayPage
from investor_intel.models.config import InvestorConfig


def _investor() -> InvestorConfig:
    return InvestorConfig(
        id="situational_awareness",
        name="Leopold Aschenbrenner",
        fund_name="Situational Awareness LP",
        cik="0001234567",
        related_essay_url="https://situational-awareness.ai/",
    )


def _page() -> EssayPage:
    return EssayPage(
        title="SITUATIONAL AWARENESS: The Decade Ahead",
        body_text="You can see the future first in San Francisco.",
    )


def test_render_includes_all_required_sections() -> None:
    body = render_essay_body(_page(), _investor(), "https://situational-awareness.ai/")
    for section in (
        "## 원문",
        "## 에세이 수집 시 유의사항",
        "## 핵심 주장",
        "## 근거",
        "## 반대 근거",
        "## 언급 자산",
        "## 포트폴리오 관련성",
        "## 출처",
    ):
        assert section in body

    assert "SITUATIONAL AWARENESS: The Decade Ahead" in body
    assert "You can see the future first in San Francisco." in body
    assert "https://situational-awareness.ai/" in body


def test_render_includes_limitations_note_verbatim() -> None:
    body = render_essay_body(_page(), _investor(), "https://example.com")
    assert ESSAY_LIMITATIONS_NOTE in body
