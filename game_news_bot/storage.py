from __future__ import annotations

from game_news_bot.models import ArticleRecord
from game_news_bot.utils import article_hash, normalize_title


def upsert_source(conn, name: str, source_type: str, url: str, priority: int, language: str, enabled: bool) -> int:
    conn.execute(
        """
        INSERT INTO sources (name, type, url, priority, language, enabled)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            type = excluded.type,
            url = excluded.url,
            priority = excluded.priority,
            language = excluded.language,
            enabled = excluded.enabled
        """,
        (name, source_type, url, priority, language, int(enabled)),
    )
    row = conn.execute("SELECT id FROM sources WHERE name = ?", (name,)).fetchone()
    return int(row["id"])


def insert_article(conn, source_id: int, article: ArticleRecord) -> bool:
    try:
        conn.execute(
            """
            INSERT INTO articles (
                source_id, title, normalized_title, url, author, summary,
                content, published_at, fetched_at, article_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_id,
                article.title,
                normalize_title(article.title),
                article.url,
                article.author,
                article.summary,
                article.content,
                article.published_at,
                article.fetched_at,
                article_hash(article.title, article.url),
            ),
        )
    except Exception:
        return False
    return True

