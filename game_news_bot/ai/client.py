from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from game_news_bot.config import AIConfig


SYSTEM_PROMPT = """
你是一名游戏资讯编辑助手。你的任务是把输入的英文或中文游戏新闻，整理成适合中文游戏资讯频道发布的结构化结果。
请只返回 JSON 对象，不要输出 markdown，不要输出解释。
字段要求：
- headline_zh: 简洁自然的中文标题，保留必要的英文游戏名或专有名词
- summary_zh: 1 到 2 句中文摘要，要求是中文转述，不要只是复制英文原文
- category: 从以下类别中选择一个：新作公布、发售日期、更新补丁、DLC扩展、行业动态、平台动态、社区热点、传闻爆料、其他
- why_it_matters: 用一句中文说明为什么这条值得关注
- confidence: 0 到 1 之间的小数
""".strip()


CONTEXT_SYSTEM_PROMPT = """
你是一名中文游戏资讯编辑。请根据“当前新闻”和“此前相关动态”，输出一句适合日报使用的中文前情提要。
要求：
- 只返回 JSON 对象
- 字段名必须是 context_summary
- 语气简洁，像编辑写的背景补充
- 长度控制在 1 句话内，尽量不要超过 45 个中文字符
- 如果历史信息不足，也尽量概括成一句自然的话
""".strip()


def analyze_article(ai_config: AIConfig, article: dict[str, str]) -> dict[str, object]:
    if not ai_config.enabled or not ai_config.api_key:
        raise ValueError("AI is not configured")

    prompt = {
        "title": article.get("title", ""),
        "summary": article.get("summary", ""),
        "source_name": article.get("source_name", ""),
        "url": article.get("url", ""),
    }

    result = _post_json(
        ai_config,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
    )
    return {
        "headline_zh": str(result.get("headline_zh", "")).strip(),
        "summary_zh": str(result.get("summary_zh", "")).strip(),
        "category": str(result.get("category", "其他")).strip(),
        "why_it_matters": str(result.get("why_it_matters", "")).strip(),
        "confidence": float(result.get("confidence", 0)),
    }


def summarize_context(
    ai_config: AIConfig,
    current_title: str,
    current_summary: str,
    prior_titles: list[str],
) -> str:
    if not ai_config.enabled or not ai_config.api_key:
        raise ValueError("AI is not configured")

    result = _post_json(
        ai_config,
        [
            {"role": "system", "content": CONTEXT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "current_title": current_title,
                        "current_summary": current_summary,
                        "related_history": prior_titles,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    return str(result.get("context_summary", "")).strip()


def _post_json(ai_config: AIConfig, messages: list[dict[str, str]]) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": ai_config.model,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    if ai_config.extra_body:
        payload.update(ai_config.extra_body)

    request = urllib.request.Request(
        _build_endpoint(ai_config),
        data=json.dumps(payload).encode("utf-8"),
        headers=_build_headers(ai_config),
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=ai_config.timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"AI request failed: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"AI request failed: {exc}") from exc

    content = raw["choices"][0]["message"]["content"]
    return _extract_json_payload(content)


def _build_endpoint(ai_config: AIConfig) -> str:
    base = ai_config.base_url.rstrip("/")
    path = ai_config.chat_path.strip()
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _build_headers(ai_config: AIConfig) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {ai_config.api_key}",
        "Content-Type": "application/json",
    }
    if ai_config.organization:
        headers["OpenAI-Organization"] = ai_config.organization
    if ai_config.project:
        headers["OpenAI-Project"] = ai_config.project
    if ai_config.extra_headers:
        headers.update({str(k): str(v) for k, v in ai_config.extra_headers.items()})
    return headers


def _extract_json_payload(content: str) -> dict[str, object]:
    text = content.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise json.JSONDecodeError("Unable to extract JSON object from model output", content, 0)
