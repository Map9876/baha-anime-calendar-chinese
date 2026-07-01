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


def merge_linetv_schedule(schedule):
    """Merge LINE TV exclusive entries into Bahamut schedule dict, remove finished cross-season entries."""
    linetv_path = os.path.join(SCRIPT_DIR, 'linetv_schedule.json')
    if not os.path.exists(linetv_path):
        return schedule
    
    with open(linetv_path, 'r', encoding='utf-8') as f:
        linetv_data = json.load(f)
    
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=8)))
    
    # weekday_cn -> 週X mapping
    wd_key_map = {'一':'週一','二':'週二','三':'週三','四':'週四',
                  '五':'週五','六':'週六','日':'週日'}
    
    # Step 1: Build lookup: for each cross-season show (matched with Bahamut), 
    # check if it has actually ended (end_timestamp in the past)
    ended_titles = set()
    ended_bahamut_titles = set()
    for anime in linetv_data.get('anime', []):
        if not anime.get('in_current_season') and anime.get('bahamut_match', {}).get('matched'):
            end_ts = anime.get('end_timestamp')
            if end_ts:
                end_dt = datetime.fromtimestamp(end_ts / 1000, tz=now.tzinfo)
                if end_dt < now:
                    # Show has ended — mark for removal
                    ended_titles.add(anime['title'])
                    bt = anime.get('bahamut_match', {}).get('bahamut_title', '')
                    if bt:
                        ended_bahamut_titles.add(bt)
            # If no end_timestamp, assume still airing (keep it)
    
    # Step 2: Remove ended cross-season entries from Bahamut schedule
    removed = 0
    for day_key in list(schedule.keys()):
        filtered = []
        for entry in schedule[day_key]:
            name = entry['name']
            name_norm = re.sub(r'\s+', '', name).lower()
            is_ended = name in ended_titles or name in ended_bahamut_titles
            if not is_ended:
                for ct in ended_titles:
                    if re.sub(r'\s+', '', ct).lower() == name_norm:
                        is_ended = True
                        break
            if is_ended:
                removed += 1
            else:
                filtered.append(entry)
        if filtered:
            schedule[day_key] = filtered
        else:
            del schedule[day_key]
    
    # Step 3: Merge LINE TV exclusive entries
    added = 0
    for anime in linetv_data.get('anime', []):
        # Skip if not current season or already in Bahamut
        if not anime.get('in_current_season'):
            continue
        if anime.get('bahamut_match', {}).get('matched'):
            continue
        
        parsed = anime.get('parsed_schedule', [])
        for entry in parsed:
            if entry.get('type') != 'regular':
                continue
            wd_cn = entry.get('weekday_cn')
            if not wd_cn or wd_cn not in wd_key_map:
                continue
            day_key = wd_key_map[wd_cn]
            new_entry = {
                'time': entry['time'],
                'name': anime['title'],
                'source': 'linetv'
            }
            # Avoid exact duplicates
            if new_entry not in schedule.get(day_key, []):
                schedule.setdefault(day_key, []).append(new_entry)
                added += 1
    
    # Sort each day by time
    for day_key in schedule:
        schedule[day_key].sort(key=lambda x: x['time'])
    
    print(f"Removed {removed} cross-season entries, merged {added} LINE TV entries")
    return schedule


def build_html(schedule, updated):
    """Build Bilibili-style anime timeline page with 30-hour time."""
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
    
    # Extended date range: Monday - 5 days to Monday + 13 days (19 days total)
    # This covers: previous week's tail + current week + next week + beyond
    monday = now - timedelta(days=today_idx)
    all_dates = [monday + timedelta(days=i-5) for i in range(19)]  # -5 to +13, 19 days
    
    weekday_names = ['一','二','三','四','五','六','日']
    
    # Convert standard time to 30-hour format
    def to_30h(hour_str, minute_str):
        h = int(hour_str)
        if h <= 6:  # 0:00-5:59 → 24:00-29:59, 6:00-6:59 → 30:00-30:59
            h += 24
        return f"{h}:{minute_str}"
    
    # Current time in 30-hour format
    now_h = now.hour
    now_m = now.minute
    now_30h = f"{now_h}:{now_m:02d}" if now_h > 6 else f"{now_h+24}:{now_m:02d}"
    now_30h_val = now_h + 24 if now_h <= 6 else now_h
    now_30h_min = now_h * 60 + now_m
    
    # Map weekday name → date for this week
    day_date_map = {}
    for dt in all_dates:
        day_date_map[weekday_names[dt.weekday()]] = dt
    
    # Generate date tabs for this week's 7 days
    date_tabs = ""
    for dt in all_dates:
        day_label = weekday_names[dt.weekday()]
        is_today = (dt.date() == now.date())
        active_cls = ' active' if is_today else ''
        dot_html = '<div class="today-dot"></div>' if is_today else ''
        date_str = dt.strftime('%m/%d')
        date_tabs += f'<div class="date-tab{active_cls}" data-date="{date_str}">{dot_html}<div class="date-num">{date_str}</div><div class="date-weekday">{day_label}</div></div>'
    
    # Map anime entries to dates using 30-hour rule
    # For each Bahamut weekday, map to the nearest matching date in our range
    date_entries = {}
    for dt in all_dates:
        date_entries[dt.strftime('%m/%d')] = []
    
    for i, day in enumerate(DAYS):
        entries = schedule.get(day, [])
        if not entries:
            continue
        # Find the date in our range that matches this weekday
        matching_dates = [dt for dt in all_dates if dt.weekday() == i]
        if not matching_dates:
            continue
        for entry in entries:
            h = int(entry['time'].split(':')[0])
            # 30-hour rule: air times before 6:00 belong to previous day
            target_idx = 0  # first matching date
            if h < 6 and len(matching_dates) > 1:
                target_idx = 0  # prev day's slot is first matching date
            else:
                # Use the most recent matching date that is not in the past
                future_dates = [dt for dt in matching_dates if dt.date() >= now.date() - timedelta(days=2)]
                if future_dates:
                    target_idx = matching_dates.index(future_dates[0])
                else:
                    target_idx = -1  # last matching date
            if target_idx < 0:
                target_idx = len(matching_dates) - 1
            
            target_date = matching_dates[target_idx]
            if h < 6:
                target_date = target_date - timedelta(days=1)
            key = target_date.strftime('%m/%d')
            if key in date_entries:
                date_entries[key].append(entry)
    
    # Generate timeline content for each date
    timelines = {}
    for dt in all_dates:
        key = dt.strftime('%m/%d')
        entries = date_entries.get(key, [])
        if not entries:
            timelines[key] = '<div class="empty-day">当天无更新</div>'
            continue
        html = ""
        is_today = (dt.date() == now.date())
        now_indicator_added = False
        # For today: find the first entry past current time
        if is_today and entries:
            first_future_idx = None
            for idx, entry in enumerate(entries):
                h = int(entry['time'].split(':')[0])
                m = int(entry['time'].split(':')[1])
                entry_min = h * 60 + m
                if entry_min > now_30h_min:
                    first_future_idx = idx
                    break
            # All entries are past → now at the beginning
            # All entries are future → now at the beginning too
            if first_future_idx == 0 or first_future_idx is None:
                html += f'<div class="now-label-bar"><span class="now-label-text">now {now_30h}</span></div>'
                now_indicator_added = True
        for entry in entries:
            name_simple = to_simple_chinese(entry['name'])
            time_str = entry['time']
            hour, minute = time_str.split(':')
            h = int(hour)
            time_30h = to_30h(hour, minute)
            # Check if near current time
            entry_min = h * 60 + int(minute)
            is_now = abs(entry_min - now_30h_min) <= 15 and is_today
            # Insert "now" indicator before the first entry that is past current time
            if is_today and not now_indicator_added and entry_min > now_30h_min:
                html += f'<div class="now-label-bar"><span class="now-label-text">now {now_30h}</span></div>'
                now_indicator_added = True
            cover = covers.get(entry['name'], '')
            cover_html = f'<img src="{cover}" class="timeline-cover" onerror="this.style.display=\'none\'">' if cover else ''
            now_cls = ' now-airing' if is_now else ''
            html += f'''
            <div class="timeline-item{now_cls}">
              <div class="timeline-left">
                <div class="timeline-cir"></div>
                <div class="timeline-line"></div>
                <div class="timeline-time">{time_30h}</div>
              </div>
              <div class="timeline-right">
                {cover_html}
                <div class="timeline-title">{name_simple}</div>
              </div>
            </div>'''
        # Add "now" indicator at the end if no entries are past current time
        if is_today and not now_indicator_added:
            html += f'<div class="now-label-bar"><span class="now-label-text">now {now_30h}</span></div>'
        timelines[key] = html
    
    # Content divs
    content_divs = ""
    for dt in all_dates:
        key = dt.strftime('%m/%d')
        is_today = (dt.date() == now.date())
        active_cls = ' active' if is_today else ''
        content_divs += f'<div class="timeline-content{active_cls}" data-date="{key}">{timelines[key]}</div>'
    
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
.header {{ position:sticky; top:0; z-index:10; background:linear-gradient(135deg,#fb7299,#fb5588); padding:6px 12px 4px; }}
.header h1 {{ font-size:15px; color:#fff; font-weight:600; }}
.header .meta {{ font-size:10px; color:rgba(255,255,255,.7); }}
.date-bar {{ position:sticky; top:35px; z-index:9; background:#fff; display:flex; overflow-x:auto; -webkit-overflow-scrolling:touch; }}
.date-bar::before {{ content:''; position:absolute; top:0; left:0; right:0; height:8px; background:linear-gradient(to bottom,rgba(0,0,0,.12),transparent); z-index:1; pointer-events:none; }}
.date-bar::after {{ content:''; position:absolute; bottom:0; left:0; right:0; height:8px; background:linear-gradient(to top,rgba(0,0,0,.12),transparent); z-index:1; pointer-events:none; }}
.date-bar-shadow-l {{ position:absolute; top:0; left:0; bottom:0; width:12px; background:linear-gradient(to right,rgba(0,0,0,.1),transparent); z-index:2; pointer-events:none; }}
.date-bar-shadow-r {{ position:absolute; top:0; right:0; bottom:0; width:12px; background:linear-gradient(to left,rgba(0,0,0,.1),transparent); z-index:2; pointer-events:none; }}
.date-bar::-webkit-scrollbar {{ display:none; }}
.date-tab {{ flex:0 0 52px; min-width:52px; padding:8px 4px; text-align:center; cursor:pointer; -webkit-tap-highlight-color:transparent; position:relative; }}
.date-tab.active {{ }}
.date-tab.active .date-num {{ color:#fb7299; font-weight:700; }}
.date-tab.active .date-weekday {{ color:#fb7299; }}
.date-tab::after {{ content:''; position:absolute; bottom:0; left:50%; transform:translateX(-50%); width:18px; height:3px; border-radius:2px; background:transparent; }}
.date-tab.active::after {{ background:#fb7299; }}
.today-dot {{ width:4px; height:4px; background:#fb7299; border-radius:50%; margin:0 auto 2px; }}
.date-num {{ font-size:12px; color:#999; margin-bottom:1px; line-height:16px; }}
.date-weekday {{ font-size:16px; color:#333; line-height:20px; }}
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
.now-label-bar {{ position:relative; margin:8px 0; text-align:center; border-top:1px dashed #fb7299; padding-top:4px; }}
.now-label-text {{ font-size:11px; color:#fb7299; background:#fff; padding:0 8px; display:inline-block; }}
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
  <div class="date-bar-shadow-l"></div>
  <div class="date-bar-shadow-r"></div>
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
      if(diff>0 && currentPage<tabs.length-1) switchDay(++currentPage);
      else if(diff<0 && currentPage>0) switchDay(--currentPage);
    }}
  }});
  
  // Scroll shadows for date bar
  var shadowL = document.querySelector('.date-bar-shadow-l');
  var shadowR = document.querySelector('.date-bar-shadow-r');
  function updateShadows() {{
    shadowL.style.opacity = bar.scrollLeft > 2 ? '1' : '0';
    shadowR.style.opacity = bar.scrollLeft < bar.scrollWidth - bar.clientWidth - 2 ? '1' : '0';
  }}
  bar.addEventListener('scroll', updateShadows);
  // Scroll to center today's tab on load
  setTimeout(function() {{
    var activeTab = document.querySelector('.date-tab.active');
    if (activeTab) {{
      var scrollLeft = activeTab.offsetLeft - bar.offsetWidth/2 + activeTab.offsetWidth/2;
      bar.scrollTo({{ left:Math.max(0,scrollLeft), behavior:'auto' }});
    }}
    updateShadows();
  }}, 50);
}})();
</script>
</body>
</html>'''
    
    return html_out

def main():
    updated = datetime.now().strftime('%Y-%m-%d %H:%M')
    schedule = load_schedule()
    schedule = merge_linetv_schedule(schedule)
    if not schedule: print("No schedule data"); sys.exit(1)
    html = build_html(schedule, updated)
    with open(OUTPUT, 'w', encoding='utf-8') as f: f.write(html)
    total = sum(len(v) for v in schedule.values())
    print(f"HTML generated: {OUTPUT} ({total} anime)")

if __name__ == '__main__':
    main()
