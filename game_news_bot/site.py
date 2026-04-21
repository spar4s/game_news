from __future__ import annotations

from html import escape
from pathlib import Path
import re

from game_news_bot.config import DEFAULT_BUILD_DIR
from game_news_bot.digest import SECTION_ORDER
from game_news_bot.utils import clean_html, to_channel_intro


def build_site(conn, site_date: str, channel_name: str, max_items: int = 12) -> tuple[str, str, dict[str, str]]:
    topics = conn.execute(
        """
        SELECT
            t.title,
            t.category,
            t.summary,
            t.why_it_matters,
            t.context_note,
            t.importance_score,
            t.article_count,
            t.is_breaking,
            a.url,
            s.name AS source_name
        FROM topics t
        LEFT JOIN articles a ON a.id = t.representative_article_id
        LEFT JOIN sources s ON s.id = a.source_id
        ORDER BY t.importance_score DESC, COALESCE(t.last_seen_at, t.first_seen_at) DESC
        LIMIT ?
        """,
        (max_items,),
    ).fetchall()

    archive_rows = conn.execute(
        """
        SELECT digest_date, title, content, generated_at
        FROM digests
        ORDER BY digest_date DESC
        LIMIT 30
        """
    ).fetchall()

    source_rows = conn.execute(
        """
        SELECT s.name AS source_name, COUNT(*) AS article_count, MAX(a.importance_score) AS max_score
        FROM articles a
        JOIN sources s ON s.id = a.source_id
        WHERE a.is_duplicate = 0 AND a.status = 'ready'
        GROUP BY s.id, s.name
        ORDER BY article_count DESC, max_score DESC, s.name ASC
        LIMIT 8
        """
    ).fetchall()

    sections: dict[str, list] = {}
    if topics:
        bulletins = [row for row in topics if row["is_breaking"]][:6]
        lead = topics[:4]
        for row in topics:
            category = row["category"] or "其他"
            section_name = SECTION_ORDER.get(category, "其他资讯")
            sections.setdefault(section_name, []).append(row)
    else:
        fallback_digest = archive_rows[0] if archive_rows else None
        if fallback_digest:
            topics, sections, lead, bulletins, source_rows = _build_site_fallback(fallback_digest["content"], max_items)
        else:
            lead = []
            bulletins = []

    homepage = _render_homepage(
        channel_name=channel_name,
        site_date=site_date,
        topics=topics,
        bulletins=bulletins,
        lead=lead,
        sections=sections,
        archive_rows=archive_rows,
        source_rows=source_rows,
    )

    archive_pages = {
        row["digest_date"]: render_archive_page(
            channel_name=channel_name,
            digest_date=row["digest_date"],
            digest_title=row["title"],
            generated_at=row["generated_at"],
            digest_content=row["content"],
        )
        for row in archive_rows
    }
    return f"{channel_name} - {site_date}", homepage, archive_pages


def write_site(home_html: str, archive_pages: dict[str, str], output_dir: Path | None = None) -> Path:
    target_dir = output_dir or (DEFAULT_BUILD_DIR / "site")
    archive_dir = target_dir / "archive"
    target_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    home_path = target_dir / "index.html"
    home_path.write_text(home_html, encoding="utf-8")
    for digest_date, html in archive_pages.items():
        (archive_dir / f"{digest_date}.html").write_text(html, encoding="utf-8")
    return home_path


def render_archive_page(channel_name: str, digest_date: str, digest_title: str, generated_at: str, digest_content: str) -> str:
    sections = _parse_digest_sections(digest_content)
    section_html = "".join(_render_archive_section(name, items) for name, items in sections)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(digest_title)}</title>
  <style>
    :root {{
      --bg: #eff3f8;
      --surface: rgba(255,255,255,0.92);
      --ink: #132238;
      --muted: #65758b;
      --line: rgba(144,163,188,0.24);
      --accent: #1f6feb;
      --shadow: 0 24px 60px rgba(28,52,84,0.10);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; color: var(--ink); font-family: "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background: linear-gradient(180deg, #f7f9fc 0%, var(--bg) 100%); }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .wrap {{ max-width: 1060px; margin: 0 auto; padding: 28px 18px 64px; }}
    .top {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 18px; padding: 14px 18px; background: rgba(255,255,255,0.72); border: 1px solid var(--line); border-radius: 999px; }}
    .hero {{ background: linear-gradient(135deg, #16365f 0%, #285ea8 100%); color: white; border-radius: 28px; padding: 30px; box-shadow: var(--shadow); margin-bottom: 22px; }}
    .hero h1 {{ margin: 8px 0; font-size: clamp(28px, 4vw, 42px); }}
    .hero p {{ margin: 0; color: rgba(255,255,255,0.86); line-height: 1.8; }}
    .section {{ background: var(--surface); border: 1px solid var(--line); border-radius: 24px; padding: 22px; box-shadow: var(--shadow); margin-bottom: 18px; }}
    .section h2 {{ margin: 0 0 14px; }}
    .item {{ padding: 18px; border: 1px solid var(--line); border-radius: 18px; background: #fff; margin-bottom: 12px; }}
    .item:last-child {{ margin-bottom: 0; }}
    .item h3 {{ margin: 0 0 10px; line-height: 1.45; }}
    .item p {{ margin: 0; line-height: 1.8; color: #42546b; }}
    .meta {{ margin-top: 12px; color: var(--muted); font-size: 13px; }}
    .context {{ margin-top: 12px; padding: 10px 12px; border-radius: 12px; background: #f7faff; border: 1px solid rgba(31,111,235,0.14); color: #48627f; line-height: 1.75; font-size: 14px; }}
    .why {{ margin-top: 12px; color: #1f6feb; font-weight: 700; font-size: 14px; line-height: 1.7; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <strong>{escape(channel_name)}</strong>
      <a href="../index.html">返回首页</a>
    </div>
    <section class="hero">
      <div>Daily Archive</div>
      <h1>{escape(digest_date)}</h1>
      <p>归档标题：{escape(digest_title)}<br>生成时间：{escape(generated_at)}</p>
    </section>
    {section_html}
  </div>
</body>
</html>
"""


def _render_homepage(channel_name: str, site_date: str, topics: list, bulletins: list, lead: list, sections: dict[str, list], archive_rows: list, source_rows: list) -> str:
    stats = {
        "topic_count": len(topics),
        "breaking_count": len(bulletins),
        "high_heat_count": len([row for row in topics if int(row["importance_score"] or 0) >= 90]),
        "source_count": len({str(row["source_name"]) for row in topics if row["source_name"]}),
    }
    filter_buttons = "".join(
        f'<button class="filter-chip" data-filter="{escape(name)}">{escape(name)}</button>'
        for name in SECTION_ORDER.values()
        if sections.get(name)
    )
    section_nav = "".join(
        f'<a href="#{_slugify(name)}">{escape(name)}</a>'
        for name in SECTION_ORDER.values()
        if sections.get(name)
    )
    radar_cards = "".join(_render_radar_card(row) for row in lead[:3])
    archive_list = "".join(_render_archive_item(row) for row in archive_rows) or "<li>还没有历史归档。</li>"
    source_list = "".join(_render_source_item(row) for row in source_rows) or "<li>还没有来源数据。</li>"
    section_blocks = "".join(
        _render_section(section_name, sections.get(section_name, []))
        for section_name in SECTION_ORDER.values()
        if sections.get(section_name)
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(channel_name)} - {escape(site_date)}</title>
  <style>
    :root {{
      --bg: #eef3f9;
      --surface: rgba(255,255,255,0.92);
      --ink: #15253b;
      --muted: #6d7c90;
      --line: rgba(138,160,187,0.24);
      --accent: #1f6feb;
      --accent-deep: #16365f;
      --accent-soft: #edf5ff;
      --chip: #eef3fb;
      --green: #e6fff1;
      --green-line: rgba(58,188,119,0.26);
      --shadow: 0 24px 60px rgba(25,52,88,0.10);
      --radius-xl: 30px;
      --radius-lg: 22px;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; color: var(--ink); font-family: "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background: linear-gradient(180deg, #f8fbff 0%, #eef3f9 100%); }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .wrap {{ max-width: 1360px; margin: 0 auto; padding: 22px 18px 72px; }}
    .topbar {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 18px; padding: 12px 16px; border: 1px solid var(--line); border-radius: 18px; background: rgba(255,255,255,0.72); backdrop-filter: blur(12px); position: sticky; top: 10px; z-index: 20; }}
    .brand {{ display: flex; align-items: center; gap: 12px; font-weight: 800; letter-spacing: 0.02em; }}
    .brand-badge {{ width: 38px; height: 38px; border-radius: 12px; display: grid; place-items: center; color: #fff; font-weight: 800; background: linear-gradient(135deg, #0f2542 0%, #2a5fa8 100%); }}
    .nav {{ display: flex; flex-wrap: wrap; gap: 14px; font-size: 14px; }}
    .hero {{ border-radius: var(--radius-xl); padding: 34px; color: white; background: linear-gradient(135deg, #16365f 0%, #285ea8 100%); box-shadow: var(--shadow); }}
    .eyebrow {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.16em; opacity: 0.8; }}
    h1 {{ margin: 10px 0 12px; font-size: clamp(34px, 5vw, 58px); line-height: 1.04; }}
    .hero-copy {{ max-width: 760px; line-height: 1.82; color: rgba(255,255,255,0.88); font-size: 16px; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-top: 22px; }}
    .stat {{ background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.18); border-radius: 18px; padding: 16px; }}
    .stat strong {{ display: block; font-size: 28px; margin-bottom: 6px; }}
    .radar {{ margin-top: 18px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }}
    .radar-card {{ padding: 16px; border-radius: 18px; background: rgba(255,255,255,0.13); border: 1px solid rgba(255,255,255,0.16); }}
    .radar-card strong {{ display: inline-flex; padding: 6px 10px; border-radius: 999px; background: rgba(255,255,255,0.16); font-size: 12px; margin-bottom: 10px; }}
    .radar-card h3 {{ margin: 0 0 8px; font-size: 18px; line-height: 1.38; }}
    .radar-card p {{ margin: 0; line-height: 1.7; color: rgba(255,255,255,0.88); font-size: 14px; }}
    .layout {{ display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 22px; margin-top: 24px; align-items: start; }}
    .sidebar {{ position: sticky; top: 84px; display: grid; gap: 18px; }}
    .panel, .section-card, .hero-card, .story, .bulletin-card {{ background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-lg); padding: 20px; box-shadow: var(--shadow); }}
    .section-card {{ border-radius: var(--radius-xl); padding: 22px; }}
    .search {{ width: 100%; border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; font-size: 14px; background: #fff; }}
    .chip-group {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    .filter-chip {{ border: 0; cursor: pointer; padding: 8px 12px; border-radius: 999px; background: var(--chip); color: #4f637f; font-size: 13px; }}
    .filter-chip.active {{ background: var(--accent); color: white; }}
    .archive-list, .source-list {{ display: grid; gap: 10px; padding: 0; margin: 0; list-style: none; }}
    .archive-item, .source-item {{ padding: 12px 14px; border-radius: 14px; background: rgba(255,255,255,0.78); border: 1px solid rgba(138,160,187,0.18); }}
    .archive-item strong, .source-item strong {{ display: block; margin-bottom: 6px; font-size: 14px; }}
    .archive-item span, .source-item span {{ color: var(--muted); font-size: 13px; }}
    .lead-grid, .bulletin-grid, .section-list, .content-stack {{ display: grid; gap: 16px; }}
    .hero-card, .story, .bulletin-card {{ position: relative; overflow: hidden; padding: 18px 18px 16px; transition: transform 180ms ease, box-shadow 180ms ease, border-color 180ms ease; }}
    .hero-card:hover, .story:hover, .bulletin-card:hover {{ transform: translateY(-2px); border-color: rgba(31,111,235,0.26); box-shadow: 0 28px 68px rgba(25,52,88,0.14); }}
    .card-topline {{ height: 4px; margin: -18px -18px 14px; background: linear-gradient(90deg, var(--card-accent, #1f6feb), transparent 90%); }}
    .pick-badge {{ position: absolute; top: -1px; left: 14px; display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 0 0 12px 12px; background: linear-gradient(135deg, #ffb24a 0%, #ff8b2b 100%); color: #fff; font-size: 12px; font-weight: 700; }}
    .news-card {{ display: grid; grid-template-columns: 54px minmax(0, 1fr); gap: 16px; align-items: start; margin-top: 8px; }}
    .news-avatar {{ width: 54px; height: 54px; border-radius: 16px; display: grid; place-items: center; background: var(--avatar-bg, linear-gradient(145deg, #0e1726 0%, #29354d 100%)); color: var(--avatar-fg, #fff); font-weight: 800; font-size: 20px; }}
    .news-main {{ min-width: 0; }}
    .news-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }}
    .news-title {{ margin: 0; line-height: 1.42; font-size: 18px; font-weight: 800; color: #203a63; }}
    .news-title a {{ color: inherit; }}
    .score-pill {{ flex-shrink: 0; display: inline-flex; align-items: center; padding: 7px 10px; border-radius: 12px; border: 1px solid rgba(255, 172, 73, 0.5); background: linear-gradient(180deg, rgba(255, 251, 236, 0.92), rgba(255, 239, 199, 0.88)); color: #b56a0f; font-size: 13px; font-weight: 700; }}
    .news-submeta {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; color: var(--muted); font-size: 13px; }}
    .news-summary {{ margin: 14px 0 0; line-height: 1.84; color: #4b596e; font-size: 15px; }}
    .context {{ margin-top: 12px; padding: 10px 12px; border-radius: 12px; background: #f7faff; border: 1px solid rgba(31,111,235,0.14); color: #48627f; font-size: 14px; line-height: 1.75; }}
    .why {{ margin-top: 12px; color: var(--accent-deep); font-size: 14px; font-weight: 700; line-height: 1.7; }}
    .tag-row {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(138,160,187,0.18); }}
    .tag {{ display: inline-flex; align-items: center; padding: 6px 11px; border-radius: 10px; border: 1px solid rgba(126,147,176,0.22); background: #f8fbff; color: #5f7492; font-size: 12px; }}
    .tag.source {{ background: var(--accent-soft); border-color: rgba(31,111,235,0.16); color: #35619a; }}
    .tag.highlight {{ background: var(--green); border-color: var(--green-line); color: #14935f; font-weight: 700; }}
    .meta {{ margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(138,160,187,0.18); font-size: 13px; color: var(--muted); }}
    .hidden {{ display: none !important; }}
    .footer {{ margin-top: 24px; text-align: center; color: var(--muted); font-size: 13px; }}
    @media (max-width: 1040px) {{ .layout {{ grid-template-columns: 1fr; }} .sidebar {{ position: static; }} .radar {{ grid-template-columns: 1fr; }} .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
    @media (max-width: 700px) {{ .wrap {{ padding: 16px 12px 56px; }} .hero {{ padding: 24px 20px; }} .stats {{ grid-template-columns: 1fr; }} .news-card {{ grid-template-columns: 1fr; }} .news-head {{ flex-direction: column; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <div class="brand"><span class="brand-badge">GN</span><span>{escape(channel_name)}</span></div>
      <nav class="nav"><a href="#lead">导读</a><a href="#bulletins">快讯</a>{section_nav}</nav>
    </div>
    <section class="hero">
      <div class="eyebrow">Game News Desk</div>
      <h1>{escape(channel_name)}</h1>
      <div class="hero-copy">{escape(site_date)} 的游戏资讯首页。这里会优先展示聚类后的热点；如果当天聚类为空，则自动回退到最新日报内容，确保首页不会空白。</div>
      <div class="stats">
        <div class="stat"><strong>{stats['topic_count']}</strong><span>今日话题</span></div>
        <div class="stat"><strong>{stats['breaking_count']}</strong><span>快讯候选</span></div>
        <div class="stat"><strong>{stats['high_heat_count']}</strong><span>高热事件</span></div>
        <div class="stat"><strong>{stats['source_count']}</strong><span>活跃来源</span></div>
      </div>
      <div class="radar">{radar_cards}</div>
    </section>
    <div class="layout">
      <aside class="sidebar">
        <section class="panel">
          <h2>站内筛选</h2>
          <input id="searchInput" class="search" type="search" placeholder="搜索游戏名、事件、来源">
          <div class="chip-group"><button class="filter-chip active" data-filter="all">全部</button>{filter_buttons}</div>
        </section>
        <section class="panel"><h3>历史归档</h3><ul class="archive-list">{archive_list}</ul></section>
        <section class="panel"><h3>来源榜单</h3><ul class="source-list">{source_list}</ul></section>
      </aside>
      <main class="content-stack">
        <section id="lead" class="section-card" data-section="导读">
          <h2>今日导读</h2>
          <div class="lead-grid">{''.join(_render_lead_item(row) for row in lead) or '<article class="hero-card"><p>今天还没有导读内容。</p></article>'}</div>
        </section>
        <section id="bulletins" class="section-card" data-section="快讯">
          <h2>热点快讯</h2>
          <div class="bulletin-grid">{''.join(_render_bulletin_item(row) for row in bulletins) or '<article class="bulletin-card"><p>今天还没有达到快讯阈值的热点。</p></article>'}</div>
        </section>
        {section_blocks}
      </main>
    </div>
    <div class="footer">由本地 Game News Bot 生成 · 可直接部署到 GitHub Pages / Vercel</div>
  </div>
  <script>
    const chips = Array.from(document.querySelectorAll('.filter-chip'));
    const searchInput = document.getElementById('searchInput');
    const sections = Array.from(document.querySelectorAll('.section-card'));
    const cards = Array.from(document.querySelectorAll('[data-card]'));
    function applyFilters() {{
      const activeChip = document.querySelector('.filter-chip.active');
      const filter = activeChip ? activeChip.dataset.filter : 'all';
      const query = (searchInput.value || '').trim().toLowerCase();
      cards.forEach((card) => {{
        const section = card.dataset.section || '';
        const search = (card.dataset.search || '').toLowerCase();
        const sectionMatch = filter === 'all' || section === filter;
        const textMatch = !query || search.includes(query);
        card.classList.toggle('hidden', !(sectionMatch && textMatch));
      }});
      sections.forEach((section) => {{
        const visible = section.querySelector('[data-card]:not(.hidden)');
        if (section.id === 'lead' || section.id === 'bulletins') {{
          section.classList.toggle('hidden', filter !== 'all' && section.dataset.section !== filter && !visible);
        }} else {{
          section.classList.toggle('hidden', !visible);
        }}
      }});
    }}
    chips.forEach((chip) => chip.addEventListener('click', () => {{
      chips.forEach((item) => item.classList.remove('active'));
      chip.classList.add('active');
      applyFilters();
    }}));
    searchInput.addEventListener('input', applyFilters);
    applyFilters();
  </script>
</body>
</html>
"""


def _render_radar_card(row) -> str:
    summary = clean_html(str(_row_value(row, "summary", "")), max_length=92) or "等待后续补充摘要。"
    return f'<article class="radar-card"><strong>{escape(to_channel_intro(str(_row_value(row, "category", "其他"))))}</strong><h3>{escape(str(_row_value(row, "title", "")))}</h3><p>{escape(summary)}</p></article>'


def _render_archive_item(row) -> str:
    link = f"archive/{row['digest_date']}.html"
    return f'<li class="archive-item"><strong><a href="{escape(link)}">{escape(row["digest_date"])}</a></strong><span>{escape(row["title"])}</span></li>'


def _render_source_item(row) -> str:
    return f'<li class="source-item"><strong>{escape(str(row["source_name"]))}</strong><span>收录 {row["article_count"]} 条 · 最高热度 {row["max_score"]}</span></li>'


def _render_lead_item(row) -> str:
    section_name = SECTION_ORDER.get(str(_row_value(row, "category", "其他")), "其他资讯")
    return _render_news_card("hero-card", section_name, row, "精选")


def _render_bulletin_item(row) -> str:
    section_name = SECTION_ORDER.get(str(_row_value(row, "category", "其他")), "其他资讯")
    badge = "快讯" if _row_value(row, "is_breaking", False) else "精选"
    return _render_news_card("bulletin-card", section_name, row, badge)


def _render_section(section_name: str, rows: list) -> str:
    stories = "".join(_render_story(section_name, row) for row in rows)
    return f'<section id="{_slugify(section_name)}" class="section-card" data-section="{escape(section_name)}"><h2>{escape(section_name)}</h2><div class="section-list">{stories}</div></section>'


def _render_story(section_name: str, row) -> str:
    return _render_news_card("story", section_name, row, "精选")


def _render_news_card(card_class: str, section_name: str, row, badge_label: str) -> str:
    summary = clean_html(str(_row_value(row, "summary", "")), max_length=170) or "等待后续补充摘要。"
    context_note = _row_value(row, "context_note", "")
    why_text = _row_value(row, "why_it_matters", "")
    context = f'<div class="context">{escape(str(context_note))}</div>' if context_note else ""
    why = f'<div class="why">看点：{escape(str(why_text))}</div>' if why_text else ""
    source_name = str(_row_value(row, "source_name", ""))
    theme = _source_theme(source_name)
    avatar = _avatar_text(source_name or str(_row_value(row, "title", "G")))
    tags = _render_tags(row)
    return f"""
    <article class="{card_class}" data-card data-section="{escape(section_name)}" data-search="{escape(_search_text(row))}" style="--card-accent:{theme['accent']}; --avatar-bg:{theme['avatar_bg']}; --avatar-fg:{theme['avatar_fg']};">
      <div class="pick-badge">✦ {escape(badge_label)}</div>
      <div class="card-topline"></div>
      <div class="news-card">
        <div class="news-avatar">{escape(avatar)}</div>
        <div class="news-main">
          <div class="news-head">
            <h3 class="news-title"><a href="{escape(str(_row_value(row, 'url', '#')))}" target="_blank" rel="noreferrer">{escape(str(_row_value(row, 'title', '')))}</a></h3>
            <span class="score-pill">热度 {int(_row_value(row, 'importance_score', 0) or 0)}</span>
          </div>
          <div class="news-submeta">
            <span>{escape(source_name or '未知来源')}</span>
            <span>相关报道 {int(_row_value(row, 'article_count', 0) or 0)}</span>
            <span>{escape(to_channel_intro(str(_row_value(row, 'category', '其他'))))}</span>
          </div>
          <p class="news-summary">{escape(summary)}</p>
          {context}
          {why}
          <div class="tag-row">{tags}</div>
          <div class="meta">来源 {escape(source_name or '未知来源')} · 栏目 {escape(section_name)}</div>
        </div>
      </div>
    </article>
    """


def _render_tags(row) -> str:
    tags: list[str] = []
    category = to_channel_intro(str(_row_value(row, "category", "其他")))
    source = str(_row_value(row, "source_name", ""))
    topic = str(_row_value(row, "title", ""))
    if category:
        tags.append(f'<span class="tag">{escape(category)}</span>')
    if source:
        tags.append(f'<span class="tag source">{escape(source)}</span>')
    keyword = _title_keyword(topic)
    if keyword:
        tags.append(f'<span class="tag">{escape(keyword)}</span>')
    tags.append('<span class="tag highlight">中文简报</span>')
    return "".join(tags[:4])


def _title_keyword(title: str) -> str:
    parts = re.split(r"[:：|｜\-—]", title)
    for part in parts:
        candidate = part.strip()
        if 2 <= len(candidate) <= 22:
            return candidate
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9 '.:&]{1,20}", title)
    return words[0].strip() if words else ""


def _avatar_text(text: str) -> str:
    letters = re.findall(r"[A-Za-z0-9]", text)
    if letters:
        return "".join(letters[:2]).upper()
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    if chinese:
        return chinese[0]
    return "G"


def _source_theme(source_name: str) -> dict[str, str]:
    lower = source_name.lower()
    if "playstation" in lower or "/r/ps5" in lower:
        return {"accent": "#3b82f6", "avatar_bg": "linear-gradient(145deg, #0b2346 0%, #2e6fdd 100%)", "avatar_fg": "#ffffff"}
    if "xbox" in lower:
        return {"accent": "#189b52", "avatar_bg": "linear-gradient(145deg, #103221 0%, #2db36c 100%)", "avatar_fg": "#ffffff"}
    if "ign" in lower:
        return {"accent": "#d83b3b", "avatar_bg": "linear-gradient(145deg, #491515 0%, #d83b3b 100%)", "avatar_fg": "#ffffff"}
    if "gamespot" in lower:
        return {"accent": "#f59e0b", "avatar_bg": "linear-gradient(145deg, #4c2c08 0%, #f59e0b 100%)", "avatar_fg": "#ffffff"}
    if "reddit" in lower:
        return {"accent": "#ff6b35", "avatar_bg": "linear-gradient(145deg, #5f2410 0%, #ff6b35 100%)", "avatar_fg": "#ffffff"}
    if "rock paper shotgun" in lower:
        return {"accent": "#8b5cf6", "avatar_bg": "linear-gradient(145deg, #24153f 0%, #8b5cf6 100%)", "avatar_fg": "#ffffff"}
    return {"accent": "#1f6feb", "avatar_bg": "linear-gradient(145deg, #0e1726 0%, #29354d 100%)", "avatar_fg": "#ffffff"}


def _build_site_fallback(digest_content: str, max_items: int) -> tuple[list[dict], dict[str, list], list[dict], list[dict], list[dict]]:
    section_to_category = {value: key for key, value in SECTION_ORDER.items()}
    parsed_sections = _parse_digest_sections(digest_content)
    rows: list[dict] = []
    sections: dict[str, list] = {}
    source_stats: dict[str, dict] = {}
    for section_name, items in parsed_sections:
        section_rows: list[dict] = []
        for item in items:
            source_name = _extract_source_name(item.get("来源", ""))
            row = {
                "title": item.get("title", "未命名条目"),
                "category": section_to_category.get(section_name, "其他"),
                "summary": item.get("摘要", ""),
                "why_it_matters": item.get("看点", ""),
                "context_note": item.get("前情提要", ""),
                "importance_score": 80,
                "article_count": 1,
                "is_breaking": section_name in {"今日重点", "热点快讯"},
                "url": item.get("链接", ""),
                "source_name": source_name,
            }
            section_rows.append(row)
            rows.append(row)
            if source_name:
                stat = source_stats.setdefault(source_name, {"source_name": source_name, "article_count": 0, "max_score": 0})
                stat["article_count"] += 1
                stat["max_score"] = max(stat["max_score"], row["importance_score"])
        if section_rows:
            sections[section_name] = section_rows[:max_items]
    rows = rows[:max_items]
    lead = sections.get("今日导读", [])[:4] or rows[:4]
    bulletins = sections.get("今日重点", [])[:6]
    source_rows = sorted(source_stats.values(), key=lambda item: (-int(item["article_count"]), str(item["source_name"])))[:8]
    return rows, sections, lead, bulletins, source_rows


def _extract_source_name(source_text: str) -> str:
    if not source_text:
        return ""
    return source_text.split("|", 1)[0].strip()


def _parse_digest_sections(content: str) -> list[tuple[str, list[dict[str, str]]]]:
    section_map: dict[str, list[dict[str, str]]] = {}
    current_section = ""
    current_item: dict[str, str] | None = None
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith("# "):
            continue
        if line.startswith("## "):
            current_section = line[3:].strip()
            section_map.setdefault(current_section, [])
            continue
        if line.startswith("- **") and line.endswith("**"):
            current_item = {"title": line[4:-2].strip()}
            section_map.setdefault(current_section or "未分类", []).append(current_item)
            continue
        if line.startswith("- "):
            current_item = {"title": line[2:].strip()}
            section_map.setdefault(current_section or "未分类", []).append(current_item)
            continue
        if current_item is None:
            continue
        stripped = line.strip()
        if "：" in stripped:
            key, value = stripped.split("：", 1)
            current_item[key] = value.strip()
    return list(section_map.items())


def _render_archive_section(section_name: str, items: list[dict[str, str]]) -> str:
    stories = "".join(_render_archive_item_card(item) for item in items)
    return f'<section class="section"><h2>{escape(section_name)}</h2>{stories}</section>'


def _render_archive_item_card(item: dict[str, str]) -> str:
    title = item.get("title", "未命名条目")
    summary = item.get("摘要", "")
    context = item.get("前情提要", "")
    why = item.get("看点", "")
    source = item.get("来源", "")
    link = item.get("链接", "")
    summary_html = f"<p>{escape(summary)}</p>" if summary else ""
    context_html = f'<div class="context">{escape(context)}</div>' if context else ""
    why_html = f'<div class="why">看点：{escape(why)}</div>' if why else ""
    meta_html = f'<div class="meta">{escape(source)}</div>' if source else ""
    link_html = f'<div class="meta"><a href="{escape(link)}" target="_blank" rel="noreferrer">查看原文</a></div>' if link else ""
    return f'<article class="item"><h3>{escape(title)}</h3>{summary_html}{context_html}{why_html}{meta_html}{link_html}</article>'


def _search_text(row) -> str:
    return " ".join([
        str(_row_value(row, "title", "")),
        str(_row_value(row, "category", "")),
        str(_row_value(row, "summary", "")),
        str(_row_value(row, "source_name", "")),
        str(_row_value(row, "why_it_matters", "")),
    ])


def _row_value(row, key: str, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _slugify(text: str) -> str:
    slug = re.sub(r"\s+", "-", text.strip().lower())
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff\-]", "", slug)
    return slug or "section"
