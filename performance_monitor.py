#!/usr/bin/env python3
"""
LUCID REALMS — Performance Monitor Agent
- Reads analytics_log.json for recent video IDs
- Fetches real view counts from YouTube Analytics API
- Detects 5+ consecutive low-view videos (< LOW_VIEW_THRESHOLD after MIN_AGE_HOURS)
- On alert: uses gpt-4o to generate a content pivot strategy
- Writes alert + pivot to config.json so generate_and_upload.py adapts immediately
"""

import os, json, time, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

OPENAI_API_KEY    = os.environ["OPENAI_API_KEY"]
YT_CLIENT_ID      = os.environ["YOUTUBE_CLIENT_ID"]
YT_CLIENT_SECRET  = os.environ["YOUTUBE_CLIENT_SECRET"]
YT_REFRESH_TOKEN  = os.environ["YOUTUBE_REFRESH_TOKEN"]

CONFIG_PATH       = Path("config.json")
ANALYTICS_LOG     = Path("analytics_log.json")
OPENAI_HEADERS    = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

LOW_VIEW_THRESHOLD = 100
MIN_AGE_HOURS      = 48
CONSECUTIVE_LIMIT  = 5

def get_access_token():
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": YT_CLIENT_ID, "client_secret": YT_CLIENT_SECRET,
        "refresh_token": YT_REFRESH_TOKEN, "grant_type": "refresh_token"
    })
    resp.raise_for_status()
    return resp.json()["access_token"]

def get_video_views(video_ids, token):
    if not video_ids:
        return {}
    views = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            headers={"Authorization": f"Bearer {token}"},
            params={"part": "statistics", "id": ",".join(batch)}
        )
        if not resp.ok:
            print(f"  YouTube API error: {resp.status_code}")
            continue
        for item in resp.json().get("items", []):
            views[item["id"]] = int(item["statistics"].get("viewCount", 0))
        time.sleep(0.3)
    return views

def load_recent_videos():
    if not ANALYTICS_LOG.exists():
        return []
    log = json.loads(ANALYTICS_LOG.read_text())
    now = datetime.now(timezone.utc)
    eligible = []
    for entry in log:
        if not entry.get("video_id"):
            continue
        try:
            upload_dt = datetime.strptime(
                entry["date"] + " " + entry.get("time_utc", "00:00"), "%Y-%m-%d %H:%M"
            ).replace(tzinfo=timezone.utc)
            if (now - upload_dt).total_seconds() / 3600 >= MIN_AGE_HOURS:
                eligible.append(entry)
        except Exception:
            continue
    return sorted(eligible, key=lambda x: x["date"] + x.get("time_utc", ""))

def check_consecutive_low(videos, views_map):
    streak = 0
    low_entries = []
    for entry in reversed(videos):
        v = views_map.get(entry["video_id"])
        if v is None:
            break
        if v < LOW_VIEW_THRESHOLD:
            streak += 1
            low_entries.append({**entry, "views": v})
        else:
            break
    return streak, list(reversed(low_entries))

def generate_pivot_strategy(low_entries, current_config):
    current_themes  = current_config.get("content_strategy", {}).get("top_performing_themes", [])
    trend_research  = current_config.get("trend_research", {})
    competitor_gaps = trend_research.get("competitor_gaps", "N/A")
    viral_hooks     = trend_research.get("viral_hook_patterns", [])
    low_titles = [f"- '{e['title_a']}' -> {e['views']} views" for e in low_entries]
    prompt = f"""You are the emergency strategy director for LUCID REALMS, a YouTube Shorts channel for surreal AI art.

PROBLEM: The last {len(low_entries)} videos all got under {LOW_VIEW_THRESHOLD} views each.
UNDERPERFORMING VIDEOS:
{chr(10).join(low_titles)}
CURRENT THEMES: {current_themes}
COMPETITOR GAPS: {competitor_gaps}
VIRAL HOOKS FROM TREND DATA: {viral_hooks}

The current content strategy is not working. Diagnose why and propose an emergency pivot.
Return JSON:
{{
  "diagnosis": "<2-3 sentences on what is likely wrong>",
  "themes_to_abandon": ["<oversaturated or wrong-fit themes>"],
  "pivot_themes": ["<2-3 completely fresh themes to try immediately>"],
  "new_hook_style": "<specific new hook formula — be concrete>",
  "new_visual_direction": "<specific visual style shift — be concrete>",
  "urgent_title_formula": "<exact title template for next 5 videos>",
  "confidence": "<high/medium/low>"
}}"""
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=OPENAI_HEADERS,
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}],
              "response_format": {"type": "json_object"}, "temperature": 0.7}
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

def write_alert(config, streak, low_entries, pivot):
    config["performance_alert"] = {
        "active": True,
        "triggered_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "consecutive_low": streak,
        "threshold_views": LOW_VIEW_THRESHOLD,
        "diagnosis": pivot.get("diagnosis", ""),
        "pivot_themes": pivot.get("pivot_themes", []),
        "themes_to_abandon": pivot.get("themes_to_abandon", []),
        "new_hook_style": pivot.get("new_hook_style", ""),
        "new_visual_direction": pivot.get("new_visual_direction", ""),
        "urgent_title_formula": pivot.get("urgent_title_formula", ""),
        "confidence": pivot.get("confidence", "medium")
    }
    strategy = config.setdefault("content_strategy", {})
    abandon  = set(pivot.get("themes_to_abandon", []))
    new      = pivot.get("pivot_themes", [])
    current  = [t for t in strategy.get("top_performing_themes", []) if t not in abandon]
    for t in new:
        if t not in current:
            current.append(t)
    strategy["top_performing_themes"]    = current
    strategy["emergency_hook_style"]     = pivot.get("new_hook_style", "")
    strategy["emergency_title_formula"]  = pivot.get("urgent_title_formula", "")
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    print("  Alert + pivot written to config.json")

def clear_alert(config):
    if "performance_alert" in config and config["performance_alert"].get("active"):
        config["performance_alert"]["active"] = False
        config["performance_alert"]["cleared_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        strategy = config.get("content_strategy", {})
        strategy.pop("emergency_hook_style", None)
        strategy.pop("emergency_title_formula", None)
        CONFIG_PATH.write_text(json.dumps(config, indent=2))
        print("  Previous alert cleared — performance recovered")

def main():
    print(f"\nLUCID REALMS — Performance Monitor")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")
    config = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}

    print("1. Loading recent videos...")
    videos = load_recent_videos()
    if not videos:
        print("   No eligible videos yet (need videos >= 48h old).\n")
        return
    print(f"   {len(videos)} videos eligible\n")

    print("2. Fetching YouTube token...")
    token = get_access_token()
    print("   Done\n")

    print("3. Fetching view counts...")
    views_map = get_video_views([e["video_id"] for e in videos], token)
    for e in videos[-10:]:
        v = views_map.get(e["video_id"], "?")
        print(f"   {e['date']} [{e['slot']}] '{e['title_a'][:45]}' -> {v} views")
    print()

    print("4. Checking consecutive low-view streak...")
    streak, low_entries = check_consecutive_low(videos, views_map)
    print(f"   Streak: {streak} consecutive videos under {LOW_VIEW_THRESHOLD} views\n")

    if streak >= CONSECUTIVE_LIMIT:
        print(f"ALERT: {streak} consecutive low-view videos. Generating pivot with gpt-4o...\n")
        pivot = generate_pivot_strategy(low_entries, config)
        print(f"Diagnosis:      {pivot.get('diagnosis','')[:120]}")
        print(f"Abandon:        {pivot.get('themes_to_abandon',[])}")
        print(f"Pivot to:       {pivot.get('pivot_themes',[])}")
        print(f"New hook:       {pivot.get('new_hook_style','')[:80]}")
        print(f"Title formula:  {pivot.get('urgent_title_formula','')[:80]}")
        print(f"Confidence:     {pivot.get('confidence','?')}\n")
        write_alert(config, streak, low_entries, pivot)
    else:
        print(f"   No alert — streak below {CONSECUTIVE_LIMIT}")
        clear_alert(config)

    print("5. Updating view counts in analytics log...")
    log = json.loads(ANALYTICS_LOG.read_text()) if ANALYTICS_LOG.exists() else []
    updated = 0
    for entry in log:
        vid = entry.get("video_id")
        if vid and vid in views_map:
            entry["views"] = views_map[vid]
            updated += 1
    ANALYTICS_LOG.write_text(json.dumps(log, indent=2))
    print(f"   Updated {updated} entries\n")

    status = "ALERT ACTIVE" if streak >= CONSECUTIVE_LIMIT else "Healthy"
    print(f"Performance Monitor complete | Status: {status}")

if __name__ == "__main__":
    main()
