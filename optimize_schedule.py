#!/usr/bin/env python3
"""
LUCID REALMS — Upload Schedule Optimizer
Runs every Wednesday 6 AM ET.
Reads analytics_log to find which UTC hours generate highest early views.
Updates workflow cron expressions via GitHub API to hit the top 3 performing slots.
"""

import os, json, base64, requests
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GITHUB_TOKEN   = os.environ.get("GH_PAT", "")
GITHUB_REPO    = "1xves/lucid-realms-bot"

CONFIG_PATH   = Path("config.json")
ANALYTICS_LOG = Path("analytics_log.json")

OPENAI_HEADERS = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
GITHUB_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept":        "application/vnd.github.v3+json"
}

# Slots to optimize and their workflow files
SLOT_WORKFLOWS = {
    "morning":   ".github/workflows/morning.yml",
    "afternoon": ".github/workflows/afternoon.yml",
    "evening":   ".github/workflows/evening.yml"
}

def analyze_upload_performance():
    """Find which UTC hours produce highest views in first 24h."""
    if not ANALYTICS_LOG.exists():
        return None

    log = json.loads(ANALYTICS_LOG.read_text())
    hour_data = defaultdict(list)

    for entry in log:
        if entry.get("type") == "daily_analytics" or entry.get("ab_tested") is None:
            continue
        hour_str = entry.get("time_utc", "")[:2]
        views    = entry.get("views_at_test", entry.get("views_24h", 0))
        if hour_str.isdigit() and views > 0:
            hour_data[int(hour_str)].append(views)

    if not hour_data:
        return None

    avg_by_hour = {h: sum(v) / len(v) for h, v in hour_data.items()}
    best_hours  = sorted(avg_by_hour, key=avg_by_hour.get, reverse=True)

    return {"avg_views_by_hour": avg_by_hour, "best_hours": best_hours, "sample_count": sum(len(v) for v in hour_data.values())}

def get_optimal_crons_from_gpt(performance_data, config):
    """Use gpt-4o-mini to recommend new cron times based on performance data."""
    prompt = f"""You manage the YouTube upload schedule for LUCID REALMS, a Shorts channel.

Upload performance by UTC hour (avg views in first 24h):
{json.dumps(performance_data['avg_views_by_hour'], indent=2)}
Best performing hours (UTC): {performance_data['best_hours'][:5]}
Sample count: {performance_data['sample_count']} uploads analyzed

Current cron schedule:
- morning:   "0 13 * * *" (9 AM EDT)
- afternoon: "0 19 * * *" (3 PM EDT)
- evening:   "0 0 * * *"  (8 PM EDT)

Rules:
- Slots must be at least 4 hours apart
- Must cover morning (8-11 UTC), afternoon (15-20 UTC), evening (21-02 UTC) windows
- Keep uploads spread across the day
- Cron format: "M H * * *" where H is UTC hour, M is 0

Return JSON:
{{
  "morning_cron": "0 H * * *",
  "afternoon_cron": "0 H * * *",
  "evening_cron": "0 H * * *",
  "reasoning": "<one sentence explanation>",
  "expected_improvement": "<estimated % view lift>"
}}"""

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=OPENAI_HEADERS,
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
              "response_format": {"type": "json_object"}, "temperature": 0.3}
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

def update_workflow_cron(workflow_path, new_cron):
    """Update the cron expression in a workflow file via GitHub API."""
    if not GITHUB_TOKEN:
        print(f"  ⚠ No GH_PAT — skipping GitHub update for {workflow_path}")
        return False

    # Get current file
    check = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{workflow_path}",
        headers=GITHUB_HEADERS
    )
    if not check.ok:
        print(f"  ✗ Could not fetch {workflow_path}")
        return False

    sha      = check.json()["sha"]
    content  = base64.b64decode(check.json()["content"]).decode("utf-8")

    # Replace the cron line
    import re
    updated = re.sub(r'cron: "[^"]*"', f'cron: "{new_cron}"', content, count=1)
    if updated == content:
        print(f"  ℹ No cron change needed for {workflow_path}")
        return True

    encoded = base64.b64encode(updated.encode()).decode()
    resp = requests.put(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{workflow_path}",
        headers=GITHUB_HEADERS,
        json={"message": f"⏰ Optimize schedule: {workflow_path} [skip ci]",
              "content": encoded, "sha": sha, "branch": "main"}
    )
    if resp.ok:
        print(f"  ✓ Updated {workflow_path} → cron: {new_cron}")
        return True
    else:
        print(f"  ✗ Failed to update {workflow_path}: {resp.status_code}")
        return False

def main():
    print(f"\n⏰ LUCID REALMS — Upload Schedule Optimizer")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")

    print("1⃣  Analyzing upload performance data...")
    performance = analyze_upload_performance()

    if not performance or performance["sample_count"] < 9:
        sample = performance["sample_count"] if performance else 0
        print(f"  ℹ Only {sample} data points — need at least 9 uploads to optimize.")
        print("  Keeping current schedule unchanged.")
        return

    print(f"  ✓ Analyzed {performance['sample_count']} uploads")
    print(f"  Best hours UTC: {performance['best_hours'][:3]}\n")

    print("2⃣  Calculating optimal crons (gpt-4o-mini)...")
    config  = json.loads(CONFIG_PATH.read_text())
    optimal = get_optimal_crons_from_gpt(performance, config)
    print(f"  Reasoning: {optimal.get('reasoning', '')}")
    print(f"  Expected lift: {optimal.get('expected_improvement', 'unknown')}\n")

    print("3⃣  Updating workflow files on GitHub...")
    cron_map = {
        "morning":   optimal.get("morning_cron"),
        "afternoon": optimal.get("afternoon_cron"),
        "evening":   optimal.get("evening_cron")
    }

    updated_count = 0
    for slot, cron in cron_map.items():
        if cron:
            success = update_workflow_cron(SLOT_WORKFLOWS[slot], cron)
            if success:
                updated_count += 1

    # Save optimization to config
    config["schedule_optimization"] = {
        "last_run":             datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "best_hours_utc":       performance["best_hours"][:3],
        "applied_crons":        cron_map,
        "reasoning":            optimal.get("reasoning", ""),
        "expected_improvement": optimal.get("expected_improvement", "")
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2))

    print()
    print("─" * 50)
    print(f"⏰ Schedule Optimization Complete")
    print(f"   🌅 Morning:   {cron_map['morning']}")
    print(f"   ☀️  Afternoon: {cron_map['afternoon']}")
    print(f"   🌙 Evening:   {cron_map['evening']}")
    print(f"   📈 {optimal.get('expected_improvement', '')}")
    print("─" * 50)

if __name__ == "__main__":
    main()
