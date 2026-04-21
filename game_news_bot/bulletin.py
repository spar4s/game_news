from __future__ import annotations

from pathlib import Path

from game_news_bot.config import DEFAULT_BUILD_DIR
from game_news_bot.utils import clean_html, to_channel_intro


def build_bulletins(
    conn,
    bulletin_date: str,
    limit: int = 5,
    since_iso: str | None = None,
    window_label: str | None = None,
) -> tuple[str, str]:
    where_clause = "WHERE t.is_breaking = 1"
    params: list[object] = []
    if since_iso:
        where_clause += " AND COALESCE(t.last_seen_at, t.first_seen_at) >= ?"
        params.append(since_iso)
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT
            t.title,
            t.category,
            t.summary,
            t.why_it_matters,
            t.context_note,
            t.importance_score,
            t.article_count,
            a.url,
            s.name AS source_name
        FROM topics t
        LEFT JOIN articles a ON a.id = t.representative_article_id
        LEFT JOIN sources s ON s.id = a.source_id
        {where_clause}
        ORDER BY t.importance_score DESC, t.article_count DESC, t.last_seen_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    label = window_label or bulletin_date
    title = f"游戏热点快讯 - {label}"
    lines = [f"# 游戏热点快讯 {label}", ""]

    if not rows:
        lines.extend(["- 这个时间窗口内还没有达到快讯阈值的热点。", ""])
    else:
        for index, row in enumerate(rows, start=1):
            summary = clean_html(row["summary"], max_length=100) or "等待后续补充摘要。"
            lines.append(f"## {index}. {to_channel_intro(row['category'])}")
            lines.append(f"标题：{row['title']}")
            lines.append(f"一句话：{summary}")
            if row["context_note"]:
                lines.append(str(row["context_note"]))
            if row["why_it_matters"]:
                lines.append(f"为什么值得发：{row['why_it_matters']}")
            lines.append(
                f"标签：{row['category']} | 热度：{row['importance_score']} | 相关报道：{row['article_count']}"
            )
            lines.append(f"来源参考：{row['source_name']}")
            lines.append(f"链接：{row['url']}")
            lines.append("")

    return title, "\n".join(lines).strip() + "\n"


def write_bulletins(content: str, bulletin_date: str, output: Path | None = None) -> Path:
    build_dir = DEFAULT_BUILD_DIR
    build_dir.mkdir(parents=True, exist_ok=True)
    target = output or build_dir / f"bulletins-{bulletin_date}.md"
    target.write_text(content, encoding="utf-8")
    return target
