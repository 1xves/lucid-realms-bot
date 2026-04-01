#!/usr/bin/env python3
"""
LUCID REALMS — A/B Title Test Agent
Runs daily. Finds videos uploaded 24-48h ago with title_b queued.
Checks CTR via YouTube Analytics API.
If CTR < 4%, swaps to title_b. Logs result.
"""

import os, json, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

YT_CLIENT_ID      = os.environ["YOUTUBE_CLIENT_ID"]
YT_CLIENT_SECRET  = os.environ["YOUTUBE_CLIENT_SECRET"]
YT_REFRESH_TOKEN  = os.environ["YOUTUBE_REFRESH_TOKEN"]

ANALYTICS_LOG = Path("analytics_log.json")

CTR_THRESHOLD = 4.0  # Switch to title B if CTR below this %

def get_access_token():
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": YT_CLIENT_ID, "client_secret": YT_CLIENT_SECRET,
        "refresh_token": YT_REFRESH_TOKEN, "grant_type": "refresh_token"
    })
    resp.raise_for_status()
    return resp.json()["access_token"]

def get_video_ctr(video_id, token):
    """Get CTR for a video via YouTube Analytics API."""
    try:
        end   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
        resp  = requests.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            headers={"Authorization": f"Bearer {token}"},
            params={"ids": "channel==MINE", "startDate": start, "endDate": end,
                    "metrics": "views,impressions,impressionClickThroughRate",
                    "dimensions": "video", "filters": f"video=={video_id}"}
        )
        rows = resp.json().get("rows", []) if resp.ok else []
        if rows:
            # columns: video_id, views, impressions, ctr
            return {"views": int(rows[0][1]), "impressions": int(rows[0][2]), "ctr": float(rows[0][3]) * 100}
        return None
    except Exception as e:
        print(f"  ⚠ CTR fetch failed for {video_id}: {e}")
        return None

def update_video_title(video_id, new_title, token):
    """Update a video's title via YouTube Data API."""
    # First get current snippet
    resp = requests.get(
        f"https://www.googleapis.com/youtube/v3/videos?part=snippet&id={video_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if not resp.ok or not resp.json().get("items"):
        return False

    snippet = resp.json()["items"][0]["snippet"]
    snippet["title"] = new_title

    update = requests.put(
        "https://www.googleapis.com/youtube/v3/videos?part=snippet",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"id": video_id, "snippet": snippet}
    )
    return update.ok

def main():
    print(f"\n🧪 LUCID REALMS — A/B Title Test")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")

    if not ANALYTICS_LOG.exists():
        print("  No analytics log found — nothing to test.")
        return

    log   = json.loads(ANALYTICS_LOG.read_text())
    token = get_access_token()
    now   = datetime.now(timezone.utc)
    tested, swapped, skipped = 0, 0, 0

    for entry in log:
        # Only process upload entries with pending A/B test
        if entry.get("type") == "daily_analytics":
            continue
        if entry.get("ab_tested", True):
            continue
        if not entry.get("title_b") or not entry.get("video_id"):
            continue

        # Only test videos uploaded 20-52 hours ago (enough data, not too stale)
        try:
            upload_date = datetime.fromisoformat(entry["date"] + "T" + entry.get("time_utc", "12:00") + ":00+00:00")
        except Exception:
            continue

        hours_old = (now - upload_date).total_seconds() / 3600
        if hours_old < 20 or hours_old > 52:
            skipped += 1
            continue

        video_id = entry["video_id"]
        title_a  = entry["title_a"]
        title_b  = entry["title_b"]

        print(f"  Testing: {video_id}")
        print(f"    🅰  {title_a}")
        print(f"    🅱  {title_b}")

        metrics = get_video_ctr(video_id, token)
        if not metrics:
            print(f"    ⚠ No metrics yet — skipping\n")
            continue

        ctr = metrics.get("ctr", 0)
        print(f"    CTR: {ctr:.1f}% | Views: {metrics.get('views', 0):,} | Impressions: {metrics.get('impressions', 0):,}")

        if ctr < CTR_THRESHOLD:
            print(f"    CTR below {CTR_THRESHOLD}% — switching to Title B...")
            success = update_video_title(video_id, title_b, token)
            if success:
                entry["active_title"]   = "b"
                entry["title_switched"] = True
                entry["ctr_at_switch"]  = ctr
                print(f"    ✓ Title updated to B")
                swapped += 1
            else:
                print(f"    ✗ Title update failed")
        else:
            print(f"    CTR {ctr:.1f}% ≥ {CTR_THRESHOLD}% — Title A is working ✓")

        entry["ab_tested"]    = True
        entry["final_ctr"]    = ctr
        entry["views_at_test"] = metrics.get("views", 0)
        tested += 1
        print()

    ANALYTICS_LOG.write_text(json.dumps(log, indent=2))

    print("─" * 50)
    print(f"🧪 A/B Test Summary: {tested} tested | {swapped} switched | {skipped} not ready")
    print("─" * 50)

if __name__ == "__main__":
    main()
