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

LOW_VIEW_THRESHOLD = 100    # views considered "low" for a video >= MIN_AGE_HOURS old
MIN_AGE_HOURS      = 48     # only evaluate videos at least this old
CONSECUTIVE_LIMIT  = 5      # how many low-view videos in a row before alert fires

# ── Auth ──────────────────────────────────────────────────────────────────────────────

def get_access_token():
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     YT_CLIENT_ID,
        "client_secret": YT_CLIENT_SECRET,
        "refresh_token": YT_REFRESH_TOKEN,
        "grant_type":    "refresh_token"
    })
    resp.raise_for_status()
    return resp.json()["access_token"]

# ── YouTube Analytics ─────────────────────────────────────────────────────────────

def get_channel_id(token):
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        headers={"Authorization": f"Bearer {token}"},
        params={"part": "id", "mine": "true"}
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return items[0]["id"] if items else None

def get_video_views(video_ids, token):
    """Fetch view counts for a list of video IDs via YouTube Data API."""
    if not video_ids:
        return {}
    # Batch up to 50 at a time
    views = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            headers={"Authorization": f"Bearer {token}"},
            params={"part": "statistics", "id": ",".join(batch)}
        )
        if not resp.ok:
            print(f"  ⚠ YouTube API error: {resp.status_code}")
            continue
        for item in resp.json().get("items", []):
            vid = item["id"]
            views[vid] = int(item["statistics"].get("viewCount", 0))
        time.sleep(0.3)
    return views

# ── Consecutive low-view detection ───────────────────────────────────────────────────────────────────

def load_recent_videos():
    """Load videos from analytics_log.json that are old enough to evaluate."""
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
                entry["date"] + " " + entry.get("time_utc", "00:00"),
                "%Y-%m-%d %H:%M"
            ).replace(tzinfo=timezone.utc)
            age_hours = (now - upload_dt).total_seconds() / 3600
            if age_hours >= MIN_AGE_HOURS:
                eligible.append(entry)
        except Exception:
            continue
    # Sort oldest first so we can count consecutive streak from most recent
    return sorted(eligible, key=lambda x: x["date"] + x.get("time_utc", ""))

def check_consecutive_low(videos, views_map):
    """
    Walk from most recent to oldest, count consecutive videos below threshold.
    Returns (streak_count, low_video_entries).
    """
    streak = 0
    low_entries = []
    for entry in reversed(videos):
        vid = entry["video_id"]
        v = views_map.get(vid)
        if v is None:
            break  # unknown — stop streak
        if v < LOW_VIEW_THRESHOLD:
            streak += 1
            low_entries.append({**entry, "views": v})
        else:
            break  # streak broken
    return streak, list(reversed(low_entries))

# ── GPT-4o content pivot ──────────────────────────────────────────────────────────────────────────────

def get_relative_performers(views_map):
    """
    From all videos with known views, find the top 3 and bottom 3
    to show gpt-4o what has worked vs. what hasn't across the whole channel history.
    """
    if not ANALYTICS_LOG.exists():
        return [], []
    log = json.loads(ANALYTICS_LOG.read_text())
    scored = []
    for e in log:
        vid = e.get("video_id")
        if vid and vid in views_map:
            scored.append({"title": e.get("title_a", ""), "views": views_map[vid],
                           "tags": e.get("tags", []), "slot": e.get("slot", "")})
    scored.sort(key=lambda x: x["views"], reverse=True)
    return scored[:3], scored[-3:]  # top 3, bottom 3

def generate_pivot_strategy(low_entries, current_config, views_map):
    strategy       = current_config.get("content_strategy", {})
    current_themes = strategy.get("top_performing_themes", [])
    trend          = current_config.get("trend_research", {})

    # Pull everything from trend research
    trending_themes    = trend.get("trending_themes", [])
    declining_themes   = trend.get("declining_themes", [])
    competitor_gaps    = trend.get("competitor_gaps", "N/A")
    viral_hooks        = trend.get("viral_hook_patterns", [])
    title_insights     = trend.get("title_insights", "N/A")
    visual_trends      = trend.get("visual_style_trends", "N/A")
    weekly_rec         = trend.get("weekly_recommendation", "N/A")
    sources_summary    = trend.get("sources_summary", "N/A")
    trend_updated      = trend.get("last_updated", "unknown")

    # Historical relative performance
    top_performers, worst_performers = get_relative_performers(views_map)
    top_str   = "\n".join(f"  - '{v['title']}' \u2192 {v['views']} views" for v in top_performers) or "  None yet"
    worst_str = "\n".join(f"  - '{v['title']}' \u2192 {v['views']} views" for v in worst_performers) or "  None yet"
    low_titles = "\n".join(f"  - '{e['title_a']}' \u2192 {e['views']} views" for e in low_entries)

    prompt = f"""You are the emergency strategy director for LUCID REALMS, a YouTube Shorts channel for surreal AI art.

PROBLEM: The last {len(low_entries)} consecutive videos got under {LOW_VIEW_THRESHOLD} views each.

FAILING VIDEOS (most recent streak):
{low_titles}

CHANNEL HISTORY \u2014 best performers ever:
{top_str}

CHANNEL HISTORY \u2014 worst performers ever:
{worst_str}

CURRENT ACTIVE THEMES: {current_themes}

TREND RESEARCH (last updated {trend_updated}):
- Trending themes right now: {trending_themes}
- Declining/oversaturated themes: {declining_themes}
- Competitor gap (uncovered angle): {competitor_gaps}
- Viral hook patterns observed: {viral_hooks}
- Title format working this week: {title_insights}
- Visual style gaining traction: {visual_trends}
- This week's recommendation: {weekly_rec}
- Data summary: {sources_summary}

Using the trend research and channel history above, diagnose why performance has stalled
and propose a data-driven emergency pivot. The 2-3 pivot themes MUST come from the trending
themes or competitor gaps identified in the trend research \u2014 not invented from scratch.

Return JSON:
{{
  "diagnosis": "<2-3 sentences: why current content is underperforming based on the data>",
  "themes_to_abandon": ["<themes from current list that overlap with declining/oversaturated \u2014 be specific>"],
  "pivot_themes": ["<2-3 themes pulled directly from trending_themes or competitor_gaps above>"],
  "new_hook_style": "<specific hook formula derived from viral_hook_patterns \u2014 be concrete>",
  "new_visual_direction": "<specific visual style shift derived from visual_style_trends \u2014 be concrete>",
  "urgent_title_formula": "<exact title template based on title_insights \u2014 e.g. '[Thing] that shouldn't exist but does'>",
  "data_rationale": "<one sentence explaining which data points drove this recommendation>",
  "confidence": "<high/medium/low>"
}}"""

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=OPENAI_HEADERS,
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.7
        }
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

# ── Write alert to config ─────────────────────────────────────────────────────────────────────────────

def write_alert(config, streak, low_entries, pivot):
    """Stamp an alert into config.json so generate_and_upload.py adapts."""
    config["performance_alert"] = {
        "active":               True,
        "triggered_at":         datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "consecutive_low":      streak,
        "threshold_views":      LOW_VIEW_THRESHOLD,
        "diagnosis":            pivot.get("diagnosis", ""),
        "pivot_themes":         pivot.get("pivot_themes", []),
        "themes_to_abandon":    pivot.get("themes_to_abandon", []),
        "new_hook_style":       pivot.get("new_hook_style", ""),
        "new_visual_direction": pivot.get("new_visual_direction", ""),
        "urgent_title_formula": pivot.get("urgent_title_formula", ""),
        "confidence":           pivot.get("confidence", "medium"),
        "data_rationale":       pivot.get("data_rationale", "")
    }
    # Also inject pivot themes directly into active content strategy
    strategy = config.setdefault("content_strategy", {})
    abandon   = set(pivot.get("themes_to_abandon", []))
    new       = pivot.get("pivot_themes", [])
    current   = [t for t in strategy.get("top_performing_themes", []) if t not in abandon]
    for t in new:
        if t not in current:
            current.append(t)
    strategy["top_performing_themes"] = current
    strategy["emergency_hook_style"]  = pivot.get("new_hook_style", "")
    strategy["emergency_title_formula"] = pivot.get("urgent_title_formula", "")

    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    print("  \u2713 Alert + pivot written to config.json")

def clear_alert(config):
    """Clear the alert if we're no longer in a streak."""
    if "performance_alert" in config and config["performance_alert"].get("active"):
        config["performance_alert"]["active"] = False
        config["performance_alert"]["cleared_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Remove emergency overrides
        strategy = config.get("content_strategy", {})
        strategy.pop("emergency_hook_style", None)
        strategy.pop("emergency_title_formula", None)
        CONFIG_PATH.write_text(json.dumps(config, indent=2))
        print("  \u2713 Previous alert cleared \u2014 performance recovered")

# ── Main ────────────────────────────────────────────────────────────────────────────────────

def main():
    print(f"\n\U0001f50d LUCID REALMS \u2014 Performance Monitor")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")

    config = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}

    print("1\ufe0f\u20e3  Loading recent videos from analytics log...")
    videos = load_recent_videos()
    if not videos:
        print("   No eligible videos yet (need videos \u2265 48h old).\n")
        return
    print(f"   {len(videos)} videos eligible for evaluation\n")

    print("2\ufe0f\u20e3  Fetching YouTube access token...")
    token = get_access_token()
    print("   \u2713\n")

    print("3\ufe0f\u20e3  Fetching view counts...")
    video_ids = [e["video_id"] for e in videos]
    views_map = get_video_views(video_ids, token)
    for e in videos[-10:]:
        vid = e["video_id"]
        v = views_map.get(vid, "?")
        print(f"   {e['date']} [{e['slot']}] '{e['title_a'][:45]}' \u2192 {v} views")
    print()

    print("4\ufe0f\u20e3  Checking for consecutive low-view streak...")
    streak, low_entries = check_consecutive_low(videos, views_map)
    print(f"   Current streak: {streak} consecutive videos under {LOW_VIEW_THRESHOLD} views")
    print()

    if streak >= CONSECUTIVE_LIMIT:
        print(f"\U0001f6a8 ALERT: {streak} consecutive low-view videos detected!")
        print(f"   Generating emergency content pivot with gpt-4o...\n")
        pivot = generate_pivot_strategy(low_entries, config, views_map)

        print("\u2500" * 55)
        print(f"Diagnosis:      {pivot.get('diagnosis', '')[:120]}")
        print(f"Abandon:        {pivot.get('themes_to_abandon', [])}")
        print(f"Pivot to:       {pivot.get('pivot_themes', [])}  <-- from trend research")
        print(f"New hook:       {pivot.get('new_hook_style', '')[:80]}")
        print(f"New visual:     {pivot.get('new_visual_direction', '')[:80]}")
        print(f"Title formula:  {pivot.get('urgent_title_formula', '')[:80]}")
        print(f"Data rationale: {pivot.get('data_rationale', '')[:100]}")
        print(f"Confidence:     {pivot.get('confidence', '?')}")
        print("\u2500" * 55 + "\n")

        write_alert(config, streak, low_entries, pivot)

    else:
        print(f"   \u2705 No alert \u2014 streak below threshold ({CONSECUTIVE_LIMIT})")
        clear_alert(config)

    # Update views in analytics_log.json
    print("5\ufe0f\u20e3  Updating view counts in analytics log...")
    log = json.loads(ANALYTICS_LOG.read_text()) if ANALYTICS_LOG.exists() else []
    updated = 0
    for entry in log:
        vid = entry.get("video_id")
        if vid and vid in views_map:
            entry["views"] = views_map[vid]
            updated += 1
    ANALYTICS_LOG.write_text(json.dumps(log, indent=2))
    print(f"   \u2713 Updated {updated} entries\n")

    print("\u2500" * 55)
    status = "\U0001f6a8 ALERT ACTIVE" if streak >= CONSECUTIVE_LIMIT else "\u2705 Healthy"
    print(f"\U0001f4ca LUCID REALMS \u2014 Monitor complete | Status: {status}")
    print("\u2500" * 55)

if __name__ == "__main__":
    main()
