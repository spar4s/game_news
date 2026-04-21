from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from game_news_bot.config import DEFAULT_BUILD_DIR


def publish_digest(conn, digest_date: str, target: str, output: Path | None = None) -> Path | None:
    row = conn.execute(
        "SELECT id, title, content FROM digests WHERE digest_date = ?",
        (digest_date,),
    ).fetchone()
    if row is None:
        raise ValueError(f"No digest found for {digest_date}")

    rendered_path: Path | None = None
    if target == "console":
        print(row["content"])
    elif target == "file":
        build_dir = DEFAULT_BUILD_DIR
        build_dir.mkdir(parents=True, exist_ok=True)
        rendered_path = output or build_dir / f"digest-{digest_date}.md"
        rendered_path.write_text(row["content"], encoding="utf-8")
    else:
        raise ValueError(f"Unsupported publish target: {target}")

    conn.execute(
        """
        INSERT INTO deliveries (digest_id, target, status, delivered_at, output_path)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            row["id"],
            target,
            "sent",
            datetime.now(UTC).replace(microsecond=0).isoformat(),
            str(rendered_path) if rendered_path else None,
        ),
    )
    return rendered_path
