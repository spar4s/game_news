from __future__ import annotations

from pathlib import Path
import re

from game_news_bot.config import DEFAULT_BUILD_DIR
from game_news_bot.utils import clean_html


def fetch_player_buzz_rows(conn, limit: int = 10, since_iso: str | None = None):
    where_clause = """
        WHERE s.name LIKE 'Reddit %'
          AND a.is_duplicate = 0
          AND a.status = 'ready'
          AND a.importance_score >= 12
    """
    params: list[object] = []
    if since_iso:
        where_clause += " AND COALESCE(a.published_at, a.fetched_at) >= ?"
        params.append(since_iso)
    params.append(max(limit * 4, 20))

    rows = conn.execute(
        f"""
        SELECT
            s.name AS source_name,
            a.title,
            a.summary,
            a.url,
            a.importance_score,
            a.context_note,
            a.ai_headline_zh,
            a.ai_summary_zh,
            a.ai_why_it_matters,
            a.ai_confidence
        FROM articles a
        JOIN sources s ON s.id = a.source_id
        {where_clause}
        ORDER BY a.importance_score DESC, COALESCE(a.published_at, a.fetched_at) DESC, a.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    scored = []
    for row in rows:
        score = _player_buzz_score(row)
        if score is None:
            continue
        scored.append((score, row))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:limit]]


def build_player_buzz(
    conn,
    report_date: str,
    limit: int = 10,
    since_iso: str | None = None,
    window_label: str | None = None,
) -> tuple[str, str]:
    rows = fetch_player_buzz_rows(conn, limit=limit, since_iso=since_iso)

    label = window_label or report_date
    title = f"玩家热议 - {label}"
    lines = [f"# 玩家热议 {label}", ""]

    if not rows:
        lines.extend(["- 这个时间窗口内还没有值得收录的 Reddit 热议。", ""])
        return title, "\n".join(lines).strip() + "\n"

    for index, row in enumerate(rows, start=1):
        headline = row["ai_headline_zh"] or row["title"]
        summary = row["ai_summary_zh"] or clean_html(row["summary"], max_length=120) or "等待后续补充摘要。"
        lines.append(f"## {index}. {headline}")
        lines.append(f"来源社区：{row['source_name']}")
        lines.append(f"热度参考：{row['importance_score']}")
        lines.append(f"讨论点：{summary}")
        if row["context_note"]:
            lines.append(str(row["context_note"]))
        if row["ai_why_it_matters"]:
            lines.append(f"为什么值得看：{row['ai_why_it_matters']}")
        lines.append(f"链接：{row['url']}")
        lines.append("")

    return title, "\n".join(lines).strip() + "\n"


def write_player_buzz(content: str, report_slug: str, output: Path | None = None) -> Path:
    build_dir = DEFAULT_BUILD_DIR
    build_dir.mkdir(parents=True, exist_ok=True)
    target = output or build_dir / f"player-buzz-{report_slug}.md"
    target.write_text(content, encoding="utf-8")
    return target


def _player_buzz_score(row) -> int | None:
    title = str(row["title"] or "")
    summary = clean_html(row["summary"], max_length=240)
    source_name = str(row["source_name"] or "")
    title_lower = title.lower()
    summary_lower = summary.lower()
    combined = f"{title_lower} {summary_lower}"

    if not title.strip():
        return None

    hard_excludes = [
        "[ama]",
        " ama ",
        "ask me anything",
        "hello reddit",
        "reposted this",
        "stay in compliance with formatting guide",
        "formatting guide",
        "official trailer",
        "launch trailer",
        "release trailer",
        "release date trailer",
        "teaser trailer",
        "gameplay trailer",
        "character trailer",
        "pre-order trailer",
        "announcement trailer",
        "cgi trailer",
        "story trailer",
        "official reveal",
        "showcase announced",
        "reveal time and date confirmed",
        "available on steam",
        "available on steam now",
        "out now on steam",
        "now available on steam",
        "now on steam",
        "coming to playstation 5",
        "coming to ps5",
        "coming to xbox",
        "coming to game pass",
        "20% discount",
        "wishlist now",
        "my game",
        "i launched my",
        "i'm the solo-indie developer",
        "we decided to rebuild as a small team",
        "submitted by /u/",
    ]
    if any(pattern in combined for pattern in hard_excludes):
        return None

    if "submitted by /u/" in summary_lower:
        return None

    if summary_lower in {"submitted by /u/ [link] [comments]", "[link] [comments]"}:
        return None

    if re.fullmatch(r".*(trailer|teaser)\s*!*", title_lower):
        return None

    if re.search(r"\b(out now|available now|official trailer|launch trailer|teaser|showcase|announced|reveal(ed)?|release date)\b", title_lower):
        return None

    discussion_signals = [
        "why",
        "how",
        "what do you think",
        "anyone else",
        "lets be honest",
        "let's be honest",
        "don't actually own",
        "dont actually own",
        "we've all just accepted",
        "weve all just accepted",
        "i love",
        "i hate",
        "feels like",
        "performance",
        "stutter",
        "microstutter",
        "shader compilation",
        "drm",
        "ownership",
        "refund",
        "anti-cheat",
        "anti cheat",
        "linux",
        "steam deck",
        "review bombing",
        "boycott",
        "layoffs",
        "server issues",
        "servers are down",
        "monetization",
        "pricing",
        "regional pricing",
        "community edition",
        "modding",
        "mods",
        "patch broke",
        "broken on pc",
        "new steam update",
        "last updated",
        "do you still",
        "is anyone else",
    ]
    has_discussion_signal = any(signal in combined for signal in discussion_signals)
    has_question_title = "?" in title
    has_substantive_summary = len(summary) >= 90 and "[link] [comments]" not in summary_lower
    opinion_markers = [
        " i ",
        " we ",
        " my ",
        " our ",
        "personally",
        "honest",
        "feel like",
        "frustrating",
        "annoying",
        "wish",
    ]
    has_opinion_voice = any(marker in f" {summary_lower} " or marker in f" {title_lower} " for marker in opinion_markers)

    if not (has_discussion_signal or has_question_title or (has_substantive_summary and has_opinion_voice)):
        return None

    score = int(row["importance_score"] or 0)
    for signal in discussion_signals:
        if signal in combined:
            score += 10

    if len(summary) >= 80:
        score += 8
    elif len(summary) >= 40:
        score += 4

    source_name_lower = source_name.lower()
    if any(name in source_name_lower for name in ["reddit /r/games", "reddit /r/pcgaming", "reddit /r/steam"]):
        score += 6
    elif "reddit /r/gaming" in source_name_lower:
        score += 2
    elif "reddit /r/pcmasterrace" in source_name_lower:
        score += 1
    elif "reddit /r/ps5" in source_name_lower:
        score -= 10

    if has_question_title and "steam" not in title_lower:
        score += 3

    if has_opinion_voice:
        score += 6

    soft_penalties = [
        "on sale now",
        "launches",
        "coming to playstation 5",
        "coming to xbox game pass",
        "available now",
        "out now",
        "official release",
    ]
    for penalty in soft_penalties:
        if penalty in combined:
            score -= 6

    return score if score >= 32 else None
