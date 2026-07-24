from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime


@dataclass
class NaverPost:
    guid: str
    title: str
    link: str
    description: str
    published_at: datetime


def parse_naver_rss(xml_text: str) -> list[NaverPost]:
    root = ET.fromstring(xml_text)
    posts: list[NaverPost] = []
    for item in root.findall("./channel/item"):
        link = item.findtext("link") or ""
        posts.append(
            NaverPost(
                guid=item.findtext("guid") or link,
                title=item.findtext("title") or "",
                link=link,
                description=item.findtext("description") or "",
                published_at=parsedate_to_datetime(item.findtext("pubDate") or ""),
            )
        )
    return posts


def extract_blog_id(source_url: str) -> str:
    return source_url.rstrip("/").rsplit("/", 1)[-1]
