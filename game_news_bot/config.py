from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "config" / "app.json"
DEFAULT_SOURCES_PATH = ROOT_DIR / "config" / "sources.json"
LEGACY_CONFIG_PATH = ROOT_DIR / "config" / "sources.json"
DEFAULT_DB_PATH = ROOT_DIR / "data" / "game_news.db"
DEFAULT_BUILD_DIR = ROOT_DIR / "build"


@dataclass(slots=True)
class SourceConfig:
    name: str
    type: str
    url: str
    enabled: bool = True
    priority: int = 5
    language: str = "en"


@dataclass(slots=True)
class AIConfig:
    enabled: bool = False
    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    chat_path: str = "/chat/completions"
    api_key_env: str = "OPENAI_API_KEY"
    api_key_value: str | None = None
    model: str = "gpt-4o-mini"
    organization: str | None = None
    project: str | None = None
    timeout_seconds: int = 60
    max_articles_per_run: int = 8
    max_batches_per_run: int = 3
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, object] = field(default_factory=dict)

    @property
    def api_key(self) -> str | None:
        if self.api_key_value:
            return self.api_key_value
        return os.environ.get(self.api_key_env)


@dataclass(slots=True)
class ChannelProfile:
    name: str
    focus: list[str]
    max_digest_items: int = 10


@dataclass(slots=True)
class AppConfig:
    ai: AIConfig
    channel_profile: ChannelProfile
    sources: list[SourceConfig]


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_sources(source_path: Path | None = None) -> list[dict]:
    path = source_path or DEFAULT_SOURCES_PATH
    if not path.exists():
        return []
    payload = _read_json(path)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return list(payload.get("sources", []))
    return []


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    if config_path.is_dir():
        config_path = config_path / "app.json"

    if config_path.exists():
        payload = _read_json(config_path)
        if not isinstance(payload, dict):
            payload = {}
    elif LEGACY_CONFIG_PATH.exists():
        legacy_payload = _read_json(LEGACY_CONFIG_PATH)
        payload = legacy_payload if isinstance(legacy_payload, dict) else {}
    else:
        payload = {}

    ai_payload = payload.get("ai", {})
    ai_config = AIConfig(
        enabled=bool(ai_payload.get("enabled", False)),
        provider=str(ai_payload.get("provider", "openai-compatible")),
        base_url=str(ai_payload.get("base_url", "https://api.openai.com/v1")),
        chat_path=str(ai_payload.get("chat_path", "/chat/completions")),
        api_key_env=str(ai_payload.get("api_key_env", "OPENAI_API_KEY")),
        api_key_value=ai_payload.get("api_key"),
        model=str(ai_payload.get("model", "gpt-4o-mini")),
        organization=ai_payload.get("organization"),
        project=ai_payload.get("project"),
        timeout_seconds=int(ai_payload.get("timeout_seconds", 60)),
        max_articles_per_run=int(ai_payload.get("max_articles_per_run", 8)),
        max_batches_per_run=int(ai_payload.get("max_batches_per_run", 3)),
        extra_headers=dict(ai_payload.get("extra_headers", {})),
        extra_body=dict(ai_payload.get("extra_body", {})),
    )

    profile = payload.get("channel_profile", {})
    channel_profile = ChannelProfile(
        name=profile.get("name", "每日游戏资讯频道"),
        focus=list(profile.get("focus", [])),
        max_digest_items=int(profile.get("max_digest_items", 10)),
    )

    source_items = payload.get("sources")
    if source_items is None:
        source_items = _load_sources(DEFAULT_SOURCES_PATH)

    sources = [
        SourceConfig(
            name=item["name"],
            type=item["type"],
            url=item["url"],
            enabled=bool(item.get("enabled", True)),
            priority=int(item.get("priority", 5)),
            language=item.get("language", "en"),
        )
        for item in source_items
    ]
    return AppConfig(ai=ai_config, channel_profile=channel_profile, sources=sources)
