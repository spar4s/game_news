# 配置说明

现在配置拆成了两个文件：

- `app.json`
  - 放 AI、频道名、日报条数等应用级配置
- `sources.json`
  - 只放采集源列表，后续增删改来源只需要改这个文件

## `sources.json` 字段

每个采集源支持这些字段：

- `name`: 来源显示名
- `type`: 采集类型，目前使用 `rss`
- `url`: RSS / Atom 地址
- `enabled`: 是否启用
- `priority`: 优先级，数字越大越容易进入高热内容池
- `language`: 来源语言，例如 `en`、`zh`

## 新增一个采集源

直接在 `sources` 数组里追加一项，例如：

```json
{
  "name": "Nintendo News",
  "type": "rss",
  "url": "https://example.com/feed.xml",
  "enabled": true,
  "priority": 8,
  "language": "en"
}
```

## 暂时关闭一个采集源

把对应条目的：

```json
"enabled": true
```

改成：

```json
"enabled": false
```

## 修改后怎么生效

改完配置后，重新执行：

```bash
uv run game_news_bot --hours 24
```

或者单独抓取：

```bash
python -m game_news_bot fetch
```
