from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from game_news_bot.config import DEFAULT_DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    url TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 5,
    language TEXT NOT NULL DEFAULT 'en',
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    author TEXT,
    summary TEXT,
    content TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL,
    article_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'fetched',
    is_duplicate INTEGER NOT NULL DEFAULT 0,
    importance_score INTEGER NOT NULL DEFAULT 0,
    event_key TEXT,
    event_entities TEXT,
    is_hot INTEGER NOT NULL DEFAULT 0,
    context_note TEXT,
    ai_headline_zh TEXT,
    ai_summary_zh TEXT,
    ai_category TEXT,
    ai_why_it_matters TEXT,
    ai_confidence REAL,
    FOREIGN KEY (source_id) REFERENCES sources (id)
);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_date TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '其他',
    summary TEXT,
    why_it_matters TEXT,
    context_note TEXT,
    importance_score INTEGER NOT NULL DEFAULT 0,
    article_count INTEGER NOT NULL DEFAULT 1,
    is_breaking INTEGER NOT NULL DEFAULT 0,
    representative_article_id INTEGER,
    first_seen_at TEXT,
    last_seen_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topic_articles (
    topic_id INTEGER NOT NULL,
    article_id INTEGER NOT NULL UNIQUE,
    PRIMARY KEY (topic_id, article_id),
    FOREIGN KEY (topic_id) REFERENCES topics (id),
    FOREIGN KEY (article_id) REFERENCES articles (id)
);

CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_id INTEGER NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL,
    delivered_at TEXT NOT NULL,
    output_path TEXT,
    FOREIGN KEY (digest_id) REFERENCES digests (id)
);
"""


@contextmanager
def connect(db_path: Path | None = None):
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout = 60000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _ensure_article_columns(conn)
        _ensure_topic_indexes(conn)


def _ensure_article_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(articles)").fetchall()
    }
    wanted = {
        "event_key": "TEXT",
        "event_entities": "TEXT",
        "is_hot": "INTEGER NOT NULL DEFAULT 0",
        "context_note": "TEXT",
        "ai_headline_zh": "TEXT",
        "ai_summary_zh": "TEXT",
        "ai_category": "TEXT",
        "ai_why_it_matters": "TEXT",
        "ai_confidence": "REAL",
    }
    for name, column_type in wanted.items():
        if name not in existing:
            try:
                conn.execute(f"ALTER TABLE articles ADD COLUMN {name} {column_type}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
    _ensure_topic_columns(conn)


def _ensure_topic_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_topics_event_key
        ON topics (event_key)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_topic_articles_topic_id
        ON topic_articles (topic_id)
        """
    )


def _ensure_topic_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(topics)").fetchall()
    }
    wanted = {
        "is_breaking": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, column_type in wanted.items():
        if name not in existing:
            try:
                conn.execute(f"ALTER TABLE topics ADD COLUMN {name} {column_type}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
