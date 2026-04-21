from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from game_news_bot.models import ArticleRecord
from game_news_bot.utils import clean_html
from game_news_bot.utils import utc_now_iso


def _strip_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_text(node: ET.Element, names: list[str]) -> str | None:
    for child in node.iter():
        if child is node:
            continue
        if _strip_tag(child.tag) in names:
            if child.text:
                return child.text.strip()
    return None


def _parse_pubdate(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    try:
        return parsedate_to_datetime(raw_value).isoformat()
    except Exception:
        return raw_value


def fetch_rss(source_name: str, source_priority: int, url: str) -> list[ArticleRecord]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; GameNewsBot/0.1; +https://example.com/bot)"
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read()

    root = ET.fromstring(payload)
    articles: list[ArticleRecord] = []
    fetched_at = utc_now_iso()

    for item in [node for node in root.iter() if _strip_tag(node.tag) == "item"]:
        title = _find_text(item, ["title"]) or "Untitled"
        link = _find_text(item, ["link"])
        if not link:
            continue

        summary = clean_html(_find_text(item, ["description", "summary"]), max_length=400)
        author = _find_text(item, ["author", "creator"])
        published_at = _parse_pubdate(_find_text(item, ["pubDate", "published", "updated"]))

        articles.append(
            ArticleRecord(
                source_name=source_name,
                source_priority=source_priority,
                title=title,
                url=link,
                author=author,
                summary=summary,
                content=summary,
                published_at=published_at,
                fetched_at=fetched_at,
            )
        )

    if articles:
        return articles

    for entry in [node for node in root.iter() if _strip_tag(node.tag) == "entry"]:
        title = _find_text(entry, ["title"]) or "Untitled"
        link = None
        for child in entry.iter():
            if child is entry:
                continue
            if _strip_tag(child.tag) == "link":
                link = child.attrib.get("href") or child.text
                if link:
                    break
        if not link:
            continue

        summary = clean_html(_find_text(entry, ["summary", "content"]), max_length=400)
        author = _find_text(entry, ["name", "author"])
        published_at = _parse_pubdate(_find_text(entry, ["published", "updated"]))

        articles.append(
            ArticleRecord(
                source_name=source_name,
                source_priority=source_priority,
                title=title,
                url=link,
                author=author,
                summary=summary,
                content=summary,
                published_at=published_at,
                fetched_at=fetched_at,
            )
        )

    return articles
