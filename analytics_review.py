#!/usr/bin/env python3
"""
LUCID REALMS — Daily Analytics Review & Monetization Tracker
Runs on GitHub Actions at 8 AM to review performance and update strategy.
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

OPENAI_API_KEY   = os.environ["OPENAI_API_KEY"]
YT_CLIENT_ID     = os.environ["YOUTUBE_CLIENT_ID"]
YT_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YT_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]

ANALYTICS_LOG = Path("analytics_log.json")
CONFIG_PATH   = Path("config.json")

MONETIZATION = {
    "subscribers_needed": 1000,
    "shorts_views_needed": 10_000_000
}

# ── Auth ──────────────────────────────────────────────────────────────────────

def get_access_token():
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     YT_CLIENT_ID,
        "client_secret": YT_CLIENT_SECRET,
        "refresh_token": YT_REFRESH_TOKEN,
        "grant_type":    "refresh_token"
    })
    resp.raise_for_status()
    return resp.json()["access_token"]

# ── Channel Stats ─────────────────────────────────────────────────────────────

def get_channel_stats(token):
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels?part=statistics&mine=true",
        headers={"Authorization": f"Bearer {token}"}
    )
    resp.raise_for_status()
    return resp.json()["items"][0]["statistics"]

# ── Video Stats ───────────────────────────────────────────────────────────────

def get_video_stats(video_ids, token):
    if not video_ids:
        return []
    ids_str = ",".join(video_ids[:50])
    resp = requests.get(
        f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id={ids_str}",
        headers={"Authorization": f"Bearer {token}"}
    )
    resp.raise_for_status()
    return resp.json().get("items", [])

# ── Analytics API (90-day Shorts views) ──────────────────────────────────────

def get_shorts_views_90d(token):
    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start     = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    resp = requests.get(
        "https://youtubeanalytics.googleapis.com/v2/reports",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "ids":        "channel==MINE",
            "startDate":  start,
            "endDate":    today,
            "metrics":    "views",
            "dimensions": "day"
        }
    )
    if not resp.ok:
        print(f"  Analytics API unavailable ({resp.status_code}) — using log totals")
        return None
    rows = resp.json().get("rows", [])
    return sum(row[1] for row in rows) if rows else 0

# ── Strategy Update via GPT-4o ────────────────────────────────────────────────

def get_strategy_update(top_themes, bottom_themes, avg_views):
    prompt = f"""You are the strategy lead for LUCID REALMS, a YouTube Shorts channel posting surreal AI art.

Performance data:
- Average views per video: {avg_views:.0f}
- Top performing themes: {top_themes}
- Underperforming themes (< 500 views after 3 days): {bottom_themes}

Based on this data, provide a brief content strategy update in JSON:
{{
  "recommended_themes": ["<theme1>", "<theme2>", "<theme3>", "<theme4>", "<theme5>", "<theme6>"],
  "strategy_note": "<1-2 sentence actionable insight for tomorrow's content>",
  "title_tip": "<one specific tip to improve click-through rate>"
}}"""

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "response_format": {"type": "json_object"}
        }
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n📊 LUCID REALMS — Daily Analytics Review")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")

    log = json.loads(ANALYTICS_LOG.read_text()) if ANALYTICS_LOG.exists() else []
    config = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}

    print("1️⃣  Fetching YouTube token...")
    token = get_access_token()
    print("   ✓\n")

    print("2️⃣  Fetching channel statistics...")
    stats = get_channel_stats(token)
    subscribers = int(stats.get("subscriberCount", 0))
    total_views = int(stats.get("viewCount", 0))
    video_count = int(stats.get("videoCount", 0))
    print(f"   Subscribers: {subscribers:,}")
    print(f"   Total views: {total_views:,}")
    print(f"   Videos:      {video_count}\n")

    print("3️⃣  Fetching video-level stats...")
    upload_entries = [e for e in log if e.get("video_id") and e.get("type") != "daily_review"]
    video_ids = [e["video_id"] for e in upload_entries[-50:]]
    video_items = get_video_stats(video_ids, token)

    # Update log entries with latest stats
    stats_map = {v["id"]: v["statistics"] for v in video_items}
    for entry in upload_entries:
        vid = entry.get("video_id")
        if vid and vid in stats_map:
            entry["views"]    = int(stats_map[vid].get("viewCount", 0))
            entry["likes"]    = int(stats_map[vid].get("likeCount", 0))
            entry["comments"] = int(stats_map[vid].get("commentCount", 0))

    # Performance analysis
    videos_with_stats = [e for e in upload_entries if "views" in e]
    avg_views = sum(e["views"] for e in videos_with_stats) / len(videos_with_stats) if videos_with_stats else 0

    sorted_by_views = sorted(videos_with_stats, key=lambda x: x["views"], reverse=True)
    top_videos      = sorted_by_views[:3]
    bottom_videos   = sorted_by_views[-3:] if len(sorted_by_views) > 3 else []
    winner_ids      = [v["video_id"] for v in sorted_by_views if v["views"] >= 10000]

    top_themes    = list(dict.fromkeys(v.get("theme", "") for v in top_videos))
    bottom_themes = [v.get("theme", "") for v in bottom_videos if v["views"] < 500]

    print(f"   Avg views/video: {avg_views:.0f}")
    print(f"   Top themes: {top_themes}")
    print(f"   Underperforming themes: {bottom_themes}")
    print(f"   🏆 Winner videos (10k+ views): {len(winner_ids)}\n")

    print("4️⃣  Fetching 90-day Shorts views...")
    shorts_views_90d = get_shorts_views_90d(token)
    if shorts_views_90d is None:
        # Fall back to summing log
        shorts_views_90d = sum(e.get("views", 0) for e in videos_with_stats)
    print(f"   Shorts views (90d): {shorts_views_90d:,}\n")

    # Monetization progress
    sub_pct   = (subscribers / MONETIZATION["subscribers_needed"]) * 100
    views_pct = (shorts_views_90d / MONETIZATION["shorts_views_needed"]) * 100
    bottleneck = "subscribers" if sub_pct < views_pct else "Shorts views"

    daily_avg_views = shorts_views_90d / max(video_count, 1) * 3  # 3 posts/day
    days_needed_views = max(0, (MONETIZATION["shorts_views_needed"] - shorts_views_90d) / max(daily_avg_views, 1))
    projected_days = int(days_needed_views) if daily_avg_views > 0 else 999

    print("5️⃣  Getting GPT-4o strategy update...")
    strategy = get_strategy_update(top_themes, bottom_themes, avg_views)
    print(f"   ✓ Strategy updated\n")

    # Update config
    if config:
        if "content_strategy" in config:
            config["content_strategy"]["top_performing_themes"] = strategy["recommended_themes"]
        if "monetization_goal" in config:
            config["monetization_goal"]["current"] = {
                "subscribers":         subscribers,
                "shorts_views_90_days": shorts_views_90d,
                "last_updated":        datetime.now(timezone.utc).strftime("%Y-%m-%d")
            }
        CONFIG_PATH.write_text(json.dumps(config, indent=2))
        print("   ✓ Config updated with new strategy\n")

    # Append review entry to log
    log.append({
        "date":                      datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "type":                      "daily_review",
        "subscribers":               subscribers,
        "shorts_views_90_days":      shorts_views_90d,
        "pct_to_subscriber_goal":    round(sub_pct, 1),
        "pct_to_views_goal":         round(views_pct, 4),
        "projected_days_to_monetization": projected_days,
        "avg_views_per_video":       round(avg_views, 1),
        "top_themes":                top_themes,
        "winner_video_ids":          winner_ids,
        "strategy_update":           strategy.get("strategy_note", ""),
        "title_tip":                 strategy.get("title_tip", "")
    })
    ANALYTICS_LOG.write_text(json.dumps(log, indent=2))

    # ── Dashboard ──────────────────────────────────────────────────────────────
    print("━" * 45)
    print(f"📊 LUCID REALMS — Daily Report {datetime.now().strftime('%Y-%m-%d')}")
    print("━" * 45)
    print(f"👥  Subscribers:      {subscribers:>7,} / 1,000     ({sub_pct:.1f}%)")
    print(f"🎬  Shorts Views 90d: {shorts_views_90d:>7,} / 10,000,000 ({views_pct:.4f}%)")
    print(f"📈  Avg views/video:  {avg_views:>7.0f}")
    print(f"⏱️   Projected days:   {projected_days:>7}")
    print(f"🚧  Bottleneck:       {bottleneck}")
    print(f"🏆  Winner videos:    {len(winner_ids)}")
    print(f"🎯  Top themes:       {', '.join(top_themes) if top_themes else 'gathering data'}")
    print(f"💡  Strategy:         {strategy.get('strategy_note', 'N/A')}")
    print(f"📝  Title tip:        {strategy.get('title_tip', 'N/A')}")
    print("━" * 45)

if __name__ == "__main__":
    main()
