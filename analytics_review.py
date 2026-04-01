#!/usr/bin/env python3
"""
LUCID REALMS — Daily Analytics Review
- gpt-4o-mini: processes raw stats, calculates metrics
- gpt-4o: generates strategy update
- Claude (claude-haiku-4-5-20251001): validates strategy as second opinion (if ANTHROPIC_API_KEY set)
- Writes best-performing upload hours to config for optimize_schedule.py
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

OPENAI_API_KEY    = os.environ["OPENAI_API_KEY"]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
YT_CLIENT_ID      = os.environ["YOUTUBE_CLIENT_ID"]
YT_CLIENT_SECRET  = os.environ["YOUTUBE_CLIENT_SECRET"]
YT_REFRESH_TOKEN  = os.environ["YOUTUBE_REFRESH_TOKEN"]

CONFIG_PATH    = Path("config.json")
ANALYTICS_LOG  = Path("analytics_log.json")

OPENAI_HEADERS = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

# ── Auth ──────────────────────────────────────────────────────────────────────
def get_access_token():
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": YT_CLIENT_ID, "client_secret": YT_CLIENT_SECRET,
        "refresh_token": YT_REFRESH_TOKEN, "grant_type": "refresh_token"
    })
    resp.raise_for_status()
    return resp.json()["access_token"]

# ── YouTube Data ──────────────────────────────────────────────────────────────
def get_channel_stats(token):
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels?part=statistics&mine=true",
        headers={"Authorization": f"Bearer {token}"}
    )
    resp.raise_for_status()
    return resp.json()["items"][0]["statistics"]

def get_recent_videos(token, max_results=20):
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search?part=snippet&type=video&mine=true&order=date&maxResults=" + str(max_results),
        headers={"Authorization": f"Bearer {token}"}
    )
    if not resp.ok:
        return []
    items = resp.json().get("items", [])
    video_ids = [item["id"]["videoId"] for item in items if "videoId" in item.get("id", {})]
    if not video_ids:
        return []
    stats_resp = requests.get(
        f"https://www.googleapis.com/youtube/v3/videos?part=statistics,snippet&id={','.join(video_ids)}",
        headers={"Authorization": f"Bearer {token}"}
    )
    return stats_resp.json().get("items", [])

def get_shorts_views_90d(token):
    try:
        end   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        resp  = requests.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            headers={"Authorization": f"Bearer {token}"},
            params={"ids": "channel==MINE", "startDate": start, "endDate": end,
                    "metrics": "views,estimatedMinutesWatched,averageViewDuration",
                    "dimensions": "video", "filters": "isShortsEligible==1",
                    "maxResults": 200}
        )
        rows = resp.json().get("rows", []) if resp.ok else []
        return sum(r[1] for r in rows) if rows else 0
    except Exception:
        return 0

# ── gpt-4o-mini: Summarise raw stats ─────────────────────────────────────────
def summarise_stats(channel_stats, video_items, shorts_views_90d):
    """Use gpt-4o-mini to extract key insights from raw API data."""
    video_summary = []
    for v in video_items[:10]:
        s = v.get("statistics", {})
        video_summary.append({
            "title":    v["snippet"]["title"][:60],
            "views":    int(s.get("viewCount", 0)),
            "likes":    int(s.get("likeCount", 0)),
            "comments": int(s.get("commentCount", 0)),
        })

    prompt = f"""Summarise these YouTube channel stats into key insights. Return JSON only.

Channel: subscribers={channel_stats.get('subscriberCount',0)}, total_views={channel_stats.get('viewCount',0)}, videos={channel_stats.get('videoCount',0)}
Shorts views (90 days): {shorts_views_90d}
Recent videos: {json.dumps(video_summary)}

Return:
{{
  "top_video_title": "<best performing title>",
  "top_video_views": <number>,
  "avg_views_per_video": <number>,
  "engagement_rate_pct": <number>,
  "growth_signal": "<positive/neutral/slow>",
  "ypp_shorts_progress_pct": <0-100, based on 10M views target>,
  "key_observation": "<one sentence insight>"
}}"""

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=OPENAI_HEADERS,
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
              "response_format": {"type": "json_object"}, "temperature": 0.3}
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

# ── gpt-4o: Strategy Update ───────────────────────────────────────────────────
def generate_strategy(summary, config):
    """Use gpt-4o for high-quality strategy synthesis."""
    current  = config.get("content_strategy", {})
    trends   = config.get("trend_research", {})

    prompt = f"""You are the strategic director for LUCID REALMS, a YouTube Shorts channel posting surreal AI art.

PERFORMANCE SUMMARY (today):
{json.dumps(summary, indent=2)}

CURRENT STRATEGY:
- Active themes: {current.get('top_performing_themes', [])}
- Weekly trend recommendation: {trends.get('weekly_recommendation', 'N/A')}
- Competitor gaps identified: {trends.get('competitor_gaps', 'N/A')}

Update the content strategy. Return JSON:
{{
  "top_performing_themes": ["<keep winning themes, retire slow ones, add 1-2 new from trend data>"],
  "hooks_to_use": ["<3 specific hook patterns that fit current data>"],
  "avoid": ["<what's clearly not working>"],
  "title_formula": "<specific title formula working this week>",
  "priority_action": "<single most important thing to change this week>",
  "monetization_note": "<one line on YPP progress>"
}}"""

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=OPENAI_HEADERS,
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}],
              "response_format": {"type": "json_object"}, "temperature": 0.7}
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

# ── Claude: Strategy Validation ───────────────────────────────────────────────
def validate_with_claude(strategy, summary):
    """Use Claude as a second opinion on the strategy. Returns refined strategy."""
    if not ANTHROPIC_API_KEY:
        print("  ℹ  ANTHROPIC_API_KEY not set — skipping Claude validation")
        return strategy

    prompt = f"""You are a YouTube growth strategist reviewing a content strategy for LUCID REALMS, a surreal AI art Shorts channel.

Performance today:
{json.dumps(summary, indent=2)}

Proposed strategy from GPT-4o:
{json.dumps(strategy, indent=2)}

Review this strategy critically. If anything looks off or could be improved, refine it. Return the same JSON structure with your refinements. Only change what genuinely needs improving — keep what's solid."""

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type":      "application/json"
        },
        json={
            "model":      "claude-haiku-4-5-20251001",
            "max_tokens": 1024,
            "messages":   [{"role": "user", "content": prompt}]
        }
    )
    if not resp.ok:
        print(f"  ⚠  Claude API error {resp.status_code} — using GPT-4o strategy")
        return strategy

    content = resp.json()["content"][0]["text"].strip()
    # Extract JSON if wrapped in markdown
    if "```" in content:
        content = content.split("```")[1].lstrip("json").strip()
    try:
        refined = json.loads(content)
        print("  ✓ Claude validation applied")
        return refined
    except Exception:
        print("  ⚠  Claude response not valid JSON — using GPT-4o strategy")
        return strategy

# ── Upload Hour Tracking ──────────────────────────────────────────────────────
def track_upload_performance(config):
    """Read analytics_log and find which UTC hours produce highest early views."""
    if not ANALYTICS_LOG.exists():
        return
    log = json.loads(ANALYTICS_LOG.read_text())
    hour_views = {}
    for entry in log:
        hour = entry.get("time_utc", "00:00")[:2]
        views = entry.get("views_24h", 0)
        if hour and views:
            if hour not in hour_views:
                hour_views[hour] = []
            hour_views[hour].append(views)
    if hour_views:
        avg_by_hour = {h: sum(v)/len(v) for h, v in hour_views.items()}
        config["upload_performance_by_hour"] = avg_by_hour
        best_hours = sorted(avg_by_hour, key=avg_by_hour.get, reverse=True)[:3]
        config["best_upload_hours_utc"] = best_hours
        print(f"  ✓ Best upload hours: {best_hours} UTC")

# ── Update Config ─────────────────────────────────────────────────────────────
def update_config(strategy, channel_stats, summary, shorts_views_90d):
    config = json.loads(CONFIG_PATH.read_text())
    config["content_strategy"]["top_performing_themes"] = strategy.get("top_performing_themes", [])
    config["content_strategy"]["seo"]["hooks"]          = strategy.get("hooks_to_use", [])
    config["monetization_goal"]["current"]["subscribers"]        = int(channel_stats.get("subscriberCount", 0))
    config["monetization_goal"]["current"]["shorts_views_90_days"] = shorts_views_90d
    config["last_strategy_update"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    config["strategy_details"]     = strategy
    track_upload_performance(config)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))

# ── Analytics Log Entry ───────────────────────────────────────────────────────
def append_daily_log(summary, strategy, shorts_views_90d):
    log = json.loads(ANALYTICS_LOG.read_text()) if ANALYTICS_LOG.exists() else []
    log.append({
        "date":             datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "type":             "daily_analytics",
        "subscribers":      summary.get("top_video_views", 0),
        "shorts_views_90d": shorts_views_90d,
        "avg_views":        summary.get("avg_views_per_video", 0),
        "growth_signal":    summary.get("growth_signal", ""),
        "priority_action":  strategy.get("priority_action", ""),
        "validated_by":     "claude+gpt4o" if ANTHROPIC_API_KEY else "gpt4o"
    })
    ANALYTICS_LOG.write_text(json.dumps(log, indent=2))

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\n📊 LUCID REALMS — Daily Analytics Review")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")

    config = json.loads(CONFIG_PATH.read_text())

    print("1⃣  Fetching YouTube data...")
    token          = get_access_token()
    channel_stats  = get_channel_stats(token)
    video_items    = get_recent_videos(token)
    shorts_views   = get_shorts_views_90d(token)
    subs           = int(channel_stats.get("subscriberCount", 0))
    print(f"   👥 {subs:,} subscribers | 📈 {shorts_views:,} Shorts views (90d)\n")

    print("2⃣  Summarising stats (gpt-4o-mini)...")
    summary = summarise_stats(channel_stats, video_items, shorts_views)
    print(f"   {summary.get('key_observation', '')}\n")

    print("3⃣  Generating strategy (gpt-4o)...")
    strategy = generate_strategy(summary, config)
    print(f"   Priority: {strategy.get('priority_action', '')}\n")

    print("4⃣  Validating with Claude...")
    strategy = validate_with_claude(strategy, summary)
    print()

    print("5⃣  Updating config + tracking upload hours...")
    update_config(strategy, channel_stats, summary, shorts_views)
    append_daily_log(summary, strategy, shorts_views)
    print()

    # YPP progress
    ypp_views_needed = 10_000_000
    pct = min(100, (shorts_views / ypp_views_needed) * 100)
    print("─" * 50)
    print(f"🎯 YPP Progress: {shorts_views:,} / {ypp_views_needed:,} views ({pct:.2f}%)")
    print(f"👥 Subscribers:  {subs:,}")
    print(f"📌 This week:    {strategy.get('priority_action', '')}")
    print(f"🧠 Models used:  gpt-4o-mini + gpt-4o{' + Claude' if ANTHROPIC_API_KEY else ''}")
    print("─" * 50)

if __name__ == "__main__":
    main()
