"""Build Bilibili-style anime timeline page."""
import os, sys, json, re
import requests
from datetime import datetime, timedelta
from zhconv import convert as zhconv_convert

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(SCRIPT_DIR, 'source')
SCHEDULE_JSON = os.path.join(SCRIPT_DIR, 'schedule.json')
OUTPUT = os.path.join(SCRIPT_DIR, 'index.html')

DAYS = ['週一','週二','週三','週四','週五','週六','週日']
DAYS_SIMPLE = ['一','二','三','四','五','六','日']
COVER_CACHE = os.path.join(SCRIPT_DIR, 'cover_cache.json')

def to_simple_chinese(text):
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
    if anime_name in cache:
        return cache[anime_name]
    try:
        search_name = to_simple_chinese(anime_name)
        search_name = re.sub(r'[ 　][第季]\S+', '', search_name).strip()
        resp = requests.get(f'https://api.bgm.tv/search/subject/{requests.utils.quote(search_name)}',
            params={'type': 2}, headers={'User-Agent': 'AnimeCalendar/1.0'}, timeout=10)
        if resp.status_code == 200:
            results = resp.json().get('results', [])
            if results:
                url = results[0].get('images', {}).get('large', '')
                if url and not url.startswith('http'): url = 'https:' + url
                if url: cache[anime_name] = url; return url
        resp = requests.get('https://api.bgm.tv/v0/search/subjects',
            params={'keyword': search_name, 'subject_type': 2},
            headers={'User-Agent': 'AnimeCalendar/1.0'}, timeout=10)
        if resp.status_code == 200:
            results = resp.json().get('data', [])
            if results:
                url = results[0].get('images', {}).get('large', '') or results[0].get('images', {}).get('medium', '')
                if url and not url.startswith('http'): url = 'https:' + url
                if url: cache[anime_name] = url; return url
    except: pass
    cache[anime_name] = ''
    return ''

def load_schedule():
    if not os.path.exists(SCHEDULE_JSON):
        source_files = sorted([f for f in os.listdir(SOURCE_DIR) if f.endswith('.html') and not f.endswith('_cookies.json')])
        if not source_files: print("No schedule data"); sys.exit(1)
        from fetch import extract_schedule
        with open(os.path.join(SOURCE_DIR, source_files[-1]), 'r', encoding='utf-8') as f:
            html = f.read()
        return extract_schedule(html)
    with open(SCHEDULE_JSON, 'r', encoding='utf-8') as f:
        return json.load(f)


def build_html(schedule, updated):
    """Build Bilibili-style anime timeline page."""
    now = datetime.now()
    today_idx = now.weekday()  # 0=Mon, 6=Sun
    
    # Query bgm.tv covers
    cover_cache = load_cover_cache()
    covers = {}
    print("Fetching covers from bgm.tv...")
    for day in DAYS:
        for entry in schedule.get(day, []):
            name = entry['name']
            if name not in covers:
                url = search_bgm_cover(name, cover_cache)
                covers[name] = url
                print(f"  {name[:20]:20s} -> {'cover' if url else 'no cover'}")
                import time; time.sleep(0.3)
    save_cover_cache(cover_cache)
    
    # Build date tabs and timeline content
    today_date = now.strftime('%m/%d')
    weekday_names = ['一','二','三','四','五','六','日']
    
    # Generate date tabs
    date_tabs = ""
    for i in range(7):
        day = DAYS[i]
        is_active = (i == today_idx)
        active_cls = ' active' if is_active else ''
        dot_html = '<div class="today-dot"></div>' if is_active else ''
        date_str = (now + timedelta(days=i - today_idx)).strftime('%m/%d') if i >= today_idx else (now + timedelta(days=i - today_idx)).strftime('%m/%d')
        # Actually just use the same week's dates
        monday = now - timedelta(days=today_idx)
        day_date = monday + timedelta(days=i)
        date_str = day_date.strftime('%m/%d')
        date_tabs += f'<div class="date-tab{active_cls}" data-day="{day}">{dot_html}<div class="date-weekday">{weekday_names[i]}</div><div class="date-num">{date_str}</div></div>'
    
    # Generate timeline content for each day
    timelines = {}
    for day in DAYS:
        entries = schedule.get(day, [])
        if not entries:
            timelines[day] = '<div class="empty-day">当天无更新</div>'
            continue
        html = ""
        for entry in entries:
            name_simple = to_simple_chinese(entry['name'])
            time_str = entry['time']
            hour, minute = time_str.split(':')
            cover = covers.get(entry['name'], '')
            cover_html = f'<img src="{cover}" class="timeline-cover" onerror="this.style.display=\'none\'">' if cover else ''
            is_now = False
            if day == DAYS[today_idx]:
                now_time = now.strftime('%H:%M')
                is_now = (time_str == now_time)
            now_cls = ' now-airing' if is_now else ''
            html += f'''
            <div class="timeline-item{now_cls}">
              <div class="timeline-left">
                <div class="timeline-cir"></div>
                <div class="timeline-line"></div>
                <div class="timeline-time">{hour}:{minute}</div>
              </div>
              <div class="timeline-right">
                {cover_html}
                <div class="timeline-title">{name_simple}</div>
              </div>
            </div>'''
        timelines[day] = html
    
    # Generate content divs for view pager
    content_divs = ""
    for i, day in enumerate(DAYS):
        active_cls = ' active' if i == today_idx else ''
        content_divs += f'<div class="timeline-content{active_cls}" data-day="{day}">{timelines[day]}</div>'
    
    total = sum(len(v) for v in schedule.values())
    
    html_out = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>新番时间表</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif; background:#f5f5f5; color:#333; }}
.header {{ position:sticky; top:0; z-index:10; background:linear-gradient(135deg,#fb7299,#fb5588); padding:12px 16px 8px; }}
.header h1 {{ font-size:18px; color:#fff; font-weight:600; }}
.header .meta {{ font-size:11px; color:rgba(255,255,255,.7); margin-top:2px; }}
.date-bar {{ position:sticky; top:54px; z-index:9; background:#fff; display:flex; overflow-x:auto; -webkit-overflow-scrolling:touch; border-bottom:1px solid #eee; }}
.date-bar::-webkit-scrollbar {{ display:none; }}
.date-tab {{ flex:0 0 60px; min-width:60px; padding:8px 4px; text-align:center; cursor:pointer; -webkit-tap-highlight-color:transparent; position:relative; }}
.date-tab.active {{ background:#fff; }}
.date-tab.active .date-weekday {{ color:#fb7299; font-weight:700; }}
.date-tab.active .date-num {{ color:#fb7299; }}
.date-tab::after {{ content:''; position:absolute; bottom:0; left:50%; transform:translateX(-50%); width:20px; height:3px; border-radius:2px; background:transparent; }}
.date-tab.active::after {{ background:#fb7299; }}
.today-dot {{ width:5px; height:5px; background:#fb7299; border-radius:50%; margin:0 auto 3px; }}
.date-weekday {{ font-size:15px; color:#666; margin-bottom:2px; }}
.date-num {{ font-size:11px; color:#999; }}
.timeline-pager {{ overflow:hidden; position:relative; }}
.timeline-content {{ display:none; padding:0 16px; transition:transform .3s ease; }}
.timeline-content.active {{ display:block; }}
.empty-day {{ text-align:center; padding:60px 20px; color:#999; font-size:14px; }}
.timeline-item {{ display:flex; padding:12px 0; position:relative; }}
.timeline-item.now-airing {{ background:#fff0f5; margin:0 -16px; padding:12px 16px; border-radius:8px; }}
.timeline-left {{ flex:0 0 56px; display:flex; flex-direction:column; align-items:center; position:relative; }}
.timeline-cir {{ width:8px; height:8px; border-radius:50%; background:#ddd; z-index:1; flex-shrink:0; }}
.timeline-item.now-airing .timeline-cir {{ width:10px; height:10px; background:#fb7299; box-shadow:0 0 6px rgba(251,114,153,.5); }}
.timeline-line {{ width:1px; flex:1; background:#e0e0e0; min-height:20px; }}
.timeline-item:last-child .timeline-line {{ display:none; }}
.timeline-time {{ font-size:13px; color:#999; margin-top:4px; white-space:nowrap; }}
.timeline-item.now-airing .timeline-time {{ color:#fb7299; font-weight:600; }}
.timeline-right {{ flex:1; margin-left:12px; padding-bottom:8px; border-bottom:1px solid #f0f0f0; }}
.timeline-item:last-child .timeline-right {{ border-bottom:none; }}
.timeline-cover {{ display:block; width:80px; height:auto; border-radius:4px; margin-bottom:6px; }}
.timeline-title {{ font-size:14px; color:#333; line-height:1.5; }}
.timeline-item.now-airing .timeline-title {{ color:#fb7299; }}
.footer {{ text-align:center; padding:16px; font-size:11px; color:#999; }}
.footer a {{ color:#999; text-decoration:underline; }}
@media (max-width:480px) {{
  .timeline-left {{ flex-basis:48px; }}
  .timeline-cover {{ width:64px; }}
  .timeline-title {{ font-size:13px; }}
}}
</style>
</head>
<body>

<div class="header">
  <h1>新番时间表</h1>
  <div class="meta">更新: {updated}</div>
</div>

<div class="date-bar" id="dateBar">
  {date_tabs}
</div>

<div class="timeline-pager" id="timelinePager">
  {content_divs}
</div>

<div class="footer">
  <a href="https://github.com/Map9876/baha-anime-calendar-chinese">GitHub</a>
</div>

<script>
(function() {{
  var tabs = document.querySelectorAll('.date-tab');
  var pages = document.querySelectorAll('.timeline-content');
  var bar = document.getElementById('dateBar');
  
  function switchDay(idx) {{
    tabs.forEach(function(t,i) {{ t.classList.toggle('active',i===idx); }});
    pages.forEach(function(p,i) {{ p.classList.toggle('active',i===idx); }});
    // Scroll tab into view
    var tab = tabs[idx];
    if (tab) {{
      var scrollLeft = tab.offsetLeft - bar.offsetWidth/2 + tab.offsetWidth/2;
      bar.scrollTo({{ left:Math.max(0,scrollLeft), behavior:'smooth' }});
    }}
  }}
  
  tabs.forEach(function(tab,i) {{
    tab.addEventListener('click',function(){{ switchDay(i); }});
  }});
  
  // Touch swipe
  var startX = 0, currentPage = 0;
  tabs.forEach(function(t,i) {{ if(t.classList.contains('active')) currentPage=i; }});
  
  var pager = document.getElementById('timelinePager');
  pager.addEventListener('touchstart',function(e){{ startX=e.touches[0].clientX; }});
  pager.addEventListener('touchend',function(e){{
    var diff = startX - e.changedTouches[0].clientX;
    if(Math.abs(diff)>50) {{
      if(diff>0 && currentPage<6) switchDay(++currentPage);
      else if(diff<0 && currentPage>0) switchDay(--currentPage);
    }}
  }});
}})();
</script>
</body>
</html>'''
    
    return html_out

def main():
    updated = datetime.now().strftime('%Y-%m-%d %H:%M')
    schedule = load_schedule()
    if not schedule: print("No schedule data"); sys.exit(1)
    html = build_html(schedule, updated)
    with open(OUTPUT, 'w', encoding='utf-8') as f: f.write(html)
    total = sum(len(v) for v in schedule.values())
    print(f"HTML generated: {OUTPUT} ({total} anime)")

if __name__ == '__main__':
    main()
