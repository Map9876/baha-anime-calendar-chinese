# Bahamut Anime Crazy - Anime Schedule

**China Direct (Cloudflare Workers Proxy):** https://c.map987.dpdns.org/https://map9876.github.io/baha-anime-calendar-chinese/

**GitHub Pages:** https://map9876.github.io/baha-anime-calendar-chinese/

Scrape Bahamut Anime Crazy weekly schedule via FlareSolverr, fetch covers from bgm.tv API,
generate a Bilibili-style timeline page.

---

## LINE TV Data Source

Bahamut only shows 3-4 days of future data. LINE TV provides full season schedules.

### API Endpoint



Static JSON, accessible via plain HTTP GET (no auth, no Cloudflare).

### Data Format



- uid=0(root) gid=0(root) 组=0(root) -- drama_id
-  -- day array (1=Mon ... 7=Sun)
-  -- update time
-  -- human readable schedule
-  -- Unix ms timestamps

### API Discovery

1. Open https://www.linetv.tw/channel/2/genre/191
2. Open DevTools (F12) -> Network tab
3. Reload, filter by 
4. Found  - contains all airing shows
5. Verified: no auth needed, accessible via curl

> Note: Page is React-rendered. Schedule text like "7/8 start, every Wed 23:30"
> is NOT in initial HTML - it is rendered by frontend from scheduleList.json.

### Source Comparison

| Feature | Bahamut (ani.gamer) | LINE TV |
|---------|---------------------|---------|
| Range | Current week only | Full season |
| Time info | Time only | Start date + weekly time |
| Count | ~20-30/week | ~80-90/season |
| Access | FlareSolverr needed | Plain HTTP GET |
| Episodes | None | total_eps available |
| Covers | bgm.tv API | Built-in posters |
| Coverage | This week only | Full season |

### Season Filtering

LINE TV includes shows from multiple seasons. Filter by start month:



Season boundaries:
- Winter (Jan): Jan-Mar (allow prev Dec)
- Spring (Apr): Apr-Jun (allow Mar)
- Summer (Jul): Jul-Sep (allow Jun)
- Autumn (Oct): Oct-Dec (allow Sep)

### Complex Schedule Parsing

Some anime have special first-week schedules:
- "7/4 start, 2 eps first week, EP1 19:00 EP2 19:30, 7/12 onwards every Sun 23:00"
- "7/2 start, 3 eps first week, 7/9 onwards every Thu 22:00"

See  for full parsing logic.

---

## Data Flow



---

## Agent-Browser MCP Setup

### Quick Install



### One-Click Script



### Verify



### MCP Tools Available

- browser_navigate - Navigate to URL
- browser_evaluate - Execute JavaScript
- browser_snapshot - Page snapshot
- browser_click - Click element
- browser_type - Type text
- browser_network - Network monitor
- browser_get - Get element info

### Config Locations

- MCP config: /root/.codebuddy/.mcp.json
- Playwright cache: /root/.cache/ms-playwright/