from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from game_news_bot.bulletin import build_bulletins, write_bulletins
from game_news_bot.collectors.rss import fetch_rss
from game_news_bot.community import build_player_buzz, write_player_buzz
from game_news_bot.config import DEFAULT_BUILD_DIR, DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, load_config
from game_news_bot.db import connect, init_db
from game_news_bot.digest import build_digest
from game_news_bot.pipelines.process import count_pending_ai_articles, process_articles
from game_news_bot.publish import publish_digest
from game_news_bot.site import build_site, write_site
from game_news_bot.storage import insert_article, upsert_source


def _resolve_date(raw_date: str | None) -> str:
    if raw_date:
        return raw_date
    return datetime.now().date().isoformat()


def _resolve_since_iso(hours: int | None) -> str | None:
    if hours is None:
        return None
    since = datetime.now(UTC) - timedelta(hours=hours)
    return since.replace(microsecond=0).isoformat()


def _window_label(hours: int | None, digest_date: str) -> str | None:
    if hours is None:
        return None
    return f"过去 {hours} 小时（截至 {digest_date}）"


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        sys.stdout.buffer.write(text.encode(encoding, errors="replace"))
        sys.stdout.buffer.write(b"\n")


def cmd_init_db(args: argparse.Namespace) -> int:
    init_db(Path(args.db))
    print(f"Initialized database at {args.db}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    init_db(Path(args.db))

    inserted = 0
    skipped = 0
    with connect(Path(args.db)) as conn:
        for source in config.sources:
            if not source.enabled or source.type != "rss":
                continue

            source_id = upsert_source(
                conn,
                name=source.name,
                source_type=source.type,
                url=source.url,
                priority=source.priority,
                language=source.language,
                enabled=source.enabled,
            )

            try:
                articles = fetch_rss(source.name, source.priority, source.url)
            except Exception as exc:
                print(f"[fetch] {source.name} failed: {exc}")
                continue

            for article in articles:
                if insert_article(conn, source_id, article):
                    inserted += 1
                else:
                    skipped += 1

            print(f"[fetch] {source.name}: {len(articles)} items")

    print(f"Fetch complete: inserted={inserted}, skipped={skipped}")
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    init_db(Path(args.db))
    ai_limit = args.ai_limit if args.ai_limit is not None else config.ai.max_articles_per_run
    max_batches = args.ai_batches if args.ai_batches is not None else config.ai.max_batches_per_run

    aggregate = {
        "processed": 0,
        "duplicates": 0,
        "filtered": 0,
        "ai_enriched": 0,
        "topics": 0,
        "batches": 0,
        "pending_ai": 0,
    }
    with connect(Path(args.db)) as conn:
        if not config.ai.enabled or not config.ai.api_key or max_batches <= 1:
            result = process_articles(
                conn,
                ai_config=config.ai,
                ai_limit=ai_limit,
                refresh_ai=args.refresh_ai,
            )
            aggregate.update(result)
            aggregate["batches"] = 1
            aggregate["pending_ai"] = count_pending_ai_articles(conn, refresh_ai=args.refresh_ai)
        else:
            for batch_no in range(1, max_batches + 1):
                pending_before = count_pending_ai_articles(conn, refresh_ai=args.refresh_ai)
                if pending_before <= 0:
                    break

                result = process_articles(
                    conn,
                    ai_config=config.ai,
                    ai_limit=ai_limit,
                    refresh_ai=args.refresh_ai,
                )
                aggregate["processed"] += result["processed"]
                aggregate["duplicates"] += result["duplicates"]
                aggregate["filtered"] += result["filtered"]
                aggregate["ai_enriched"] += result["ai_enriched"]
                aggregate["topics"] = result["topics"]
                aggregate["batches"] = batch_no
                aggregate["pending_ai"] = count_pending_ai_articles(conn, refresh_ai=args.refresh_ai)
                print(
                    f"[process] batch {batch_no}: "
                    f"ai_enriched={result['ai_enriched']}, "
                    f"pending_ai={aggregate['pending_ai']}"
                )
                if result["ai_enriched"] <= 0:
                    break

            if aggregate["batches"] == 0:
                result = process_articles(
                    conn,
                    ai_config=config.ai,
                    ai_limit=0,
                    refresh_ai=args.refresh_ai,
                )
                aggregate.update(result)
                aggregate["batches"] = 1
                aggregate["pending_ai"] = count_pending_ai_articles(conn, refresh_ai=args.refresh_ai)

            if aggregate["batches"] == 0:
                result = process_articles(
                    conn,
                    ai_config=config.ai,
                    ai_limit=0,
                    refresh_ai=args.refresh_ai,
                )
                aggregate["processed"] = result["processed"]
                aggregate["duplicates"] = result["duplicates"]
                aggregate["filtered"] = result["filtered"]
                aggregate["ai_enriched"] = result["ai_enriched"]
                aggregate["topics"] = result["topics"]
                aggregate["batches"] = 1
                aggregate["pending_ai"] = count_pending_ai_articles(conn, refresh_ai=args.refresh_ai)
    print(
        "Process complete: "
        f"processed={aggregate['processed']}, "
        f"duplicates={aggregate['duplicates']}, "
        f"filtered={aggregate['filtered']}, "
        f"ai_enriched={aggregate['ai_enriched']}, "
        f"topics={aggregate['topics']}, "
        f"batches={aggregate['batches']}, "
        f"pending_ai={aggregate['pending_ai']}"
    )
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    init_db(Path(args.db))
    digest_date = _resolve_date(args.date)
    with connect(Path(args.db)) as conn:
        title, content = build_digest(
            conn,
            digest_date=digest_date,
            channel_name=config.channel_profile.name,
            max_items=config.channel_profile.max_digest_items,
        )
    _safe_print(title)
    _safe_print(content)
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    init_db(Path(args.db))
    digest_date = _resolve_date(args.date)
    with connect(Path(args.db)) as conn:
        output = publish_digest(
            conn,
            digest_date=digest_date,
            target=args.target,
            output=Path(args.output) if args.output else None,
        )
    if output:
        print(f"Published to file: {output}")
    return 0


def cmd_bulletins(args: argparse.Namespace) -> int:
    init_db(Path(args.db))
    bulletin_date = _resolve_date(args.date)
    since_iso = _resolve_since_iso(args.hours)
    window_label = _window_label(args.hours, bulletin_date)
    with connect(Path(args.db)) as conn:
        title, content = build_bulletins(
            conn,
            bulletin_date=bulletin_date,
            limit=args.limit,
            since_iso=since_iso,
            window_label=window_label,
        )
    _safe_print(title)
    _safe_print(content)
    if args.output:
        output = write_bulletins(content, bulletin_date=bulletin_date, output=Path(args.output))
        print(f"Bulletins written to: {output}")
    return 0


def cmd_site(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    init_db(Path(args.db))
    site_date = _resolve_date(args.date)
    with connect(Path(args.db)) as conn:
        title, home_html, archive_pages = build_site(
            conn,
            site_date=site_date,
            channel_name=config.channel_profile.name,
            max_items=config.channel_profile.max_digest_items,
        )
    output = write_site(
        home_html,
        archive_pages,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    print(f"{title}")
    print(f"Site written to: {output}")
    return 0


def cmd_player_buzz(args: argparse.Namespace) -> int:
    init_db(Path(args.db))
    report_date = _resolve_date(args.date)
    since_iso = _resolve_since_iso(args.hours)
    window_label = _window_label(args.hours, report_date)
    slug = f"last-{args.hours}h" if args.hours is not None else report_date
    with connect(Path(args.db)) as conn:
        title, content = build_player_buzz(
            conn,
            report_date=report_date,
            limit=args.limit,
            since_iso=since_iso,
            window_label=window_label,
        )
    _safe_print(title)
    _safe_print(content)
    if args.output:
        output = write_player_buzz(content, report_slug=slug, output=Path(args.output))
        print(f"Player buzz written to: {output}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config))
    init_db(Path(args.db))
    digest_date = _resolve_date(args.date)
    since_iso = _resolve_since_iso(args.hours)
    window_label = _window_label(args.hours, digest_date)
    ai_limit = args.ai_limit if args.ai_limit is not None else config.ai.max_articles_per_run
    max_batches = args.ai_batches if args.ai_batches is not None else config.ai.max_batches_per_run

    build_dir = DEFAULT_BUILD_DIR
    build_dir.mkdir(parents=True, exist_ok=True)
    digest_slug = f"last-{args.hours}h" if args.hours is not None else digest_date
    digest_output = Path(args.output) if args.output else build_dir / f"digest-{digest_slug}.md"
    bulletins_output = build_dir / f"bulletins-{digest_slug}.md"
    site_output = build_dir / "site" / "index.html"

    inserted = 0
    skipped = 0
    with connect(Path(args.db)) as conn:
        if not args.skip_fetch:
            for source in config.sources:
                if not source.enabled or source.type != "rss":
                    continue

                source_id = upsert_source(
                    conn,
                    name=source.name,
                    source_type=source.type,
                    url=source.url,
                    priority=source.priority,
                    language=source.language,
                    enabled=source.enabled,
                )
                try:
                    articles = fetch_rss(source.name, source.priority, source.url)
                except Exception as exc:
                    print(f"[fetch] {source.name} failed: {exc}")
                    continue

                for article in articles:
                    if insert_article(conn, source_id, article):
                        inserted += 1
                    else:
                        skipped += 1
                print(f"[fetch] {source.name}: {len(articles)} items")

        aggregate = {
            "processed": 0,
            "duplicates": 0,
            "filtered": 0,
            "ai_enriched": 0,
            "topics": 0,
            "batches": 0,
            "pending_ai": 0,
        }
        if not config.ai.enabled or not config.ai.api_key or max_batches <= 1:
            result = process_articles(
                conn,
                ai_config=config.ai,
                ai_limit=ai_limit,
                refresh_ai=args.refresh_ai,
            )
            aggregate.update(result)
            aggregate["batches"] = 1
            aggregate["pending_ai"] = count_pending_ai_articles(conn, refresh_ai=args.refresh_ai)
        else:
            for batch_no in range(1, max_batches + 1):
                pending_before = count_pending_ai_articles(conn, refresh_ai=args.refresh_ai)
                if pending_before <= 0:
                    break

                result = process_articles(
                    conn,
                    ai_config=config.ai,
                    ai_limit=ai_limit,
                    refresh_ai=args.refresh_ai,
                )
                aggregate["processed"] += result["processed"]
                aggregate["duplicates"] += result["duplicates"]
                aggregate["filtered"] += result["filtered"]
                aggregate["ai_enriched"] += result["ai_enriched"]
                aggregate["topics"] = result["topics"]
                aggregate["batches"] = batch_no
                aggregate["pending_ai"] = count_pending_ai_articles(conn, refresh_ai=args.refresh_ai)
                print(
                    f"[process] batch {batch_no}: "
                    f"ai_enriched={result['ai_enriched']}, "
                    f"pending_ai={aggregate['pending_ai']}"
                )
                if result["ai_enriched"] <= 0:
                    break

        digest_key = digest_slug
        _, digest_content = build_digest(
            conn,
            digest_date=digest_key,
            channel_name=config.channel_profile.name,
            max_items=config.channel_profile.max_digest_items,
            since_iso=since_iso,
            window_label=window_label,
        )
        digest_output.write_text(digest_content, encoding="utf-8")

        _, bulletins_content = build_bulletins(
            conn,
            bulletin_date=digest_key,
            limit=args.limit,
            since_iso=since_iso,
            window_label=window_label,
        )
        bulletins_output.write_text(bulletins_content, encoding="utf-8")

        _, home_html, archive_pages = build_site(
            conn,
            site_date=digest_date,
            channel_name=config.channel_profile.name,
            max_items=config.channel_profile.max_digest_items,
        )
        site_output = write_site(home_html, archive_pages)

    print(f"Run complete: inserted={inserted}, skipped={skipped}")
    print(
        "Process complete: "
        f"processed={aggregate['processed']}, "
        f"duplicates={aggregate['duplicates']}, "
        f"filtered={aggregate['filtered']}, "
        f"ai_enriched={aggregate['ai_enriched']}, "
        f"topics={aggregate['topics']}, "
        f"batches={aggregate['batches']}, "
        f"pending_ai={aggregate['pending_ai']}"
    )
    print(f"Digest written to: {digest_output}")
    print(f"Bulletins written to: {bulletins_output}")
    print(f"Site written to: {site_output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Game news channel MVP CLI")
    parser.set_defaults(func=None)
    parser.add_argument("--hours", type=int)
    parser.add_argument("--date")
    parser.add_argument("--output")
    parser.add_argument("--ai-limit", type=int)
    parser.add_argument("--ai-batches", type=int)
    parser.add_argument("--refresh-ai", action="store_true")
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    common.add_argument("--db", default=str(DEFAULT_DB_PATH))

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", parents=[common])
    run_parser.add_argument("--hours", type=int, default=24)
    run_parser.add_argument("--date")
    run_parser.add_argument("--output")
    run_parser.add_argument("--ai-limit", type=int)
    run_parser.add_argument("--ai-batches", type=int)
    run_parser.add_argument("--refresh-ai", action="store_true")
    run_parser.add_argument("--skip-fetch", action="store_true")
    run_parser.add_argument("--limit", type=int, default=5)
    run_parser.set_defaults(func=cmd_run)

    init_db_parser = subparsers.add_parser("init-db", parents=[common])
    init_db_parser.set_defaults(func=cmd_init_db)

    fetch_parser = subparsers.add_parser("fetch", parents=[common])
    fetch_parser.set_defaults(func=cmd_fetch)

    process_parser = subparsers.add_parser("process", parents=[common])
    process_parser.add_argument("--ai-limit", type=int)
    process_parser.add_argument("--ai-batches", type=int)
    process_parser.add_argument("--refresh-ai", action="store_true")
    process_parser.set_defaults(func=cmd_process)

    digest_parser = subparsers.add_parser("digest", parents=[common])
    digest_parser.add_argument("--date")
    digest_parser.set_defaults(func=cmd_digest)

    publish_parser = subparsers.add_parser("publish", parents=[common])
    publish_parser.add_argument("--date")
    publish_parser.add_argument("--target", default="console", choices=["console", "file"])
    publish_parser.add_argument("--output")
    publish_parser.set_defaults(func=cmd_publish)

    bulletins_parser = subparsers.add_parser("bulletins", parents=[common])
    bulletins_parser.add_argument("--date")
    bulletins_parser.add_argument("--hours", type=int)
    bulletins_parser.add_argument("--limit", type=int, default=5)
    bulletins_parser.add_argument("--output")
    bulletins_parser.set_defaults(func=cmd_bulletins)

    player_buzz_parser = subparsers.add_parser("player-buzz", parents=[common])
    player_buzz_parser.add_argument("--date")
    player_buzz_parser.add_argument("--hours", type=int)
    player_buzz_parser.add_argument("--limit", type=int, default=10)
    player_buzz_parser.add_argument("--output")
    player_buzz_parser.set_defaults(func=cmd_player_buzz)

    site_parser = subparsers.add_parser("site", parents=[common])
    site_parser.add_argument("--date")
    site_parser.add_argument("--output-dir")
    site_parser.set_defaults(func=cmd_site)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.func is None:
        if args.hours is not None:
            return cmd_run(args)
        parser.print_help()
        return 1
    return args.func(args)
