from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime

from game_news_bot.community import fetch_player_buzz_rows
from game_news_bot.utils import CATEGORY_OTHER, SECTION_TITLES, clean_html


SECTION_ORDER = OrderedDict(
    [
        ("新作公布", SECTION_TITLES["新作公布"]),
        ("发售日期", SECTION_TITLES["发售日期"]),
        ("更新补丁", SECTION_TITLES["更新补丁"]),
        ("DLC扩展", SECTION_TITLES["DLC扩展"]),
        ("平台动态", SECTION_TITLES["平台动态"]),
        ("行业动态", SECTION_TITLES["行业动态"]),
        ("社区热点", SECTION_TITLES["社区热点"]),
        ("传闻爆料", SECTION_TITLES["传闻爆料"]),
        ("其他", SECTION_TITLES["其他"]),
    ]
)


def build_digest(
    conn,
    digest_date: str,
    channel_name: str,
    max_items: int,
    since_iso: str | None = None,
    window_label: str | None = None,
) -> tuple[str, str]:
    where_clause = ""
    params: list[object] = []
    if since_iso:
        where_clause = "WHERE COALESCE(t.last_seen_at, t.first_seen_at) >= ?"
        params.append(since_iso)
    params.append(max_items)

    rows = conn.execute(
        f"""
        SELECT
            t.title,
            t.summary,
            t.importance_score,
            CASE WHEN t.article_count > 1 OR t.importance_score >= 90 THEN 1 ELSE 0 END AS is_hot,
            t.context_note,
            t.category,
            t.why_it_matters,
            t.article_count,
            a.url,
            s.name AS source_name
        FROM topics t
        LEFT JOIN articles a ON a.id = t.representative_article_id
        LEFT JOIN sources s ON s.id = a.source_id
        {where_clause}
        ORDER BY t.importance_score DESC, COALESCE(t.last_seen_at, t.first_seen_at) DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    title = f"{channel_name} - {digest_date}"
    heading = f"# {channel_name} {digest_date}"
    if window_label:
        title = f"{channel_name} - {window_label}"
        heading = f"# {channel_name} {window_label}"

    lines = [heading, ""]

    if not rows:
        lines.extend(["## 今日重点", "- 这个时间窗口内还没有可用资讯。", ""])
    else:
        sections: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            display_title = row["title"]
            summary = clean_html(row["summary"], max_length=140) or "这条消息已经进入本轮资讯跟踪列表。"
            category = row["category"] or CATEGORY_OTHER
            section_name = SECTION_ORDER.get(category, SECTION_TITLES[CATEGORY_OTHER])
            sections.setdefault(section_name, []).append(
                {
                    "title": display_title,
                    "summary": summary,
                    "source_name": row["source_name"],
                    "score": row["importance_score"],
                    "is_hot": row["is_hot"],
                    "context_note": row["context_note"],
                    "why": row["why_it_matters"],
                    "article_count": row["article_count"],
                    "url": row["url"],
                    "category": category,
                }
            )

        lines.append("## 今日导读")
        for row in rows[:3]:
            display_title = row["title"]
            category = row["category"] or CATEGORY_OTHER
            lines.append(f"- {display_title}（{category}）")
        lines.append("")

        seen_sections: set[str] = set()
        for section_name in SECTION_ORDER.values():
            if section_name in seen_sections:
                continue
            seen_sections.add(section_name)
            if section_name not in sections:
                continue
            lines.append(f"## {section_name}")
            for item in sections[section_name]:
                lines.append(f"- **{item['title']}**")
                lines.append(f"  摘要：{item['summary']}")
                if item["is_hot"] and item["context_note"]:
                    lines.append(f"  {item['context_note']}")
                if item["why"]:
                    lines.append(f"  看点：{item['why']}")
                lines.append(
                    f"  来源：{item['source_name']} | 热度：{item['score']} | 相关报道：{item['article_count']}"
                )
                lines.append(f"  链接：{item['url']}")
                lines.append("")

    player_rows = fetch_player_buzz_rows(conn, limit=6, since_iso=since_iso)
    if player_rows:
        lines.append("## 玩家热议")
        for row in player_rows:
            headline = row["ai_headline_zh"] or row["title"]
            summary = row["ai_summary_zh"] or clean_html(row["summary"], max_length=120) or "等待后续补充摘要。"
            lines.append(f"- **{headline}**")
            lines.append(f"  社区：{row['source_name']}")
            lines.append(f"  讨论点：{summary}")
            if row["ai_why_it_matters"]:
                lines.append(f"  为什么值得看：{row['ai_why_it_matters']}")
            lines.append(f"  链接：{row['url']}")
            lines.append("")

    content = "\n".join(lines).strip() + "\n"
    conn.execute(
        """
        INSERT INTO digests (digest_date, title, content, generated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(digest_date) DO UPDATE SET
            title = excluded.title,
            content = excluded.content,
            generated_at = excluded.generated_at
        """,
        (digest_date, title, content, datetime.now(UTC).replace(microsecond=0).isoformat()),
    )
    return title, content
