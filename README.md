# 巴哈姆特動畫瘋 - 新番時間表

**中国大陆直连 (Cloudflare Workers 代理):** https://c.map987.dpdns.org/https://map9876.github.io/baha-anime-calendar-chinese/

**GitHub Pages:** https://map9876.github.io/baha-anime-calendar-chinese/

通过 FlareSolverr 抓取巴哈姆特動畫瘋每周新番时间表，从 bgm.tv API 获取封面，
生成 Bilibili 风格的时间线页面。

---

## LINE TV 数据源

巴哈姆特只显示未来 3-4 天的数据。LINE TV 提供完整的季度时间表。

### API 地址

`https://static.linetv.tw/api/configs/schedule/scheduleList.json?t=1`

静态 JSON，直接 HTTP GET 即可访问（无需认证，没有 Cloudflare 防护）。

### 数据格式

```json
{
  "id": 12345,            // drama_id
  "name": "动画名称",
  "weekday": [3],          // 星期数组 (1=周一 ... 7=周日)
  "time": "20:00",         // 更新时间
  "description": "7/8起，每週三20:00更新",  // 可读的时间表
  "startTime": 1780272000000,  // Unix ms 时间戳
  "endTime": 1790000000000,
  "horizontalPosterUrl": "...",
  "verticalPosterUrl": "...",
  "channelName": ["動畫"],
  "total_eps": 12
}
```

### 发现过程

1. 打开 https://www.linetv.tw/channel/2/genre/191
2. 打开开发者工具 (F12) -> Network 标签
3. 刷新页面，过滤关键词 `scheduleList`
4. 找到 `scheduleList.json` - 包含所有正在播出的节目
5. 验证：无需认证，curl 可直接访问

> 注意：页面是 React 渲染的。像 "7/8起，每週三20:00更新" 这样的时间表文本
> 不在初始 HTML 中 - 由前端从 scheduleList.json 渲染。

### 数据源对比

| 特性 | 巴哈姆特 (ani.gamer) | LINE TV |
|------|---------------------|---------|
| 范围 | 仅���周 | 完整季度 |
| 时间信息 | 仅时间 | 开播日期 + 每周时间 |
| 数量 | ~20-30/周 | ~80-90/季 |
| 访问方式 | 需要 FlareSolverr | 直接 HTTP GET |
| 集数 | 无 | 有 total_eps |
| 封面 | bgm.tv API | 自带海报 |
| 覆盖范围 | 仅本周 | 整季 |

### 季度过滤

LINE TV 包含多个季度的节目。通过开播月份过滤：

```python
def get_season_range(now):
    m = now.month
    if 1 <= m <= 3:   return (1, 3)   # 冬季
    elif 4 <= m <= 6: return (4, 6)   # 春季
    elif 7 <= m <= 9: return (7, 9)   # 夏季
    else:             return (10, 12)  # 秋季
```

季度边界：
- 冬季 (1月): 1-3月（允许前一年12月）
- 春季 (4月): 4-6月��允许3月）
- 夏季 (7月): 7-9月（允许6月）
- 秋季 (10月): 10-12月（允许9月）

### 复杂时间表解析

部分动画有特殊的首周播出安排：
- "7/4首週播出2集，EP1 19:00 EP2 19:30，7/12起，每週日23:00後更新"
- "7/2首週播出3集，7/9起，每週四22:00後���新"

详细解析逻辑见 `fetch_linetv.py` 中的 `parse_description()` 函数。

### 去重逻辑

LINE TV 和巴哈姆特的数据通过模糊标题匹配去重：
1. 标准化标题（去除空格、括号、季节标记）
2. 计���相似度评分
3. 评分 >= 0.85 视为匹配，跳过 LINE TV 条目

---

## 数据流

```
fetch.py (FlareSolverr) -> schedule.json (巴哈姆特, 本周)
fetch_linetv.py (HTTP GET) -> linetv_schedule.json (LINE TV, 整季)
                                        |
build.py -> 合并两个数据源 -> 去重 -> 生成 index.html
```

---

## Agent-Browser MCP 安装

### 快速安装

```bash
npm install -g @anthropic-ai/agent-browser
```

### 一键脚本

```bash
npx agent-browser install
```

### 验证安装

```bash
npx agent-browser eval "document.title"
```

### MCP 工具列表

- `browser_navigate` - 导航到 URL
- `browser_evaluate` - 执行 JavaScript
- `browser_snapshot` - 页面快照
- `browser_click` - 点击元素
- `browser_type` - 输入文本
- `browser_network` - 网络监控
- `browser_get` - 获取元素信息

### 配置文件位置

- MCP 配置: `/root/.codebuddy/.mcp.json`
- Playwright 缓存: `/root/.cache/ms-playwright/`

---

## 本地构建

```bash
# 安装依赖
pip install requests zhconv

# 获取巴哈姆特数据
python3 fetch.py

# 获取 LINE TV 数据
python3 fetch_linetv.py

# 构建 HTML
python3 build.py

# 输出文件: index.html
```
