from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class NaverResearchStub:
    research_id: int
    item_code: str
    item_name: str
    title: str
    broker_name: str
    write_date: date | None
    rank: int | None = None


@dataclass
class NaverResearchDetail:
    content_text: str | None
    opinion: str | None
    goal_price: float | None
    prev_goal_price: float | None
    attach_url: str | None
    item_name: str | None = None


def _parse_write_date(text: object) -> date | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_naver_research_list(json_text: str) -> list[NaverResearchStub]:
    data = json.loads(json_text)
    stubs: list[NaverResearchStub] = []
    for item in data:
        research_id = item.get("researchId")
        if research_id is None:
            continue
        stubs.append(
            NaverResearchStub(
                research_id=int(research_id),
                item_code=str(item.get("itemCode") or ""),
                item_name=str(item.get("itemName") or ""),
                title=str(item.get("title") or ""),
                broker_name=str(item.get("brokerName") or ""),
                write_date=_parse_write_date(item.get("writeDate")),
            )
        )
    return stubs


def _strip_html(html_fragment: str) -> str:
    text = _TAG_RE.sub("", html_fragment)
    return text.replace("&nbsp;", " ").replace("&amp;", "&").strip()


def _parse_price(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def parse_naver_research_detail(json_text: str) -> NaverResearchDetail:
    data = json.loads(json_text)
    content = data.get("researchContent", data)
    raw_content = content.get("content")
    return NaverResearchDetail(
        content_text=_strip_html(raw_content) if raw_content else None,
        opinion=content.get("opinion") or None,
        goal_price=_parse_price(content.get("goalPrice")),
        prev_goal_price=_parse_price(content.get("prevGoalPrice")),
        attach_url=content.get("attachUrl") or None,
        item_name=content.get("itemName") or None,
    )


def parse_weekly_hot_list(json_text: str) -> list[NaverResearchStub]:
    """stock.naver.com/api/stockSecurity/researches/v2/weekly-hot - the "요즘 많이 보는 리포트"
    ranking widget. Unlike the general listing, rows here have no itemName (only itemCode),
    so callers should prefer NaverResearchDetail.item_name once fetched."""
    data = json.loads(json_text)
    stubs: list[NaverResearchStub] = []
    for item in data.get("researchList", []):
        nid = item.get("nid")
        if nid is None:
            continue
        try:
            rank = int(item["ranking"]) if item.get("ranking") is not None else None
        except (TypeError, ValueError):
            rank = None
        stubs.append(
            NaverResearchStub(
                research_id=int(nid),
                item_code=str(item.get("itemCode") or ""),
                item_name="",
                title=str(item.get("title") or ""),
                broker_name=str(item.get("brokerName") or ""),
                write_date=_parse_write_date(item.get("writeDate")),
                rank=rank,
            )
        )
    return stubs
