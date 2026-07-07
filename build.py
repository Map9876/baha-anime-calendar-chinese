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

def normalize_title(t):
    return re.sub(r'[\s　]+', '', t).strip().lower()

def title_exists(titles, name):
    """Check if name already exists in a list of entries (fuzzy)."""
    n = normalize_title(name)
    for e in titles:
        if normalize_title(e.get('name','')) == n:
            return True
    return False

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
    wd_from_date = {0:'一',1:'二',2:'三',3:'四',4:'五',5:'六',6:'日'}
    for anime in linetv_data.get('anime', []):
        # Skip if not current season or already in Bahamut
        if not anime.get('in_current_season'):
            continue
        if anime.get('bahamut_match', {}).get('matched'):
            continue
        
        parsed = anime.get('parsed_schedule', [])
        # Check if this anime has first_week_special/first_episode entries
        has_special = any(p.get('type') in ('first_week_special', 'first_episode') for p in parsed)
        
        for entry in parsed:
            # Handle first_week_special: create entries for each time
            if entry.get('type') in ('first_week_special', 'first_episode'):
                times = entry.get('times', [])
                if entry.get('time'):  # first_episode has single time
                    times = [entry['time']]
                start_date_str = entry.get('start_date', '')
                if not start_date_str or not times:
                    continue
                try:
                    sd = datetime.strptime(start_date_str, '%Y/%m/%d')
                    wd_cn = wd_from_date[sd.weekday()]
                except (ValueError, KeyError):
                    continue
                day_key = wd_key_map[wd_cn]
                for t in times:
                    new_entry = {
                        'time': t,
                        'name': anime['title'],
                        'source': 'linetv',
                        'start_date': start_date_str,
                        'note': entry.get('detail', '首播')
                    }
                    if not title_exists(schedule.get(day_key, []), new_entry['name']):
                        schedule.setdefault(day_key, []).append(new_entry)
                        added += 1
                continue
            
            # Regular weekly entries
            if entry.get('type') != 'regular':
                continue
            wd_cn = entry.get('weekday_cn')
            if not wd_cn or wd_cn not in wd_key_map:
                continue
            day_key = wd_key_map[wd_cn]
            # Mark as premiere only if no special first-week entry exists
            # (otherwise premiere is already marked on the special entry)
            is_premiere = not has_special
            new_entry = {
                'time': entry['time'],
                'name': anime['title'],
                'source': 'linetv',
                'start_date': entry.get('start_date', ''),
                'is_premiere': is_premiere
            }
            # Avoid duplicates (use fuzzy title match)
            if not title_exists(schedule.get(day_key, []), new_entry['name']):
                schedule.setdefault(day_key, []).append(new_entry)
                added += 1
    
    # Sort each day by time
    for day_key in schedule:
        schedule[day_key].sort(key=lambda x: x['time'])
    
    print(f"Removed {removed} cross-season entries, merged {added} LINE TV entries")
    return schedule


def build_html(schedule, updated):
    """Build Bilibili-style anime timeline page."""
    from datetime import timezone, timedelta
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
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
    
    # Current time
    now_str = f"{now.hour}:{now.minute:02d}"
    now_min = now.hour * 60 + now.minute
    
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
        date_str = dt.strftime('%m/%d')
        iso_str = dt.strftime('%Y-%m-%d')
        dot_html = '<div class="today-dot"></div>' if is_today else ''
        date_tabs += f'<div class="date-tab{active_cls}" data-date="{iso_str}">{dot_html}<div class="date-num">{date_str}</div><div class="date-weekday">{day_label}</div></div>'
    
    # Find today's index for inline track positioning
    try:
        init_idx = [i for i, dt in enumerate(all_dates) if dt.date() == now.date()][0]
    except IndexError:
        init_idx = 0
    
    # Map anime entries to dates by weekday
    date_entries = {}
    for dt in all_dates:
        date_entries[dt.strftime('%Y-%m-%d')] = []
    
    for i, day in enumerate(DAYS):
        entries = schedule.get(day, [])
        if not entries:
            continue
        # Find the date in our range that matches this weekday
        matching_dates = [dt for dt in all_dates if dt.weekday() == i]
        if not matching_dates:
            continue
        for entry in entries:
            start_date_str = entry.get('start_date', '')
            is_one_time = bool(entry.get('note'))
            
            if is_one_time:
                # One-time entries (special premieres): only show on the first matching date
                if start_date_str and entry.get('source') == 'linetv':
                    try:
                        sd = datetime.strptime(start_date_str, '%Y/%m/%d').date()
                        future_dates = [dt for dt in matching_dates if dt.date() >= sd]
                        target_idx = matching_dates.index(future_dates[0]) if future_dates else -1
                    except ValueError:
                        target_idx = 0
                else:
                    future_dates = [dt for dt in matching_dates if dt.date() >= now.date() - timedelta(days=1)]
                    target_idx = matching_dates.index(future_dates[0]) if future_dates else -1
                if target_idx < 0:
                    target_idx = len(matching_dates) - 1
                target_date = matching_dates[target_idx]
                key = target_date.strftime('%Y-%m-%d')
                if key in date_entries:
                    date_entries[key].append(entry)
            else:
                # Weekly entries: repeat on ALL matching dates >= start_date
                start_date = None
                if start_date_str and entry.get('source') == 'linetv':
                    try:
                        start_date = datetime.strptime(start_date_str, '%Y/%m/%d').date()
                    except ValueError:
                        pass
                
                first_added = False
                for dt in matching_dates:
                    if start_date and dt.date() < start_date:
                        continue
                    # Bahamut entries (no start_date): show from today onwards
                    if not start_date and dt.date() < now.date() - timedelta(days=1):
                        continue
                    key = dt.strftime('%Y-%m-%d')
                    if key in date_entries:
                        # Copy entry for each date to allow per-date flag modification
                        new_entry = dict(entry)
                        # Only show premiere badge on the first occurrence
                        if first_added:
                            new_entry['is_premiere'] = False
                            new_entry.pop('note', None)
                        first_added = True
                        date_entries[key].append(new_entry)
    
    # Generate timeline content for each date
    timelines = {}
    for dt in all_dates:
        key = dt.strftime('%Y-%m-%d')
        entries = date_entries.get(key, [])
        if not entries:
            timelines[key] = '<div class="empty-day">当天无更新</div>'
            continue
        html = ""
        for entry in entries:
            name_simple = to_simple_chinese(entry['name'])
            time_str = entry['time']
            cover = covers.get(entry['name'], '')
            cover_html = f'<img src="{cover}" class="timeline-cover" onerror="this.style.display=\'none\'">' if cover else ''
            # Show premiere badge: special entries or regular entries with is_premiere flag
            sd = entry.get('start_date', '')
            is_premiere = bool(entry.get('note')) or (entry.get('is_premiere') and sd and entry.get('source') == 'linetv')
            badge = '<span class="timeline-badge">首播</span>' if is_premiere else ''
            html += f'''
            <div class="timeline-item" data-time="{time_str}">
              <div class="timeline-left">
                <div class="timeline-cir"></div>
                <div class="timeline-line"></div>
                <div class="timeline-time">{time_str}</div>
              </div>
              <div class="timeline-right">
                {cover_html}
                <div class="timeline-title">{name_simple}{badge}</div>
              </div>
            </div>'''
        timelines[key] = html
    
    # Content divs
    content_divs = ""
    for dt in all_dates:
        key = dt.strftime('%Y-%m-%d')
        is_today = (dt.date() == now.date())
        active_cls = ' active' if is_today else ''
        content_divs += f'<div class="timeline-content{active_cls}" data-date="{key}">{timelines[key]}</div>'
    
    total = sum(len(v) for v in schedule.values())
    
    html_out = f'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<meta name="description" content="巴哈姆特动画疯 &amp; LINE TV 新番时间表 - 每周动漫日历/周历，收录当前季度最新番剧更新时间，支持左右滑动切换日期">
<meta name="keywords" content="巴哈姆特动画疯,巴哈姆特動畫瘋,番剧,新番,动漫,日历,周历,新番表,时间表,新番時間表,更新,季度,LINE TV,anime schedule">
<title>新番时间表 - 巴哈姆特动画疯 &amp; LINE TV 动漫日历</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif; background:#f5f5f5; color:#333; }}
.header {{ position:sticky; top:0; z-index:10; background:#fff; border-bottom:1px solid #eee; padding:6px 12px 4px; display:flex; justify-content:space-between; align-items:flex-start; }}
.header-left {{ min-width:0; }}
.header-left h1 {{ font-size:17px; color:#333; font-weight:700; }}
.header-left .meta {{ font-size:11px; color:#999; }}
.header-right {{ display:flex; align-items:center; gap:4px; flex-shrink:1; min-width:0; margin-left:12px; padding:4px 4px 0 0; }}
.header-right a {{ display:flex; align-items:center; gap:4px; text-decoration:none; color:#333; }}
.github-icon {{ flex-shrink:0; width:16px; height:16px; }}
.github-badge {{ font-size:12px; color:#57606a; border:1px solid #d0d7de; border-radius:6px; padding:1px 8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:140px; }}
.github-badge:hover {{ background:#f6f8fa; }}
.date-bar-wrap {{ position:relative; box-shadow:0 -3px 6px rgba(0,0,0,.10), 0 2px 4px rgba(0,0,0,.08); }}
.date-bar {{ position:sticky; top:35px; z-index:9; background:#fff; display:flex; overflow-x:auto; -webkit-overflow-scrolling:touch; }}
.date-bar-shadow-l {{ position:absolute; top:0; left:0; bottom:0; width:16px; background:linear-gradient(to right,rgba(0,0,0,.12),transparent); z-index:10; pointer-events:none; opacity:0; transition:opacity .15s; }}
.date-bar-shadow-r {{ position:absolute; top:0; right:0; bottom:0; width:16px; background:linear-gradient(to left,rgba(0,0,0,.12),transparent); z-index:10; pointer-events:none; opacity:0; transition:opacity .15s; }}
.date-bar::-webkit-scrollbar {{ display:none; }}
.date-tab {{ flex:0 0 52px; min-width:52px; padding:8px 2px; text-align:center; cursor:pointer; -webkit-tap-highlight-color:transparent; position:relative; }}
.date-tab.active {{ }}
.date-tab.active .date-num {{ color:#fb7299; font-weight:700; }}
.date-tab.active .date-weekday {{ color:#fff; background:#fb7299; border-radius:999px; display:inline-flex; align-items:center; justify-content:center; min-width:28px; min-height:24px; padding:0 7px; font-size:13px; }}
.today-dot {{ width:5px; height:5px; background:#fb7299; border-radius:50%; position:absolute; top:3px; left:50%; margin-left:-2.5px; }}
.date-num {{ font-size:13px; color:#999; margin-bottom:1px; line-height:16px; white-space:nowrap; }}
.date-weekday {{ font-size:15px; color:#333; line-height:20px; }}
.timeline-pager {{ overflow:hidden; position:relative; touch-action:pan-y; overscroll-behavior:none; }}
.timeline-track {{ display:flex; transition:transform .35s cubic-bezier(.25,.46,.45,.94); will-change:transform; }}
.timeline-content {{ flex:0 0 100%; min-width:0; padding:0 16px; }}
.empty-day {{ text-align:center; padding:60px 20px; color:#999; font-size:16px; }}
.timeline-item {{ display:flex; padding:12px 0; position:relative; }}
.timeline-item.now-airing {{ background:#fff0f5; margin:0 -16px; padding:12px 16px; border-radius:8px; }}
.timeline-left {{ flex:0 0 56px; display:flex; flex-direction:column; align-items:center; position:relative; }}
.timeline-cir {{ width:8px; height:8px; border-radius:50%; background:#ddd; z-index:1; flex-shrink:0; }}
.timeline-item.now-airing .timeline-cir {{ width:10px; height:10px; background:#fb7299; box-shadow:0 0 6px rgba(251,114,153,.5); }}
.timeline-line {{ width:1px; flex:1; background:#e0e0e0; min-height:20px; }}
.timeline-item:last-child .timeline-line {{ display:none; }}
.timeline-time {{ font-size:14px; color:#666; margin-top:4px; white-space:nowrap; font-weight:600; }}
.timeline-item.now-airing .timeline-time {{ color:#fb7299; font-weight:600; }}
.timeline-right {{ flex:1; margin-left:12px; padding-bottom:8px; border-bottom:1px solid #f0f0f0; }}
.timeline-item:last-child .timeline-right {{ border-bottom:none; }}
.timeline-cover {{ display:block; width:80px; height:auto; border-radius:4px; margin-bottom:6px; }}
.timeline-title {{ font-size:16px; color:#333; line-height:1.5; }}
.timeline-item.now-airing .timeline-title {{ color:#fb7299; }}
.timeline-badge {{ display:inline-block; font-size:11px; color:#fb7299; border:1px solid #fb7299; border-radius:3px; padding:0 4px; margin-left:4px; vertical-align:middle; line-height:16px; }}
.footer {{ text-align:center; padding:16px; font-size:12px; color:#999; }}
.footer a {{ color:#999; text-decoration:underline; }}
.now-label-bar {{ position:relative; margin:8px 0; text-align:center; border-top:1px dashed #fb7299; padding-top:4px; }}
.now-label-text {{ font-size:13px; color:#fb7299; background:#fff; padding:0 8px; display:inline-block; }}
.swipe-hint {{ position:fixed; bottom:20px; left:50%; transform:translateX(-50%); background:rgba(0,0,0,.55); color:#fff; font-size:13px; padding:8px 18px; border-radius:20px; z-index:100; pointer-events:none; transition:opacity .5s; white-space:nowrap; max-width:calc(100vw - 40px); overflow:hidden; text-overflow:ellipsis; }}
.swipe-hint.hide {{ opacity:0; }}
@media (max-width:480px) {{
  .timeline-left {{ flex-basis:48px; }}
  .timeline-cover {{ width:64px; }}
  .timeline-title {{ font-size:15px; }}
}}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <h1>新番时间表</h1>
    <div class="meta">更新: {updated}</div>
  </div>
  <div class="header-right">
    <a href="https://github.com/Map9876/baha-anime-calendar-chinese" target="_blank" rel="noopener" title="Map9876/baha-anime-calendar-chinese">
      <svg class="github-icon" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
      <span class="github-badge">Map9876/baha-anime-calendar-chinese</span>
    </a>
  </div>
</div>

<div class="date-bar-wrap">
  <div class="date-bar-shadow-l"></div>
  <div class="date-bar-shadow-r"></div>
  <div class="date-bar" id="dateBar">
    {date_tabs}
  </div>
</div>

<div class="timeline-pager" id="timelinePager">
  <div class="timeline-track" id="timelineTrack" style="transform:translateX(-{init_idx}00%)">
    {content_divs}
  </div>
</div>

<div class="footer">
  <div><a href="https://ani.gamer.com.tw/">巴哈姆特動畫瘋</a> · <a href="https://www.linetv.tw/channel/2/genre/367?channel_id=2&genre_token=367&page=1&sort=LAST_PUBLISH&source=DRAMA_PAGE_CATEGORY_LABEL">LINE TV 動畫分類</a></div>
  <div style="margin-top:4px"><a href="https://github.com/Map9876/baha-anime-calendar-chinese">GitHub</a></div>
  <div id="footerSwipeHint" style="margin-top:4px;font-size:10px;color:#bbb;">← 左右滑动切换日期 →</div>
</div>
<div id="swipeHint" class="swipe-hint">← 左右滑动切换日期 →</div>

<script>
(function() {{
  var tabs = document.querySelectorAll('.date-tab');
  var pages = document.querySelectorAll('.timeline-content');
  var bar = document.getElementById('dateBar');
  var pager = document.getElementById('timelinePager');
  var track = document.getElementById('timelineTrack');
  
  function getTaiwanNow() {{
    var s = new Date().toLocaleString('en-CA', {{
      timeZone: 'Asia/Taipei',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
    }});
    var m = s.match(/(\\d{{4}})-(\\d{{2}})-(\\d{{2}}), (\\d{{2}}):(\\d{{2}})/);
    if (!m) return {{ iso: '', hour: 0, minute: 0 }};
    return {{
      iso: m[1] + '-' + m[2] + '-' + m[3],
      hour: parseInt(m[4]),
      minute: parseInt(m[5])
    }};
  }}
  
  function updateNow() {{
    var tw = getTaiwanNow();
    var nowMin = tw.hour * 60 + tw.minute;
    var nowStr = tw.hour + ':' + String(tw.minute).padStart(2, '0');
    
    // Remove old now markers
    document.querySelectorAll('.now-label-bar').forEach(function(el) {{ el.remove(); }});
    document.querySelectorAll('.timeline-item.now-airing').forEach(function(el) {{
      el.classList.remove('now-airing');
    }});
    
    var todayContent = document.querySelector('.timeline-content[data-date="' + tw.iso + '"]');
    if (!todayContent) return;
    
    var items = todayContent.querySelectorAll('.timeline-item');
    if (!items.length) return;
    
    var insertBefore = null;
    items.forEach(function(item) {{
      var time = item.getAttribute('data-time');
      if (!time) return;
      var parts = time.split(':');
      var entryMin = parseInt(parts[0]) * 60 + parseInt(parts[1]);
      if (Math.abs(entryMin - nowMin) <= 15) {{
        item.classList.add('now-airing');
      }}
      if (entryMin > nowMin && !insertBefore) {{
        insertBefore = item;
      }}
    }});
    
    var label = document.createElement('div');
    label.className = 'now-label-bar';
    label.innerHTML = '<span class="now-label-text">现在 ' + nowStr + '</span>';
    
    if (insertBefore) {{
      todayContent.insertBefore(label, insertBefore);
    }} else {{
      todayContent.appendChild(label);
    }}
  }}
  
  function switchDay(idx, duration) {{
    // duration: false=instant, true=normal(.35s), number=seconds
    if (duration === false || duration === 0) {{
      track.style.transition = 'none';
    }} else if (duration === true) {{
      track.style.transition = 'transform .35s cubic-bezier(.25,.46,.45,.94)';
    }} else {{
      track.style.transition = 'transform ' + duration + 's cubic-bezier(.25,.46,.45,.94)';
    }}
    track.style.transform = 'translateX(' + (-idx * 100) + '%)';
    
    // Sync swipe handler's currentPage with tab clicks
    currentPage = idx;
    
    // Update tabs
    tabs.forEach(function(t,i) {{ t.classList.toggle('active',i===idx); }});
    
    // Scroll date bar — instant for tab clicks, smooth for swipes
    var tab = tabs[idx];
    if (tab) {{
      var scrollLeft = tab.offsetLeft - bar.offsetWidth/2 + tab.offsetWidth/2;
      var scrollBehavior = (duration === 0) ? 'auto' : 'smooth';
      bar.scrollTo({{ left:Math.max(0,scrollLeft), behavior:scrollBehavior }});
    }}
    updateNow();
  }}
  
  // Date tab clicks — very fast animation like Bilibili app
  tabs.forEach(function(tab,i) {{
    tab.addEventListener('click',function(){{ switchDay(i, 0); }});
  }});
  
  // Touch swipe — Bilibili Compose 风格: 方向锁定，不重新评估
  var startX = 0, startY = 0, currentPage = 0;
  var isHorizontal = false, isActive = false, lastX = 0;
  var velPoints = [];
  
  
  // 服务端已设置active（build.py按构建时间计算），客户端不做覆盖
  tabs.forEach(function(t,i) {{ if(t.classList.contains("active")) currentPage=i; }});
  if (!document.querySelector(".date-tab.active")) {{
    currentPage = 0;
    tabs[0].classList.add("active");
  }}
  updateNow();
  updateShadows();
  
  function handleTouchStart(e) {{
    // Skip if touch is on date bar
    if (e.target.closest('#dateBar') || e.target.closest('.date-bar')) {{
      isActive = false;
      return;
    }}
    var t = e.touches[0];
    startX = t.clientX;
    startY = t.clientY;
    lastX = startX;
    isHorizontal = false;
    isActive = true;
    velPoints = [];
    track.style.transition = 'none';
  }}
  
  function handleTouchMove(e) {{
    if (!isActive) return;
    var t = e.touches[0];
    var cx = t.clientX, cy = t.clientY;
    var deltaX = cx - startX;
    var deltaY = cy - startY;
    var absX = Math.abs(deltaX), absY = Math.abs(deltaY);
    
    // 还没有锁定方向: 等移动 >10px 后决定
    if (!isHorizontal && absY <= 10 && absX <= 10) return;
    
    if (!isHorizontal) {{
      // 第一次判断: 锁定方向（Compose 风格，不重新评估）
      if (absY > absX) {{
        // 垂直 → 释放给浏览器原生滚动
        isActive = false;
        track.style.transition = 'transform .35s cubic-bezier(.25,.46,.45,.94)';
        track.style.transform = 'translateX(' + (-currentPage * 100) + '%)';
        return;
      }} else {{
        // 水平 → 锁定横向模式
        isHorizontal = true;
        e.preventDefault();
      }}
    }}
    
    // 水平跟手 + 速度采样
    if (isHorizontal) {{
      e.preventDefault();
      if (Math.abs(cx - lastX) >= 5) {{
        velPoints.push({{ x: cx, t: Date.now() }});
        if (velPoints.length > 7) velPoints.shift();
        lastX = cx;
      }}
      track.style.transform = 'translateX(' + (-currentPage * 100 + deltaX / pager.offsetWidth * 100) + '%)';
    }}
  }}
  
  function handleTouchEnd(e) {{
    if (!isActive) return;
    if (!isHorizontal) return;
    isActive = false;
    
    var endX = e.changedTouches[0].clientX;
    var deltaX = endX - startX;
    var absDelta = Math.abs(deltaX);
    var pageW = pager.offsetWidth;
    
    // 计算速度 (最后 3 个采样点)
    var vel = 0;
    if (velPoints.length >= 2) {{
      var n = velPoints.length;
      var first = velPoints[Math.max(0, n - 3)];
      var last = velPoints[n - 1];
      var dt = last.t - first.t;
      if (dt > 5) vel = (last.x - first.x) / dt;
    }}
    
    var shouldSwitch = false;
    var direction = 0;
    var absVel = Math.abs(vel);
    
    // 速度优先，距离兜底
    if (absVel > 0.12) {{
      shouldSwitch = true;
      direction = vel > 0 ? -1 : 1;
    }} else if (absDelta > pageW * 0.2) {{
      shouldSwitch = true;
      direction = deltaX > 0 ? -1 : 1;
    }}
    
    if (shouldSwitch) {{
      e.preventDefault();
      var newPage = currentPage + direction;
      if (newPage >= 0 && newPage < tabs.length) {{
        currentPage = newPage;
        switchDay(newPage, true);
        return;
      }}
    }}
    
    // Snap back
    switchDay(currentPage, true);
  }}
  
  // Attach to track element only — avoids conflict with touch-action:pan-y
  track.addEventListener('touchstart', handleTouchStart, {{ passive: true }});
  track.addEventListener('touchmove', handleTouchMove, {{ passive: false }});
  track.addEventListener('touchend', handleTouchEnd, {{ passive: true }});
  
  // Scroll shadows for date bar
  var shadowL = document.querySelector('.date-bar-shadow-l');
  var shadowR = document.querySelector('.date-bar-shadow-r');
  function updateShadows() {{
    shadowL.style.opacity = bar.scrollLeft > 2 ? '1' : '0';
    shadowR.style.opacity = bar.scrollLeft < bar.scrollWidth - bar.clientWidth - 2 ? '1' : '0';
  }}
  bar.addEventListener('scroll', updateShadows);
  
  // Init: show now marker and shadows
  
  // Update now marker every 60 seconds
  setInterval(updateNow, 60000);
  
  // Swipe hint — once per browser (localStorage)
  var hint = document.getElementById('swipeHint');
  if (hint && !localStorage.getItem('swipeHintShown')) {{
    localStorage.setItem('swipeHintShown', '1');
    setTimeout(function() {{ hint.classList.add('hide'); }}, 4000);
    // Hide on first touch
    window.addEventListener('touchstart', function() {{
      hint.classList.add('hide');
    }}, {{ once: true }});
  }} else if (hint) {{
    hint.classList.add('hide');
  }}
}})();
</script>
<script>
if ('serviceWorker' in navigator) {{
  navigator.serviceWorker.register('sw.js');
}}
</script>
</body>
</html>'''
    
    return html_out

def main():
    from datetime import timezone, timedelta
    tz = timezone(timedelta(hours=8))
    updated = datetime.now(tz).strftime('%Y-%m-%d %H:%M')
    schedule = load_schedule()
    schedule = merge_linetv_schedule(schedule)
    if not schedule: print("No schedule data"); sys.exit(1)
    html = build_html(schedule, updated)
    with open(OUTPUT, 'w', encoding='utf-8') as f: f.write(html)
    total = sum(len(v) for v in schedule.values())
    print(f"HTML generated: {OUTPUT} ({total} anime)")

def export_api(schedule):
    """Export schedule as API JSON files for developers."""
    import shutil
    api_dir = os.path.join(SCRIPT_DIR, 'api')
    os.makedirs(api_dir, exist_ok=True)
    
    # 1. 完整整合版 (中文名)
    merged = {'updated': updated, 'total': sum(len(v) for v in schedule.values()), 'schedule': schedule}
    with open(os.path.join(api_dir, '最新baha和line整合时间表.json'), 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    
    # 2. calendar-newest.json (开发者直链)
    calendar = {'updated': updated, 'total': sum(len(v) for v in schedule.values()), 'schedule': schedule}
    with open(os.path.join(api_dir, 'calendar-newest.json'), 'w', encoding='utf-8') as f:
        json.dump(calendar, f, ensure_ascii=False, indent=2)
    
    # 3. Bahamut only
    baha_path = os.path.join(SCRIPT_DIR, 'linetv_schedule.json')
    baha_schedule = {}
    if os.path.exists(baha_path):
        with open(baha_path, 'r') as f:
            linetv_data = json.load(f)
        # Extract Bahamut-only entries
        for day in DAYS:
            baha_schedule[day] = [e for e in schedule.get(day, []) if e.get('source') != 'linetv']
    else:
        baha_schedule = schedule
    baha_total = sum(len(v) for v in baha_schedule.values())
    with open(os.path.join(api_dir, 'baha.json'), 'w', encoding='utf-8') as f:
        json.dump({'updated': updated, 'total': sum(len(v) for v in baha_schedule.values()), 'schedule': baha_schedule}, f, ensure_ascii=False, indent=2)
    
    # 4. LINE TV only
    linetv_schedule = {}
    if os.path.exists(baha_path):
        for day in DAYS:
            linetv_schedule[day] = [e for e in schedule.get(day, []) if e.get('source') == 'linetv']
    linetv_total = sum(len(v) for v in linetv_schedule.values())
    with open(os.path.join(api_dir, 'line_tv.json'), 'w', encoding='utf-8') as f:
        json.dump({'updated': updated, 'total': sum(len(v) for v in linetv_schedule.values()), 'schedule': linetv_schedule}, f, ensure_ascii=False, indent=2)
    
    print(f"API JSONs exported to {api_dir}/")
    for f in os.listdir(api_dir):
        sz = os.path.getsize(os.path.join(api_dir, f)) / 1024
        print(f"  {f}: {sz:.1f} KB")

if __name__ == '__main__':
    main()
    from datetime import timezone, timedelta
    tz = timezone(timedelta(hours=8))
    updated = datetime.now(tz).strftime('%Y-%m-%d %H:%M')
    schedule = load_schedule()
    schedule = merge_linetv_schedule(schedule)
    if schedule:
        export_api(schedule)
