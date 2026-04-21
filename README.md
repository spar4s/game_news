# Game News Bot

一个受 `Horizon` 启发的游戏资讯聚合 MVP，用来抓取、整理、生成日报，并输出成静态站点。

## 当前能力

- 从配置文件读取采集源
- 抓取 RSS / Atom 资讯并写入 SQLite
- 基础去重、过滤、优先级排序
- 可选 AI 中文标题、摘要、看点、前情提要
- 热点事件聚类与快讯生成
- 玩家热议合并进主日报
- 生成首页 + 每日归档页的静态站点

## 配置文件

- [config/app.json](C:/Users/zzz/Documents/Codex/2026-04-20-https-github-com-thysrael-horizon/config/app.json)
  - AI、频道名、日报条数
- [config/sources.json](C:/Users/zzz/Documents/Codex/2026-04-20-https-github-com-thysrael-horizon/config/sources.json)
  - 采集源列表
- [config/README.md](C:/Users/zzz/Documents/Codex/2026-04-20-https-github-com-thysrael-horizon/config/README.md)
  - 配置字段说明

后面如果你只想增删采集源，直接改 `config/sources.json` 就行。

## 本地运行

初始化数据库：

```bash
python -m game_news_bot init-db
```

单独抓取：

```bash
python -m game_news_bot fetch
```

生成过去 24 小时报告：

```bash
uv run game_news_bot --hours 24
```

这条命令会自动完成：

- 抓取资讯
- AI 分批处理
- 生成日报
- 生成快讯
- 生成静态站点

输出文件默认在：

- `build/digest-last-24h.md`
- `build/bulletins-last-24h.md`
- `build/site/index.html`

## AI 配置

项目支持 OpenAI 兼容接口。

默认示例在 `config/app.json`：

```json
{
  "ai": {
    "enabled": true,
    "provider": "openai-compatible",
    "base_url": "https://api.minimaxi.com/v1",
    "chat_path": "/chat/completions",
    "api_key": "",
    "api_key_env": "MINIMAX_API_KEY",
    "model": "MiniMax-M2.7"
  }
}
```

建议优先使用环境变量或 GitHub Secret，不要把真实 key 提交到仓库里。

## GitHub Actions / GitHub Pages

仓库里已经准备好工作流：

- [deploy-pages.yml](C:/Users/zzz/Documents/Codex/2026-04-20-https-github-com-thysrael-horizon/.github/workflows/deploy-pages.yml)

它会：

- 定时执行 `uv run game_news_bot --hours 24`
- 生成最新静态站点
- 发布到 GitHub Pages
- 用 Actions cache 保存 `data/game_news.db`，尽量保留历史数据

### 你需要做的事

1. 在 GitHub 仓库里添加 Secret：
   - `MINIMAX_API_KEY`
2. 在仓库设置里启用 GitHub Pages：
   - Source 选择 `GitHub Actions`
3. 推送代码后，手动运行一次工作流确认部署成功

## 默认目录

- 配置：`config/`
- 数据库：`data/game_news.db`
- 输出：`build/`
