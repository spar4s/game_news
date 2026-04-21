from __future__ import annotations

from game_news_bot.ai.client import analyze_article, summarize_context
from game_news_bot.config import AIConfig
from game_news_bot.utils import (
    CATEGORY_COMMUNITY,
    CATEGORY_OTHER,
    build_context_note,
    build_why_it_matters,
    compute_importance,
    deserialize_entities,
    extract_event_key,
    extract_named_entities,
    extract_topic_terms,
    generate_fallback_headline,
    generate_fallback_summary,
    infer_category,
    is_breaking_topic,
    is_low_signal_article,
    serialize_entities,
    utc_now_iso,
)


def process_articles(
    conn,
    ai_config: AIConfig | None = None,
    ai_limit: int | None = None,
    refresh_ai: bool = False,
) -> dict[str, int]:
    ai_candidates = _select_ai_candidates(conn, ai_limit, refresh_ai) if ai_config and ai_config.enabled and ai_config.api_key else set()
    rows = conn.execute(
        """
        SELECT a.id, a.title, a.normalized_title, a.url, a.summary, a.published_at, a.fetched_at,
               a.ai_headline_zh, a.ai_summary_zh, a.ai_category, a.ai_why_it_matters, a.ai_confidence,
               s.priority, s.name AS source_name
        FROM articles a
        JOIN sources s ON s.id = a.source_id
        ORDER BY a.id ASC
        """
    ).fetchall()

    seen_titles: set[str] = set()
    duplicate_count = 0
    processed_count = 0
    ai_enriched_count = 0
    filtered_count = 0

    for row in rows:
        normalized_title = row["normalized_title"]
        is_duplicate = int(normalized_title in seen_titles)
        if is_duplicate:
            duplicate_count += 1
        else:
            seen_titles.add(normalized_title)

        importance = compute_importance(
            row["title"],
            int(row["priority"]),
            source_name=row["source_name"],
            url=row["url"],
        )
        is_filtered = int(is_low_signal_article(row["title"], row["source_name"], row["url"]))
        if is_filtered:
            filtered_count += 1
            importance = max(0, importance - 30)

        if is_duplicate:
            status = "duplicate"
        elif is_filtered:
            status = "filtered"
        else:
            status = "ready"

        ai_payload = None
        fallback_category = infer_category(
            row["title"],
            source_name=row["source_name"],
            summary=row["summary"] or "",
        )
        fallback_headline = generate_fallback_headline(row["title"], fallback_category)
        fallback_summary = generate_fallback_summary(
            row["title"],
            row["summary"] or "",
            row["source_name"],
            fallback_category,
        )
        fallback_why = build_why_it_matters(row["title"], fallback_category)
        event_key = extract_event_key(row["title"])
        event_entities = extract_named_entities(row["title"])

        prior_rows = _find_related_history(
            conn=conn,
            article_id=row["id"],
            title=row["title"],
            event_key=event_key,
            category=fallback_category,
            event_entities=event_entities,
        )
        prior_titles = [prior["title"] for prior in prior_rows if prior["title"] != row["title"]]
        context_note = build_context_note(row["title"], prior_titles, fallback_category)
        is_hot = int(len(prior_titles) > 0 or importance >= 90)

        if (
            not is_duplicate
            and row["id"] in ai_candidates
            and ai_config
            and ai_config.enabled
            and ai_config.api_key
        ):
            try:
                ai_payload = analyze_article(
                    ai_config,
                    {
                        "title": row["title"],
                        "summary": row["summary"] or "",
                        "source_name": row["source_name"],
                        "url": row["url"],
                    },
                )
                ai_enriched_count += 1
            except Exception:
                ai_payload = None

        if prior_titles and row["id"] in ai_candidates and ai_config and ai_config.enabled and ai_config.api_key:
            try:
                ai_context = summarize_context(
                    ai_config,
                    current_title=row["title"],
                    current_summary=row["summary"] or "",
                    prior_titles=prior_titles,
                )
                if ai_context:
                    context_note = f"前情提要：{ai_context}"
            except Exception:
                pass

        conn.execute(
            """
            UPDATE articles
            SET is_duplicate = ?, importance_score = ?, status = ?,
                event_key = ?, event_entities = ?, is_hot = ?, context_note = ?,
                ai_headline_zh = ?, ai_summary_zh = ?, ai_category = ?,
                ai_why_it_matters = ?, ai_confidence = ?
            WHERE id = ?
            """,
            (
                is_duplicate,
                importance,
                status,
                event_key,
                serialize_entities(event_entities),
                is_hot,
                context_note,
                ai_payload["headline_zh"] if ai_payload else (row["ai_headline_zh"] or fallback_headline),
                ai_payload["summary_zh"] if ai_payload else (row["ai_summary_zh"] or fallback_summary),
                ai_payload["category"] if ai_payload else (row["ai_category"] or fallback_category),
                ai_payload["why_it_matters"] if ai_payload else (row["ai_why_it_matters"] or fallback_why),
                ai_payload["confidence"] if ai_payload else row["ai_confidence"],
                row["id"],
            ),
        )
        processed_count += 1

    topic_count = rebuild_topics(conn)
    return {
        "processed": processed_count,
        "duplicates": duplicate_count,
        "filtered": filtered_count,
        "ai_enriched": ai_enriched_count,
        "topics": topic_count,
    }


def count_pending_ai_articles(conn, refresh_ai: bool = False) -> int:
    where_clause = "a.is_duplicate = 0 AND a.status = 'ready'"
    if not refresh_ai:
        where_clause += " AND a.ai_confidence IS NULL"

    row = conn.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM articles a
        WHERE {where_clause}
        """
    ).fetchone()
    return int(row["total"]) if row else 0


def _select_ai_candidates(conn, ai_limit: int | None, refresh_ai: bool) -> set[int]:
    if ai_limit is not None and ai_limit <= 0:
        return set()

    where_clause = "a.is_duplicate = 0 AND a.status = 'ready'"
    if not refresh_ai:
        where_clause += " AND a.ai_confidence IS NULL"

    params: list[object] = []
    sql = f"""
        SELECT a.id
        FROM articles a
        WHERE {where_clause}
        ORDER BY a.importance_score DESC, COALESCE(a.published_at, a.fetched_at) DESC, a.id DESC
    """
    if ai_limit is not None:
        sql += " LIMIT ?"
        params.append(ai_limit)

    rows = conn.execute(sql, params).fetchall()
    return {int(row["id"]) for row in rows}


def _find_related_history(
    conn,
    article_id: int,
    title: str,
    event_key: str,
    category: str,
    event_entities: list[str],
):
    direct_rows = conn.execute(
        """
        SELECT title, event_entities, ai_category
        FROM articles
        WHERE id <> ? AND event_key = ?
        ORDER BY COALESCE(published_at, fetched_at) DESC
        LIMIT 3
        """,
        (article_id, event_key),
    ).fetchall()
    filtered_direct = _filter_direct_matches(direct_rows, category, event_entities)
    if filtered_direct:
        return filtered_direct[:3]

    terms = extract_topic_terms(title)
    if not terms:
        return []

    candidates = conn.execute(
        """
        SELECT title, event_entities, ai_category, published_at, fetched_at
        FROM articles
        WHERE id <> ?
        ORDER BY COALESCE(published_at, fetched_at) DESC
        LIMIT 60
        """,
        (article_id,),
    ).fetchall()

    scored: list[tuple[int, object]] = []
    current_entities = set(event_entities)
    for candidate in candidates:
        candidate_terms = extract_topic_terms(candidate["title"])
        overlap = terms & candidate_terms
        candidate_entities = set(deserialize_entities(candidate["event_entities"]))
        entity_overlap = current_entities & candidate_entities
        candidate_category = candidate["ai_category"] or CATEGORY_OTHER

        if current_entities and candidate_entities:
            if entity_overlap and candidate_category == category:
                scored.append((10 + len(entity_overlap), candidate))
            continue

        if len(overlap) >= 2 and candidate_category == category and category not in {CATEGORY_OTHER, CATEGORY_COMMUNITY}:
            scored.append((len(overlap), candidate))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:3]]


def _filter_direct_matches(rows, category: str, event_entities: list[str]):
    filtered = []
    current_entities = set(event_entities)
    for row in rows:
        row_entities = set(deserialize_entities(row["event_entities"]))
        row_category = row["ai_category"] or CATEGORY_OTHER
        same_category = row_category == category

        if current_entities and row_entities and current_entities.isdisjoint(row_entities):
            continue
        if not same_category and category in {CATEGORY_COMMUNITY, CATEGORY_OTHER}:
            continue
        filtered.append(row)
    return filtered


def rebuild_topics(conn) -> int:
    conn.execute("DELETE FROM topic_articles")
    conn.execute("DELETE FROM topics")

    rows = conn.execute(
        """
        SELECT
            id,
            title,
            summary,
            published_at,
            fetched_at,
            event_key,
            importance_score,
            context_note,
            ai_headline_zh,
            ai_summary_zh,
            ai_category,
            ai_why_it_matters,
            is_duplicate
        FROM articles
        WHERE is_duplicate = 0 AND status = 'ready'
        ORDER BY importance_score DESC, COALESCE(published_at, fetched_at) DESC, id DESC
        """
    ).fetchall()

    buckets: dict[tuple[str, str], list] = {}
    for row in rows:
        category = row["ai_category"] or CATEGORY_OTHER
        event_key = row["event_key"] or f"article-{row['id']}"
        buckets.setdefault((event_key, category), []).append(row)

    now = utc_now_iso()
    topic_count = 0
    for (event_key, category), bucket_rows in buckets.items():
        representative = bucket_rows[0]
        article_count = len(bucket_rows)
        importance = max(int(item["importance_score"]) for item in bucket_rows)
        first_seen = min((item["published_at"] or item["fetched_at"] or now) for item in bucket_rows)
        last_seen = max((item["published_at"] or item["fetched_at"] or now) for item in bucket_rows)
        title = representative["ai_headline_zh"] or representative["title"]
        summary = representative["ai_summary_zh"] or representative["summary"]
        why = representative["ai_why_it_matters"]
        context_note = representative["context_note"]
        is_breaking = int(
            is_breaking_topic(
                title=title,
                category=category,
                importance=importance,
                article_count=article_count,
                context_note=context_note,
            )
        )

        cursor = conn.execute(
            """
            INSERT INTO topics (
                event_key, title, category, summary, why_it_matters, context_note,
                importance_score, article_count, is_breaking, representative_article_id,
                first_seen_at, last_seen_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_key,
                title,
                category,
                summary,
                why,
                context_note,
                importance,
                article_count,
                is_breaking,
                representative["id"],
                first_seen,
                last_seen,
                now,
                now,
            ),
        )
        topic_id = int(cursor.lastrowid)
        for item in bucket_rows:
            conn.execute(
                """
                INSERT INTO topic_articles (topic_id, article_id)
                VALUES (?, ?)
                """,
                (topic_id, item["id"]),
            )
        topic_count += 1

    return topic_count
