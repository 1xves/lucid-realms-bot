#!/usr/bin/env python3
"""
LUCID REALMS — Weekly Milestone Watcher
Runs on GitHub Actions every Sunday at 10 AM ET.
Checks subscriber count. At 10,000 subs, activates the long-form video pipeline.
"""

import os
import json
import base64
import requests
from datetime import datetime, timezone
from pathlib import Path

OPENAI_API_KEY   = os.environ["OPENAI_API_KEY"]
YT_CLIENT_ID     = os.environ["YOUTUBE_CLIENT_ID"]
YT_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YT_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]
GITHUB_TOKEN     = os.environ.get("GH_PAT", "")
GITHUB_REPO      = "1xves/lucid-realms-bot"

CONFIG_PATH   = Path("config.json")
ANALYTICS_LOG = Path("analytics_log.json")

MILESTONES = [1000, 5000, 10000, 25000, 50000, 100000]

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

# ── Milestone Check ───────────────────────────────────────────────────────────

def get_next_milestone(current):
    for m in MILESTONES:
        if current < m:
            return m
    return None

def milestone_already_reached(milestone_name, config):
    reached = config.get("milestones_reached", [])
    return milestone_name in reached

def mark_milestone_reached(milestone_name, config):
    if "milestones_reached" not in config:
        config["milestones_reached"] = []
    if milestone_name not in config["milestones_reached"]:
        config["milestones_reached"].append(milestone_name)

# ── Long-Form Strategy Buildout (fires at 10k) ────────────────────────────────

def build_longform_strategy(subscribers, config):
    print("\n🎉 10,000 SUBSCRIBERS REACHED — Activating long-form pipeline...\n")

    prompt = f"""You are the strategic director for LUCID REALMS, a YouTube Shorts channel that has just crossed 10,000 subscribers.
Channel brand: {config.get('channel_theme', '')}
Current top themes: {config.get('content_strategy', {}).get('top_performing_themes', [])}

The channel is ready to launch long-form videos (8-12 minutes) alongside its Shorts.
Design a long-form content strategy in JSON:
{{
  "formats": ["<format 1 — e.g. cinematic world exploration>", "<format 2>", "<format 3>"],
  "target_length_minutes": 10,
  "uploads_per_week": 1,
  "upload_day": "Saturday",
  "title_strategy": "<how titles should differ from Shorts — no #Shorts, longer curiosity gap>",
  "thumbnail_strategy": "<key visual approach for long-form thumbnails>",
  "description_strategy": "<how to use chapters and descriptions to maximize watch time>",
  "monetization_notes": "<why long-form unlocks $5k/month — RPM comparison>",
  "first_video_concept": {{
    "title": "<compelling long-form debut title>",
    "premise": "<2-3 sentence concept>",
    "chapters": ["00:00 - <chapter>", "02:00 - <chapter>", "04:00 - <chapter>", "06:00 - <chapter>", "08:00 - <chapter>"]
  }}
}}"""

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={
            "model":           "gpt-4o",
            "messages":        [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

def create_longform_workflow_yaml():
    return '''name: "🎬 Weekly Long-Form Video (Saturday 12 PM ET)"

on:
  schedule:
    - cron: "0 16 * * 6"   # 12 PM EDT (UTC-4). Change to '0 17 * * 6' for EST
  workflow_dispatch:

jobs:
  longform:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Install ffmpeg
        run: sudo apt-get install -y ffmpeg

      - name: Generate and upload long-form video
        env:
          OPENAI_API_KEY:        ${{ secrets.OPENAI_API_KEY }}
          YOUTUBE_CLIENT_ID:     ${{ secrets.YOUTUBE_CLIENT_ID }}
          YOUTUBE_CLIENT_SECRET: ${{ secrets.YOUTUBE_CLIENT_SECRET }}
          YOUTUBE_REFRESH_TOKEN: ${{ secrets.YOUTUBE_REFRESH_TOKEN }}
        run: python generate_longform.py

      - name: Commit analytics log
        run: |
          git config --local user.email "lucid-realms-bot@users.noreply.github.com"
          git config --local user.name "LUCID REALMS Bot"
          git pull --rebase origin main
          git add analytics_log.json
          git diff --staged --quiet || git commit -m "📊 Long-form upload log [skip ci]"
          git push
'''

def push_file_to_github(path, content_str, commit_message):
    """Create or update a file in the GitHub repo."""
    if not GITHUB_TOKEN:
        print(f"  ⚠️  No GH_PAT — skipping GitHub push for {path}")
        return False

    encoded = base64.b64encode(content_str.encode()).decode()
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept":        "application/vnd.github.v3+json"
    }

    # Check if file exists (get SHA)
    check = requests.get(f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}", headers=headers)
    sha   = check.json().get("sha") if check.ok else None

    body = {"message": commit_message, "content": encoded, "branch": "main"}
    if sha:
        body["sha"] = sha

    resp = requests.put(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
        headers=headers,
        json=body
    )
    if resp.ok:
        print(f"  ✓ Pushed {path} to GitHub")
        return True
    else:
        print(f"  ✗ Failed to push {path}: {resp.status_code} {resp.text[:200]}")
        return False

# ── Progress Log ──────────────────────────────────────────────────────────────

def log_progress(subscribers, next_milestone, config):
    pct = (subscribers / next_milestone) * 100
    log = json.loads(ANALYTICS_LOG.read_text()) if ANALYTICS_LOG.exists() else []
    log.append({
        "date":             datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "type":             "milestone_check",
        "subscribers":      subscribers,
        "next_milestone":   next_milestone,
        "pct_to_milestone": round(pct, 1)
    })
    ANALYTICS_LOG.write_text(json.dumps(log, indent=2))

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n🏁 LUCID REALMS — Weekly Milestone Check")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")

    config = json.loads(CONFIG_PATH.read_text())

    print("1️⃣  Fetching subscriber count...")
    token       = get_access_token()
    stats       = get_channel_stats(token)
    subscribers = int(stats.get("subscriberCount", 0))
    print(f"   👥 Subscribers: {subscribers:,}\n")

    next_milestone = get_next_milestone(subscribers)

    # ── 10k Long-Form Launch ──────────────────────────────────────────────────
    if subscribers >= 10000 and not milestone_already_reached("10k", config):
        lf_strategy = build_longform_strategy(subscribers, config)

        # Update config with long-form strategy
        config["long_form_strategy"] = {
            "enabled":            True,
            "milestone_reached":  "10k subscribers",
            "milestone_date":     datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "uploads_per_week":   lf_strategy.get("uploads_per_week", 1),
            "upload_day":         lf_strategy.get("upload_day", "Saturday"),
            "target_length_minutes": lf_strategy.get("target_length_minutes", 10),
            "formats":            lf_strategy.get("formats", []),
            "title_strategy":     lf_strategy.get("title_strategy", ""),
            "monetization_notes": lf_strategy.get("monetization_notes", ""),
            "first_video_concept": lf_strategy.get("first_video_concept", {})
        }
        mark_milestone_reached("10k", config)
        CONFIG_PATH.write_text(json.dumps(config, indent=2))

        # Push longform workflow to GitHub
        push_file_to_github(
            ".github/workflows/longform.yml",
            create_longform_workflow_yaml(),
            "🎬 Add long-form weekly workflow — 10k milestone reached [skip ci]"
        )

        # Push updated config to GitHub
        push_file_to_github(
            "config.json",
            json.dumps(config, indent=2),
            "🎉 10k milestone — long-form strategy activated [skip ci]"
        )

        print("\n━" * 50)
        print("🎉 LUCID REALMS — 10,000 SUBSCRIBERS!")
        print("━" * 50)
        print("✅ Long-form strategy saved to config")
        print("✅ Weekly Saturday long-form workflow deployed")
        print(f"🎬 First video concept: {lf_strategy.get('first_video_concept', {}).get('title', '')}")
        print("━" * 50)

    # ── 1k YPP Milestone ─────────────────────────────────────────────────────
    elif subscribers >= 1000 and not milestone_already_reached("1k", config):
        mark_milestone_reached("1k", config)
        CONFIG_PATH.write_text(json.dumps(config, indent=2))
        print("🎉 1,000 SUBSCRIBERS — YPP subscriber requirement met!")
        print("   Now focus on hitting 10M Shorts views in 90 days to unlock monetization.")

    # ── Not yet at next milestone ─────────────────────────────────────────────
    else:
        if next_milestone:
            pct = (subscribers / next_milestone) * 100
            remaining = next_milestone - subscribers
            print(f"   Next milestone: {next_milestone:,} subscribers")
            print(f"   Progress: {subscribers:,} / {next_milestone:,} ({pct:.1f}%)")
            print(f"   Remaining: {remaining:,} subscribers to go")
            log_progress(subscribers, next_milestone, config)

    print(f"\n✅ Milestone check complete\n")

if __name__ == "__main__":
    main()
