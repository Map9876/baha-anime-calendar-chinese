"""Build anime calendar HTML with itv6.jp styling + bgm.tv covers."""
import os, sys, json, re
import requests
from datetime import datetime
from zhconv import convert as zhconv_convert

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(SCRIPT_DIR, 'source')
SCHEDULE_JSON = os.path.join(SCRIPT_DIR, 'schedule.json')
OUTPUT = os.path.join(SCRIPT_DIR, 'index.html')

DAYS = ['週一','週二','週三','週四','週五','週六','週日']
DAYS_SIMPLE = ['周一','周二','周三','周四','周五','周六','周日']
COVER_CACHE = os.path.join(SCRIPT_DIR, 'cover_cache.json')

def to_simple_chinese(text):
    """Convert Traditional Chinese to Simplified using zhconv."""
    return zhconv_convert(text, 'zh-cn')


def load_cover_cache():
    if os.path.exists(COVER_CACHE):
        with open(COVER_CACHE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_cover_cache(cache):
    with open(COVER_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def search_bgm_cover(anime_name, cache):
    """Search bgm.tv for anime cover. Returns cover URL or empty string."""
    if anime_name in cache:
        return cache[anime_name]
    
    try:
        # Clean name: remove season info, simplify
        search_name = to_simple_chinese(anime_name)
        # Remove season/episode suffixes that hurt search
        search_name = re.sub(r'[ 　][第季]\S+', '', search_name).strip()
        search_name = re.sub(r'Season \d+', '', search_name, flags=re.I).strip()
        search_name = re.sub(r'\d+季', '', search_name).strip()
        
        # Try v1 search (old API)
        resp = requests.get(
            f'https://api.bgm.tv/search/subject/{requests.utils.quote(search_name)}',
            params={'type': 2},
            headers={'User-Agent': 'AnimeCalendar/1.0'},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get('results', [])
            if results:
                best = results[0]
                url = best.get('images', {}).get('large', '')
                if url and not url.startswith('http'):
                    url = 'https:' + url
                if url:
                    cache[anime_name] = url
                    return url
        
        # Try v0 API as fallback
        resp = requests.get(
            'https://api.bgm.tv/v0/search/subjects',
            params={'keyword': search_name, 'subject_type': 2},
            headers={'User-Agent': 'AnimeCalendar/1.0'},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get('data', [])
            if results:
                best = results[0]
                for r in results[:5]:
                    full_name = (r.get('name','') + r.get('name_cn',''))
                    # Prefer matches where search_name keywords appear in result
                    if any(kw in full_name for kw in search_name.split()[:3] if len(kw) > 1):
                        best = r
                        break
                url = best.get('images', {}).get('large', '') or best.get('images', {}).get('medium', '')
                if url and not url.startswith('http'):
                    url = 'https:' + url
                if url:
                    cache[anime_name] = url
                    return url
    except Exception as e:
        print(f"  bgm.tv search failed for '{anime_name}': {e}")
    
    cache[anime_name] = ''
    return ''


def load_schedule():
    if not os.path.exists(SCHEDULE_JSON):
        # Try to extract from latest source
        source_files = sorted([f for f in os.listdir(SOURCE_DIR) if f.endswith('.html') and not f.endswith('_cookies.json')])
        if not source_files:
            print("No schedule data found")
            sys.exit(1)
        from fetch import extract_schedule
        with open(os.path.join(SOURCE_DIR, source_files[-1]), 'r', encoding='utf-8') as f:
            html = f.read()
        return extract_schedule(html)
    with open(SCHEDULE_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_html(schedule, updated):
    """Build HTML with itv6.jp CSS styling + anime covers."""
    # Collect all time slots
    all_times = sorted(set(e['time'] for entries in schedule.values() for e in entries))
    total = sum(len(v) for v in schedule.values())
    
    # Query bgm.tv for covers
    cover_cache = load_cover_cache()
    covers = {}
    print("Fetching covers from bgm.tv...")
    for day in DAYS:
        for entry in schedule.get(day, []):
            name = entry['name']
            if name not in covers:
                url = search_bgm_cover(name, cover_cache)
                covers[name] = url
                if url:
                    print(f"  {name[:20]:20s} -> cover")
                else:
                    print(f"  {name[:20]:20s} -> no cover")
                import time
                time.sleep(0.3)  # Rate limit
    save_cover_cache(cover_cache)
    
    # Build grid
    grid = {}
    for day in DAYS:
        for entry in schedule.get(day, []):
            t = entry['time']
            if t not in grid: grid[t] = {}
            if day not in grid[t]: grid[t][day] = []
            grid[t][day].append(entry['name'])
    
    # Build table rows
    now = datetime.now()
    current_hour = now.hour
    current_min = now.min
    current_time_str = f"{current_hour:02d}:{current_min:02d}"
    closest_time = all_times[0] if all_times else "00:00"
    for t in all_times:
        if t <= current_time_str:
            closest_time = t
    
    today_idx = now.weekday()
    
    rows_html = ""
    row_span = {}  # time -> {day -> rowspan}
    
    # Calculate rowspan for time cells (hour blocks like itv6.jp)
    time_groups = {}
    for t in all_times:
        hour = t.split(':')[0]
        if hour not in time_groups: time_groups[hour] = []
        time_groups[hour].append(t)
    
    time_span = {}
    for hour, times in time_groups.items():
        first = True
        for t in times:
            time_span[t] = {'is_first': first, 'span': len(times)}
            first = False
    
    for t in all_times:
        is_current = (t == closest_time)
        tr_cls = ' class="current-row"' if is_current else ''
        ts = time_span.get(t, {})
        rowspan = ts.get('span', 1)
        first_in_group = ts.get('is_first', True)
        
        rows_html += f'<tr{tr_cls}>\n'
        
        if first_in_group:
            rows_html += f'<td class="w_Hour1" rowspan="{rowspan}">{t.split(":")[0]}</td>\n'
        
        for di, day in enumerate(DAYS):
            # Day border color: match itv6.jp header colors
            day_border = ['#9999cc', '#9999cc', '#9999cc', '#9999cc', '#9999cc', '#99cccc', '#ff9966'][di]
            anime_list = grid.get(t, {}).get(day, [])
            if anime_list:
                names_html = ""
                for name in anime_list:
                    name_simple = to_simple_chinese(name)
                    cover = covers.get(name, '')
                    cover_html = f'<img src="{cover}" class="anime-cover" onerror="this.style.display=\'none\'">' if cover else ''
                    names_html += f'<div class="anime-entry" style="border-left: 4px solid {day_border};">{cover_html}<div class="oa_time">{t}</div><div class="oa_title">{name_simple}</div></div>'
                is_today = ' w_WeekDay' if di == today_idx else ''
                rows_html += f'<td class="w_WeekDay{is_today}">{names_html}</td>\n'
            else:
                rows_html += '<td class="space"></td>\n'
        
        rows_html += '</tr>\n'
    
    # Weekday CSS class mapping
    weekday_css = ['w_WeekDay_date'] * 4 + ['w_Sat_date'] + ['w_Sun_date'] + ['w_WeekDay_date'] * 2
    
    # Generate HTML with itv6.jp CSS
    html_out = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<title>巴哈姆特动画疯 - 新番时间表</title>
<style>
body {{
    font-size: 80%;
    margin: 0px;
    line-height: 120%;
    background-color: #ffffff;
    font-family: 'Microsoft JhengHei', 'PingFang SC', -apple-system, sans-serif;
}}
a {{
    color: #0099ff;
    text-decoration: none;
}}
a:hover {{ color: #0099ff; text-decoration: underline; }}
table {{
    font-size: 12px;
    color: #444444;
}}
.w_Hour_head {{
    color: #ffffff;
    font-weight: 900;
    font-size: 12px;
    text-align: center;
    background-color: #9999cc;
    width: 24px;
}}
.w_Hour1 {{
    color: #424242;
    font-weight: 900;
    font-size: 12px;
    text-align: center;
    background-color: #99ccff;
    width: 24px;
}}
.w_Hour2 {{
    color: #424242;
    font-weight: 900;
    font-size: 12px;
    text-align: center;
    background-color: #99ff99;
    width: 24px;
}}
.w_Hour3 {{
    color: #424242;
    font-weight: 900;
    font-size: 12px;
    text-align: center;
    background-color: #ffcc00;
    width: 24px;
}}
.oa_time {{
    font-weight: 900;
    font-size: 10px;
    color: #888;
}}
.oa_title {{
    font-weight: 900;
    font-size: 12px;
    color: #424242;
    line-height: 120%;
    letter-spacing: 0.5px;
    margin-bottom: 2px;
}}
.w_WeekDay_date {{
    color: #ffffff;
    font-weight: 900;
    font-size: 12px;
    text-align: center;
    background-color: #9999cc;
    width: 120px;
}}
.w_WeekDay {{
    font-size: 10px;
    letter-spacing: 0.5px;
    color: #424242;
    background-color: #F3F3F3;
    line-height: 12px;
    width: 120px;
    vertical-align: top;
    padding: 4px;
}}
.w_Sun_date {{
    color: #424242;
    font-weight: 900;
    font-size: 12px;
    text-align: center;
    background-color: #ff9966;
    width: 120px;
}}
.w_Sun {{
    font-size: 10px;
    color: #424242;
    background-color: #FFF0E7;
    line-height: 12px;
    width: 120px;
    vertical-align: top;
    padding: 4px;
}}
.w_Sat_date {{
    color: #424242;
    font-weight: 900;
    font-size: 12px;
    text-align: center;
    background-color: #99cccc;
    width: 120px;
}}
.w_Sat {{
    font-size: 10px;
    color: #424242;
    background-color: #E6F0E1;
    line-height: 12px;
    width: 120px;
    vertical-align: top;
    padding: 4px;
}}
.space {{
    background-color: #FFFFFF;
}}
td {{
    line-height: 110%;
    vertical-align: top;
    padding: 3px;
}}
.table_margin {{
    margin-top: 26px;
}}
h1 {{
    font-size: 16px;
    text-align: center;
    margin: 10px 0 2px;
    color: #444;
}}
.meta {{
    text-align: center;
    font-size: 11px;
    color: #888;
    margin-bottom: 6px;
}}
.current-row td {{
    background-color: #ffffcc !important;
}}
.current-row .oa_time {{
    color: #e65100;
}}
.anime-entry {{
    margin-bottom: 6px;
    padding-bottom: 4px;
    border-bottom: 1px dotted #ccc;
}}
.anime-entry:last-child {{
    border-bottom: none;
}}
.anime-cover {{
    display: block;
    width: 100%;
    max-width: 100px;
    height: auto;
    margin: 4px auto;
    border-radius: 2px;
}}
.today-col {{
    background-color: #e8f0fe !important;
}}
</style>
</head>
<body onscroll="Menu()">
<div align="center">
<div id="menu" style="position:absolute; top:0; left:0; z-index:1; width:100%;">
<table border="0" cellpadding="3" cellspacing="1" width="911px" bgcolor="#6699cc">
<tr>
<td width="24px" class="w_Hour_head">时</td>
{"".join(f'<td width="120px" class="{weekday_css[i]}">{DAYS_SIMPLE[i]}</td>' for i in range(7))}
<td width="24px" class="w_Hour_head">时</td>
</tr>
</table>
</div>
<div class="table_margin">
<table border="0" cellpadding="3" cellspacing="1" width="911px" bgcolor="#6699cc">
{rows_html}
</table>
</div>
<p style="font-size:10px; color:#888; margin-top:10px;">
更新时间: {updated} | 来源: ani.gamer.com.tw | 封面: bgm.tv
</p>
<p style="font-size:10px; color:#888; text-align:center; margin:6px 0;">
<a href="https://github.com/Map9876/baha-anime-calendar-chinese" style="color:#888; text-decoration:underline;">GitHub</a>
</p>
</div>
<script>
function Menu() {{
    var el = document.getElementById('menu');
    if (el) el.style.top = pageYOffset + 'px';
}}
onscroll = Menu;
</script>
</body>
</html>'''
    
    return html_out


def main():
    updated = datetime.now().strftime('%Y-%m-%d %H:%M')
    schedule = load_schedule()
    if not schedule:
        print("No schedule data")
        sys.exit(1)
    
    html = build_html(schedule, updated)
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        f.write(html)
    
    total = sum(len(v) for v in schedule.values())
    print(f"HTML generated: {OUTPUT} ({total} anime)")


if __name__ == '__main__':
    main()
