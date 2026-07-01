"""Fetch ani.gamer.com.tw page source via FlareSolverr (bypasses CF challenge)."""
import os, sys, json, re
import requests
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(SCRIPT_DIR, 'source')
FLARESOLVERR_URL = os.environ.get('FLARESOLVERR_URL', 'http://localhost:8191/v1')
TARGET_URL = 'https://ani.gamer.com.tw/'
DAYS = ['週一','週二','週三','週四','週五','週六','週日']

def fetch_source():
    payload = {"cmd": "request.get", "url": TARGET_URL, "maxTimeout": 60000}
    try:
        resp = requests.post(FLARESOLVERR_URL, json=payload, timeout=90)
        data = resp.json()
        if data.get('status') == 'ok':
            return data['solution'].get('response', '')
    except Exception as e:
        print(f"FlareSolverr error: {e}")
    return None

def extract_schedule(html):
    schedule = {}
    for day in DAYS:
        idx = html.find(f'<h3 class="day-title">{day}</h3>')
        if idx == -1: continue
        next_idx = len(html)
        for d2 in DAYS:
            i = html.find(f'<h3 class="day-title">{d2}</h3>', idx+10)
            if i != -1 and i < next_idx: next_idx = i
        block = html[idx:next_idx]
        pattern = r'<span class="text-anime-time">(\d+:\d+)</span>.*?<p class="text-anime-name">(.*?)</p>'
        schedule[day] = [{'time': t, 'name': n.strip()} for t, n in re.findall(pattern, block, re.DOTALL)]
    return schedule

def main():
    os.makedirs(SOURCE_DIR, exist_ok=True)
    today = datetime.now().strftime('%Y-%m-%d')
    
    html = fetch_source()
    if not html or len(html) < 5000:
        print("Failed to fetch page source")
        # Try to use existing source
        source_files = sorted([f for f in os.listdir(SOURCE_DIR) if f.endswith('.html')])
        if source_files:
            with open(os.path.join(SOURCE_DIR, source_files[-1]), 'r', encoding='utf-8') as f:
                html = f.read()
            print(f"Using cached source: {source_files[-1]}")
        else:
            sys.exit(1)
    else:
        with open(os.path.join(SOURCE_DIR, f'{today}.html'), 'w', encoding='utf-8') as f:
            f.write(html)

    schedule = extract_schedule(html)
    if not schedule:
        print("No schedule found")
        sys.exit(1)

    with open(os.path.join(SCRIPT_DIR, 'schedule.json'), 'w', encoding='utf-8') as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)
    
    lines = []
    for day in DAYS:
        entries = schedule.get(day, [])
        lines.append(f'== {day} ({len(entries)}) ==')
        for e in entries:
            lines.append(f'  {e["time"]}  {e["name"]}')
        lines.append('')
    with open(os.path.join(SCRIPT_DIR, 'schedule.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    
    total = sum(len(v) for v in schedule.values())
    print(f"Schedule extracted: {total} anime across {len(schedule)} days")

if __name__ == '__main__':
    main()
