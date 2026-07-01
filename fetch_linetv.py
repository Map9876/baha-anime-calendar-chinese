#!/usr/bin/env python3
"""Fetch LINE TV schedule list, parse all air times, detect current season, and deduplicate with Bahamut data."""
import json, re, urllib.request, os
from datetime import datetime, timezone, timedelta

SCHEDULE_URL = "https://static.linetv.tw/api/configs/schedule/scheduleList.json?t=1"
OUTPUT = "linetv_schedule.json"

TZ = timezone(timedelta(hours=8))

def get_season_range(now=None):
    """Return (start_month, end_month) for current anime season."""
    if now is None:
        now = datetime.now(TZ)
    m = now.month
    if 1 <= m <= 3:   return (1, 3)
    elif 4 <= m <= 6: return (4, 6)
    elif 7 <= m <= 9: return (7, 9)
    else:             return (10, 12)

def in_season_range(start_month, season_start, season_end):
    """Check with grace period (prev month allowed)."""
    if season_start <= start_month <= season_end:
        return True
    prev = season_start - 1 if season_start > 1 else 12
    if start_month == prev:
        return True
    return False

def parse_description(desc, weekday_list, time_str):
    """Parse complex schedule descriptions into structured entries."""
    entries = []
    if not desc:
        return entries
    
    now = datetime.now(TZ)
    year = now.year
    
    # Pattern 1: "M/D首週播出N集，EP1 HH:MM EP2 HH:MM，M/D起，每週X HH:MM���更新"
    # e.g. "7/4首週播出2集，EP1 19:00 EP2 19:30，7/12起，每週日23:00��更新"
    m = re.match(
        r'(\d{1,2})/(\d{1,2})首週播出(\d+)集，EP1\s*(\d{1,2}):(\d{2})\s*EP\d+\s*(\d{1,2}):(\d{2})[，,]\s*(\d{1,2})/(\d{1,2})起，每週([^，\s]+?)\s*(\d{1,2}):(\d{2})[後]?更新',
        desc
    )
    if m:
        sm, sd, eps, h1, m1, h2, m2, rm, rd, wd_cn, rh, rmin = m.groups()
        # First week special
        entries.append({
            "start_date": f"{year}/{int(sm):02d}/{int(sd):02d}",
            "type": "first_week_special",
            "detail": f"EP1 {h1}:{m1} EP2 {h2}:{m2}",
            "episodes": int(eps),
            "times": [f"{int(h1):02d}:{int(m1):02d}", f"{int(h2):02d}:{int(m2):02d}"]
        })
        # Regular weekly
        wd_map = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"日":7}
        entries.append({
            "start_date": f"{year}/{int(rm):02d}/{int(rd):02d}",
            "weekday": wd_map.get(wd_cn),
            "weekday_cn": wd_cn,
            "time": f"{int(rh):02d}:{int(rmin):02d}",
            "frequency": "weekly",
            "type": "regular"
        })
        return entries
    
    # Pattern 2: "M/D首週播出N集，EP1 HH:MM EP2 HH:MM"
    # e.g. "7/4，EP1 19:30更新，7/13起，每週一21:00後���新"
    m = re.match(
        r'(\d{1,2})/(\d{1,2})[，,]\s*EP1\s*(\d{1,2}):(\d{2})更新[，,]\s*(\d{1,2})/(\d{1,2})起，每週([^，\s]+?)\s*(\d{1,2}):(\d{2})[後]?更新',
        desc
    )
    if m:
        sm, sd, h1, m1, rm, rd, wd_cn, rh, rmin = m.groups()
        wd_map = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"日":7}
        entries.append({
            "start_date": f"{year}/{int(sm):02d}/{int(sd):02d}",
            "type": "first_episode",
            "time": f"{int(h1):02d}:{int(m1):02d}"
        })
        entries.append({
            "start_date": f"{year}/{int(rm):02d}/{int(rd):02d}",
            "weekday": wd_map.get(wd_cn),
            "weekday_cn": wd_cn,
            "time": f"{int(rh):02d}:{int(rmin):02d}",
            "frequency": "weekly",
            "type": "regular"
        })
        return entries
    
    # Pattern 3: "M/D首週播出N集，EP1 HH:MM EP2 HH:MM" (simpler)
    m = re.match(r'(\d{1,2})/(\d{1,2})首週播出(\d+)集', desc)
    if m:
        sm, sd, eps = m.groups()
        entries.append({
            "start_date": f"{year}/{int(sm):02d}/{int(sd):02d}",
            "type": "first_week",
            "detail": desc,
            "episodes": int(eps)
        })
        # Also look for regular weekly after
        m2 = re.search(r'(\d{1,2})/(\d{1,2})起，每週([^，\s]+?)\s*(\d{1,2}):(\d{2})[後]?更新', desc)
        if m2:
            rm, rd, wd_cn, rh, rmin = m2.groups()
            wd_map = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"日":7}
            entries.append({
                "start_date": f"{year}/{int(rm):02d}/{int(rd):02d}",
                "weekday": wd_map.get(wd_cn),
                "weekday_cn": wd_cn,
                "time": f"{int(rh):02d}:{int(rmin):02d}",
                "frequency": "weekly",
                "type": "regular"
            })
        return entries
    
    # Pattern 4: "M/D起，每週X HH:MM[後]更新" (standard, with optional 後)
    m = re.match(r'(\d{1,2})/(\d{1,2})起[，,]\s*每週([^，\s]+?)\s*(\d{1,2}):(\d{2})\s*[後]?\s*更新', desc)
    if m:
        sm, sd, wd_cn, h, minute = m.groups()
        wd_map = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"日":7}
        entries.append({
            "start_date": f"{year}/{int(sm):02d}/{int(sd):02d}",
            "weekday": wd_map.get(wd_cn),
            "weekday_cn": wd_cn,
            "time": f"{int(h):02d}:{int(minute):02d}",
            "frequency": "weekly",
            "type": "regular"
        })
        return entries
    
    # Pattern 5: "M/D 起，每週X HH:MM [後]更新N集" (with space, optional 後, extra info like 五集)
    m = re.match(r'(\d{1,2})/(\d{1,2})\s*起[，,]\s*每週([^，\s]+?)\s*(\d{1,2}):(\d{2})\s*[後]?\s*更新', desc)
    if m:
        sm, sd, wd_cn, h, minute = m.groups()
        wd_map = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"日":7}
        entries.append({
            "start_date": f"{year}/{int(sm):02d}/{int(sd):02d}",
            "weekday": wd_map.get(wd_cn),
            "weekday_cn": wd_cn,
            "time": f"{int(h):02d}:{int(minute):02d}",
            "frequency": "weekly",
            "type": "regular"
        })
        return entries
    
    # Pattern 6: "每週X HH:MM���新" (ongoing, no start date)
    m = re.match(r'每週([^，\s]+?)\s*(\d{1,2}):(\d{2})\s*更新', desc)
    if m:
        wd_cn, h, minute = m.groups()
        wd_map = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"日":7}
        entries.append({
            "start_date": None,
            "weekday": wd_map.get(wd_cn),
            "weekday_cn": wd_cn,
            "time": f"{int(h):02d}:{int(minute):02d}",
            "frequency": "weekly",
            "type": "regular"
        })
        return entries
    
    # Pattern 7: Fallback - use weekday list and time
    if weekday_list and time_str:
        wd = weekday_list[0] if weekday_list else None
        wd_map_rev = {1:"一",2:"二",3:"三",4:"四",5:"五",6:"六",7:"日"}
        entries.append({
            "start_date": None,
            "weekday": wd,
            "weekday_cn": wd_map_rev.get(wd),
            "time": time_str,
            "frequency": "weekly",
            "type": "regular",
            "note": f"raw: {desc}"
        })
        return entries
    
    # Save raw if unparseable
    entries.append({"raw": desc, "type": "unknown"})
    return entries


def normalize_title(title):
    """Normalize anime title for fuzzy matching (dedup with Bahamut)."""
    t = title.strip()
    t = re.sub(r'[\s　]+', ' ', t)  # normalize spaces
    t = re.sub(r'[「」『』《》（）()【】\[\]]', '', t)  # remove brackets
    t = t.replace('～', '~').replace('‧', '·')
    return t.lower()

def similarity(a, b):
    """Simple title similarity check for dedup."""
    a = normalize_title(a)
    b = normalize_title(b)
    if a == b:
        return 1.0
    # Check if one contains the other
    if a in b or b in a:
        return 0.9
    # Check with season/episode markers stripped
    a_stripped = re.sub(r'[ 　][第季]\S+', '', a)
    b_stripped = re.sub(r'[ 　][第季]\S+', '', b)
    if a_stripped == b_stripped:
        return 0.95
    if a_stripped in b_stripped or b_stripped in a_stripped:
        return 0.85
    return 0.0


def fetch():
    print(f"Fetching schedule from {SCHEDULE_URL}")
    req = urllib.request.Request(SCHEDULE_URL, headers={
        "User-Agent": "Mozilla/5.0 (compatible; AnimeCalendar/1.0)"
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    
    all_items = data.get("datas", [])
    print(f"Total schedule items: {len(all_items)}")
    
    now = datetime.now(TZ)
    sm, em = get_season_range(now)
    print(f"Current season: months {sm}-{em}")
    
    # Parse all anime entries
    anime_items = []
    for item in all_items:
        channel_names = item.get("channelName", [])
        if "動畫" not in channel_names:
            continue
        
        desc = item.get("description", "")
        weekday_list = item.get("weekday", [])
        time_str = item.get("time", "")
        
        parsed = parse_description(desc, weekday_list, time_str)
        
        # Determine season: prefer parsed description start_date over startTime
        # (LINE TV sets many startTime=2026-01-01 as default for 7月番)
        start_month = None
        for p in parsed:
            sd = p.get("start_date")
            if sd:
                try:
                    start_month = int(sd.split("/")[1])
                    break
                except (IndexError, ValueError):
                    pass
        
        if start_month is None:
            start_ts = item.get("startTime")
            if start_ts:
                start_dt = datetime.fromtimestamp(start_ts / 1000, tz=TZ)
                start_month = start_dt.month
        
        entry = {
            "drama_id": str(item["id"]),
            "title": item["name"],
            "horizontal_poster": item.get("horizontalPosterUrl", ""),
            "vertical_poster": item.get("verticalPosterUrl", ""),
            "weekday_list": weekday_list,
            "time": time_str,
            "description": desc,
            "start_timestamp": item.get("startTime"),
            "end_timestamp": item.get("endTime"),
            "channel_name": channel_names,
            "start_month": start_month,
            "start_month_source": "parsed" if any(p.get("start_date") for p in parsed) else "timestamp",
            "in_current_season": in_season_range(start_month, sm, em) if start_month else False,
            "parsed_schedule": parsed,
        }
        anime_items.append(entry)
    
    print(f"Total anime entries: {len(anime_items)}")
    in_season = [a for a in anime_items if a["in_current_season"]]
    print(f"In current season: {len(in_season)}")
    
    # Sort: current season first, then by weekday/time
    def sort_key(x):
        season_sort = 0 if x["in_current_season"] else 1
        wd = x["weekday_list"][0] if x.get("weekday_list") else 99
        t = x.get("time") or "99:99"
        return (season_sort, wd, t)
    anime_items.sort(key=sort_key)
    
    # Save full data
    output = {
        "fetched_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "Asia/Taipei (UTC+8)",
        "season": f"{sm}-{em}",
        "total": len(anime_items),
        "current_season_count": len(in_season),
        "anime": anime_items
    }
    
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"Saved to {OUTPUT}")
    
    # Print summary
    wd_cn = {1:"一",2:"二",3:"三",4:"四",5:"五",6:"六",7:"日"}
    by_day = {}
    for a in anime_items:
        if not a["in_current_season"]:
            continue
        for wd in (a.get("weekday_list") or [99]):
            by_day.setdefault(wd, []).append(a)
    
    print(f"\n=== 当前季度 ({sm}-{em}) ===")
    for wd in sorted(by_day.keys()):
        label = f"周{wd_cn.get(wd, '?')}" if wd != 99 else "其他"
        print(f"\n[{label}]")
        for a in sorted(by_day[wd], key=lambda x: x.get("time") or "99:99"):
            t = a.get("time") or "??:??"
            desc_preview = a["description"][:40] if a["description"] else ""
            print(f"  {t:>5}  {a['title']:30s}  {desc_preview}")
    
    # Print non-current season (cross-season)
    cross = [a for a in anime_items if not a["in_current_season"]]
    if cross:
        print(f"\n=== 跨季度跟播 ({len(cross)}部) ===")
        for a in cross:
            print(f"  {a['title']:30s}  startMonth={a['start_month']}  {a['description'][:40]}")
    
    return output


def dedup_with_bahamut(linetv_data, bahamut_path="schedule.json"):
    """Deduplicate LINE TV data against Bahamut schedule using fuzzy title matching."""
    if not os.path.exists(bahamut_path):
        print(f"Bahamut data not found at {bahamut_path}, skipping dedup")
        return linetv_data
    
    with open(bahamut_path, encoding="utf-8") as f:
        bahamut = json.load(f)
    
    bahamut_titles = set()
    for day_entries in bahamut.values():
        for entry in day_entries:
            bahamut_titles.add(normalize_title(entry.get("name", "")))
    
    print(f"\n=== 去重分析 ===")
    print(f"Bahamut titles: {len(bahamut_titles)}")
    
    matched = []
    unmatched = []
    for anime in linetv_data["anime"]:
        title_norm = normalize_title(anime["title"])
        best_score = 0
        best_match = None
        for bt in bahamut_titles:
            score = similarity(title_norm, bt)
            if score > best_score:
                best_score = score
                best_match = bt
        
        if best_score >= 0.85:
            anime["bahamut_match"] = {"matched": True, "score": best_score, "bahamut_title": best_match}
            matched.append(anime)
        else:
            anime["bahamut_match"] = {"matched": False, "score": best_score}
            unmatched.append(anime)
    
    print(f"Matched: {len(matched)}, Unmatched (LINE TV only): {len(unmatched)}")
    if unmatched:
        print("LINE TV only:")
        for a in unmatched:
            print(f"  {a['title']:30s}  {a['description'][:40]}")
    
    return linetv_data


if __name__ == "__main__":
    data = fetch()
    # Also try dedup if Bahamut schedule.json exists in same dir
    script_dir = os.path.dirname(os.path.abspath(__file__))
    bahamut_path = os.path.join(script_dir, "schedule.json")
    dedup_with_bahamut(data, bahamut_path)
