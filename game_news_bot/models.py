from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ArticleRecord:
    source_name: str
    source_priority: int
    title: str
    url: str
    author: str | None
    summary: str | None
    content: str | None
    published_at: str | None
    fetched_at: str

