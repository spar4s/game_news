from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import UTC, datetime


CATEGORY_NEW = "新作公布"
CATEGORY_RELEASE = "发售日期"
CATEGORY_UPDATE = "更新补丁"
CATEGORY_DLC = "DLC扩展"
CATEGORY_INDUSTRY = "行业动态"
CATEGORY_PLATFORM = "平台动态"
CATEGORY_COMMUNITY = "社区热点"
CATEGORY_RUMOR = "传闻爆料"
CATEGORY_OTHER = "其他"


CATEGORY_LABELS = [
    CATEGORY_NEW,
    CATEGORY_RELEASE,
    CATEGORY_UPDATE,
    CATEGORY_DLC,
    CATEGORY_INDUSTRY,
    CATEGORY_PLATFORM,
    CATEGORY_COMMUNITY,
    CATEGORY_RUMOR,
    CATEGORY_OTHER,
]


SECTION_TITLES = {
    CATEGORY_NEW: "今日重点",
    CATEGORY_RELEASE: "发售与上线",
    CATEGORY_UPDATE: "更新情报",
    CATEGORY_DLC: "更新情报",
    CATEGORY_PLATFORM: "平台与订阅",
    CATEGORY_INDUSTRY: "行业动态",
    CATEGORY_COMMUNITY: "社区与话题",
    CATEGORY_RUMOR: "传闻与爆料",
    CATEGORY_OTHER: "其他资讯",
}


CHANNEL_INTROS = {
    CATEGORY_NEW: "新作动态",
    CATEGORY_RELEASE: "上线情报",
    CATEGORY_UPDATE: "版本更新",
    CATEGORY_DLC: "扩展内容",
    CATEGORY_PLATFORM: "平台动态",
    CATEGORY_INDUSTRY: "行业观察",
    CATEGORY_COMMUNITY: "社区热点",
    CATEGORY_RUMOR: "传闻追踪",
    CATEGORY_OTHER: "资讯更新",
}


STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "of",
    "to",
    "for",
    "in",
    "on",
    "with",
    "from",
    "at",
    "by",
    "as",
    "is",
    "are",
    "be",
    "new",
    "version",
    "update",
    "patch",
    "launch",
    "launches",
    "revealed",
    "reveal",
    "today",
    "tomorrow",
    "tips",
    "first",
    "look",
    "details",
    "feature",
    "features",
    "story",
    "gameplay",
    "guide",
    "preview",
    "review",
    "week",
    "share",
    "how",
    "what",
    "why",
    "when",
    "where",
}


MONTH_PATTERN = r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}"


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalize_title(title: str) -> str:
    text = title.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff ]+", "", text)
    return text


def article_hash(title: str, url: str) -> str:
    normalized = f"{normalize_title(title)}::{url.strip().lower()}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_importance(
    title: str,
    source_priority: int,
    source_name: str | None = None,
    url: str | None = None,
) -> int:
    title_lower = title.lower()
    score = source_priority * 8
    source_name_lower = (source_name or "").lower()
    url_lower = (url or "").lower()

    keywords = {
        "release date": 18,
        "arrives": 14,
        "coming": 12,
        "launch": 15,
        "announced": 16,
        "revealed": 14,
        "update": 10,
        "version": 10,
        "patch": 10,
        "dlc": 12,
        "shutdown": 20,
        "layoffs": 20,
        "sales": 12,
        "trailer": 8,
        "demo": 9,
        "beta": 9,
        "steam": 5,
        "delayed": 16,
        "delay": 14,
        "available now": 16,
        "out now": 16,
    }
    for keyword, weight in keywords.items():
        if keyword in title_lower:
            score += weight

    if any(name in source_name_lower for name in ["playstation blog", "xbox wire"]):
        score += 6
    elif any(name in source_name_lower for name in ["ign", "gamespot", "gematsu"]):
        score += 4
    elif "reddit" in source_name_lower:
        score -= 10

    if "reddit.com" in url_lower and "/comments/" in url_lower:
        score -= 4

    if "reddit" in source_name_lower:
        if any(
            pattern in title_lower
            for pattern in [
                "what are you playing",
                "what are we all playing",
                "making friends",
                "help me",
                "is it worth it",
                "my setup",
                "rate my",
                "anyone else",
                "should i buy",
                "can i run",
                "look at this",
                "fan art",
                "meme",
            ]
        ):
            score -= 18

    return max(0, min(score, 100))


def clean_html(raw_text: str | None, max_length: int | None = None) -> str:
    if not raw_text:
        return ""

    text = html.unescape(raw_text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    if max_length and len(text) > max_length:
        return text[: max_length - 3].rstrip() + "..."
    return text


def infer_category(title: str, source_name: str | None = None, summary: str | None = None) -> str:
    combined = " ".join(filter(None, [title, summary, source_name])).lower()

    if any(keyword in combined for keyword in ["rumour", "rumor", "leak", "alleged", "reportedly"]):
        return CATEGORY_RUMOR

    if any(keyword in combined for keyword in ["layoffs", "acquired", "acquisition", "sales", "studio", "union", "ceo", "director", "publisher"]):
        return CATEGORY_INDUSTRY

    if any(keyword in combined for keyword in ["announced", "revealed", "reveal", "debut", "first trailer", "announce"]):
        return CATEGORY_NEW

    if any(keyword in combined for keyword in ["release date", "launches", "launch", "available now", "arrives", "coming to", "out now"]):
        return CATEGORY_RELEASE

    if any(keyword in combined for keyword in ["playstation plus", "game pass", "ps5", "xbox", "switch", "steam deck", "subscription", "catalog", "service", "native app"]):
        if any(keyword in combined for keyword in ["launch", "launches", "available now", "arrives", "coming to", "catalog", "service", "subscription", "app"]):
            return CATEGORY_PLATFORM

    if any(keyword in combined for keyword in ["patch", "hotfix", "title update", "season update", "anniversary update"]) or re.search(r"\bversion\s+\d", combined):
        return CATEGORY_UPDATE

    if any(keyword in combined for keyword in ["dlc", "expansion", "add-on", "season pass"]):
        return CATEGORY_DLC

    if "reddit" in (source_name or "").lower():
        return CATEGORY_COMMUNITY

    return CATEGORY_OTHER


def build_why_it_matters(title: str, category: str) -> str:
    if category == CATEGORY_RELEASE:
        return "这类消息最直接影响玩家的预约、入坑和内容排期，适合优先推送。"
    if category == CATEGORY_UPDATE:
        return "涉及版本内容变化，通常会直接影响活跃玩家是否回流。"
    if category == CATEGORY_NEW:
        return "新作公开往往会带来更高讨论度，适合作为频道重点内容。"
    if category == CATEGORY_INDUSTRY:
        return "这类动态会影响厂商和项目后续走向，读者通常会持续关注。"
    if category == CATEGORY_PLATFORM:
        return "平台侧变化往往影响的玩家面更广，传播价值通常更高。"
    if category == CATEGORY_RUMOR:
        return "虽然仍需观察真实性，但这类消息热度通常较高，适合标注后跟进。"
    if category == CATEGORY_COMMUNITY:
        return "如果社区讨论持续升温，它很适合作为观察玩家情绪的补充样本。"
    return "这条消息和近期游戏动态相关，适合放进当天资讯汇总。"


def to_channel_intro(category: str) -> str:
    return CHANNEL_INTROS.get(category, CHANNEL_INTROS[CATEGORY_OTHER])


def is_breaking_topic(
    title: str,
    category: str,
    importance: int,
    article_count: int,
    context_note: str | None,
) -> bool:
    title_lower = title.lower()

    soft_excludes = [
        "next week on xbox",
        "first look",
        "get excited",
        "share of the week",
        "what are we all playing",
        "ui beta",
        "workshop",
        "tips you should know",
        "starter tips",
    ]
    if any(signal in title_lower for signal in soft_excludes):
        return False

    hard_signals = [
        "release date",
        "launches",
        "launch",
        "arrives",
        "announced",
        "revealed",
        "shutdown",
        "layoffs",
        "delayed",
        "delay",
        "available now",
        "out now",
    ]
    hard_hit = any(signal in title_lower for signal in hard_signals)
    if hard_hit and (importance >= 86 or article_count >= 2 or bool(context_note)):
        return True

    if category == CATEGORY_NEW and importance >= 88:
        return True
    if category == CATEGORY_RELEASE and importance >= 85:
        return True
    if category == CATEGORY_UPDATE and (importance >= 90 or article_count >= 2) and (article_count >= 2 or bool(context_note) or importance >= 95):
        return True
    if category == CATEGORY_INDUSTRY and importance >= 82:
        return True
    if category == CATEGORY_DLC and importance >= 88:
        return True
    if category == CATEGORY_PLATFORM and importance >= 90 and article_count >= 2:
        return True
    if category == CATEGORY_OTHER and importance >= 85 and article_count >= 3:
        return True
    if article_count >= 3 and importance >= 75:
        return True
    if context_note and importance >= 88:
        return True
    return False


def is_low_signal_article(title: str, source_name: str | None, url: str | None = None) -> bool:
    title_lower = title.lower().strip()
    source_name_lower = (source_name or "").lower()
    url_lower = (url or "").lower()

    generic_noise = [
        "what are you playing",
        "what are we all playing",
        "making friends",
        "share your",
        "show off",
        "look at my",
        "my setup",
        "rate my",
        "fan art",
        "meme",
        "shitpost",
        "help me decide",
        "which should i buy",
        "should i buy",
        "can i run",
        "anyone else",
        "question about",
        "weekly discussion",
        "daily discussion",
        "free talk",
        "recommend me",
        "recommendation",
        "giveaway",
        "screenshot saturday",
    ]
    if any(pattern in title_lower for pattern in generic_noise):
        return True

    if "reddit" in source_name_lower:
        if title_lower.endswith("?") and not any(
            keyword in title_lower
            for keyword in [
                "release date",
                "announced",
                "revealed",
                "launch",
                "update",
                "patch",
                "shutdown",
                "layoffs",
                "delayed",
                "delay",
            ]
        ):
            return True

        if any(domain in url_lower for domain in ["i.redd.it", "v.redd.it"]):
            return True

    return False


def extract_event_key(title: str) -> str:
    entities = extract_named_entities(title)
    if entities:
        return entities[0]

    text = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff: \-–]+", " ", title)
    tokens = [token for token in re.split(r"\s+", text.strip()) if token]

    phrase_tokens: list[str] = []
    for token in tokens:
        if token.lower() in STOPWORDS:
            continue
        if token[:1].isupper() or any(ch.isdigit() for ch in token) or re.search(r"[\u4e00-\u9fff]", token):
            phrase_tokens.append(token)
        elif phrase_tokens:
            break

    if phrase_tokens:
        return " ".join(phrase_tokens[:5]).strip(":- ").lower()

    normalized = normalize_title(title)
    return " ".join(normalized.split(" ")[:4]).strip()


def extract_named_entities(title: str) -> list[str]:
    text = re.sub(r"[^\w\u4e00-\u9fff: \-–|]+", " ", title)
    pieces = re.split(r"[:\-–|]", text)
    candidates: list[str] = []

    for piece in pieces[:2]:
        words = [word for word in re.split(r"\s+", piece.strip()) if word]
        if not words:
            continue

        current: list[str] = []
        for word in words:
            lower = word.lower()
            is_named = (
                word[:1].isupper()
                or any(ch.isdigit() for ch in word)
                or re.search(r"[\u4e00-\u9fff]", word) is not None
            )
            if is_named and lower not in STOPWORDS:
                current.append(word)
            else:
                if current:
                    candidates.append(" ".join(current))
                current = []
        if current:
            candidates.append(" ".join(current))

    cleaned: list[str] = []
    for candidate in candidates:
        normalized = candidate.strip(" :-").lower()
        if len(normalized) < 4:
            continue
        if normalized in cleaned:
            continue
        cleaned.append(normalized)
    return cleaned[:4]


def extract_topic_terms(title: str) -> set[str]:
    text = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff ]+", " ", title)
    terms: set[str] = set()
    for token in re.split(r"\s+", text.strip()):
        token_lower = token.lower()
        if len(token_lower) < 4:
            continue
        if token_lower in STOPWORDS:
            continue
        if token[:1].isupper() or any(ch.isdigit() for ch in token) or re.search(r"[\u4e00-\u9fff]", token):
            terms.add(token_lower)
    return terms


def serialize_entities(entities: list[str]) -> str:
    return json.dumps(entities, ensure_ascii=False)


def deserialize_entities(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    try:
        data = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in data if str(item).strip()]


def generate_fallback_headline(title: str, category: str) -> str:
    game_name = extract_display_name(title)
    title_stripped = title.strip()

    patterns = [
        (CATEGORY_NEW, r"(.+?)\s+(revealed|announced)(?:\s|$)", "{name}公布新消息"),
        (CATEGORY_RELEASE, r"(.+?)\s+(arrives|launches|available now|out now)(?:\s|$)", "{name}公布上线安排"),
        (CATEGORY_UPDATE, r"(.+?)\s+(update|version|patch)(?:\s|$)", "{name}带来新版本更新"),
        (CATEGORY_DLC, r"(.+?)\s+(dlc|expansion)(?:\s|$)", "{name}公布扩展内容"),
    ]
    for target_category, pattern, template in patterns:
        if category != target_category:
            continue
        match = re.search(pattern, title_stripped, flags=re.IGNORECASE)
        if match:
            raw_name = match.group(1).strip(" -:")
            name = _quote_game_name(raw_name or game_name)
            return template.format(name=name)

    name = _quote_game_name(game_name)
    if category == CATEGORY_PLATFORM:
        return f"{name}迎来平台新动态"
    if category == CATEGORY_INDUSTRY:
        return f"{name}相关行业动态更新"
    if category == CATEGORY_COMMUNITY:
        return f"{name}成为社区热议话题"
    if category == CATEGORY_RUMOR:
        return f"{name}传出新爆料"
    if category == CATEGORY_NEW:
        return f"{name}公开亮相"
    if category == CATEGORY_RELEASE:
        return f"{name}上线信息更新"
    if category == CATEGORY_UPDATE:
        return f"{name}版本内容更新"
    return title_stripped


def generate_fallback_summary(title: str, summary: str | None, source_name: str | None, category: str) -> str:
    clean_summary = clean_html(summary, max_length=180)
    game_name = _quote_game_name(extract_display_name(title))
    source_label = source_name or "来源"
    date_hint = extract_date_hint(title, clean_summary)
    platform_hint = extract_platform_hint(title, clean_summary)

    if category == CATEGORY_NEW:
        sentence = f"{game_name}有了新的公布动态"
        if platform_hint:
            sentence += f"，涉及{platform_hint}"
        return _finish_summary(sentence, clean_summary, source_label)

    if category == CATEGORY_RELEASE:
        sentence = f"{game_name}更新了发售或上线安排"
        if date_hint:
            sentence += f"，时间点指向{date_hint}"
        if platform_hint:
            sentence += f"，相关平台包括{platform_hint}"
        return _finish_summary(sentence, clean_summary, source_label)

    if category == CATEGORY_UPDATE:
        sentence = f"{game_name}带来了版本更新消息"
        if date_hint:
            sentence += f"，更新节点在{date_hint}"
        return _finish_summary(sentence, clean_summary, source_label)

    if category == CATEGORY_DLC:
        sentence = f"{game_name}公开了新的扩展内容"
        return _finish_summary(sentence, clean_summary, source_label)

    if category == CATEGORY_PLATFORM:
        sentence = f"{game_name}出现新的平台动态"
        if platform_hint:
            sentence += f"，重点平台是{platform_hint}"
        return _finish_summary(sentence, clean_summary, source_label)

    if category == CATEGORY_INDUSTRY:
        sentence = f"{game_name}相关的行业动态出现新进展"
        return _finish_summary(sentence, clean_summary, source_label)

    if category == CATEGORY_COMMUNITY:
        sentence = f"{game_name}在社区中出现了新的高热讨论"
        return _finish_summary(sentence, clean_summary, source_label)

    if category == CATEGORY_RUMOR:
        sentence = f"{game_name}相关传闻再次升温"
        return _finish_summary(sentence, clean_summary, source_label)

    return _finish_summary(f"{game_name}出现新的消息更新", clean_summary, source_label)


def build_context_note(current_title: str, prior_titles: list[str], category: str | None = None) -> str | None:
    if not prior_titles:
        return None

    latest = prior_titles[0]
    event_name = _quote_game_name(extract_display_name(current_title))

    if category == CATEGORY_UPDATE:
        return f"前情提要：{event_name}此前已经有过相关更新，这次属于后续补充内容。"
    if category == CATEGORY_RELEASE:
        return f"前情提要：{event_name}此前已有相关上线消息，这次进一步补充了时间或版本信息。"
    if category == CATEGORY_NEW:
        return f"前情提要：{event_name}此前已出现相关曝光或预热，这次是更明确的一次公开进展。"
    if len(prior_titles) == 1:
        return f"前情提要：这条消息并不是第一次出现，上一条相关动态是《{latest}》。"
    return f"前情提要：这已经是该事件近期的连续进展，之前还出现过 {len(prior_titles)} 条相关更新。"


def extract_display_name(title: str) -> str:
    patterns = [
        r"(.+?)\s+(?:revealed|announced|arrives|launches|launch|available now|out now)\b",
        r"(.+?)\s*[:\-–|]",
    ]
    for pattern in patterns:
        match = re.search(pattern, title, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()

    entities = extract_named_entities(title)
    if entities:
        entity = entities[0]
        idx = title.lower().find(entity.lower())
        if idx >= 0:
            return title[idx : idx + len(entity)].strip()
        return entity.strip()

    words = title.split()
    if len(words) >= 4:
        return " ".join(words[:4]).strip()
    return title.strip()


def extract_date_hint(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        match = re.search(MONTH_PATTERN, text, flags=re.IGNORECASE)
        if match:
            return match.group(0)
        match = re.search(r"\b20\d{2}\b", text)
        if match:
            return match.group(0)
    return None


def extract_platform_hint(*texts: str | None) -> str | None:
    combined = " ".join(text for text in texts if text).lower()
    labels = []
    mapping = [
        ("ps5", "PS5"),
        ("playstation 5", "PS5"),
        ("xbox series x", "Xbox Series X|S"),
        ("xbox", "Xbox"),
        ("steam", "Steam"),
        ("pc", "PC"),
        ("switch", "Switch"),
        ("ios", "iOS"),
        ("android", "Android"),
    ]
    for keyword, label in mapping:
        if keyword in combined and label not in labels:
            labels.append(label)
    return "、".join(labels[:3]) if labels else None


def _quote_game_name(name: str) -> str:
    clean_name = name.strip(" :-")
    if not clean_name:
        return "该作"
    if clean_name.startswith("《") and clean_name.endswith("》"):
        return clean_name
    return f"《{clean_name}》"


def _finish_summary(prefix: str, clean_summary: str, source_label: str) -> str:
    if clean_summary:
        first_sentence = re.split(r"(?<=[.!?。！？])\s+", clean_summary, maxsplit=1)[0].strip()
        first_sentence = re.sub(r"\s+", " ", first_sentence)
        if len(first_sentence) > 90:
            first_sentence = first_sentence[:87].rstrip() + "..."
        return f"{prefix}。{source_label}提到：{first_sentence}"
    return f"{prefix}，目前已进入当天资讯跟踪列表。"
