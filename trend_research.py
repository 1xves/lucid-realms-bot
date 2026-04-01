#!/usr/bin/env python3
"""
LUCID REALMS — Weekly Trend Research Agent
- gpt-4o-mini: filters and preprocesses raw YouTube/Reddit/web data
- gpt-4o: synthesizes into final strategy recommendations
- Runs every Monday 8 AM ET on GitHub Actions
"""

import os, json, time, requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

OPENAI_API_KEY   = os.environ["OPENAI_API_KEY"]
YT_CLIENT_ID     = os.environ["YOUTUBE_CLIENT_ID"]
YT_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YT_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]

CONFIG_PATH    = Path("config.json")
ANALYTICS_LOG  = Path("analytics_log.json")
REDDIT_HEADERS = {"User-Agent": "LucidRealmsResearchBot/1.0"}
OPENAI_HEADERS = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

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

# ── YouTube Research ──────────────────────────────────────────────────────────

def search_youtube_trending(query, token, max_results=10):
    published_after = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/search",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "part":           "snippet",
            "type":           "video",
            "q":              query,
            "videoDuration":  "short",
            "order":          "viewCount",
            "publishedAfter": published_after,
            "maxResults":     max_results
        }
    )
    if not resp.ok:
        print(f"  YouTube search failed for '{query}': {resp.status_code}")
        return []
    items = resp.json().get("items", [])
    return [
        {
            "title":       item["snippet"]["title"],
            "channel":     item["snippet"]["channelTitle"],
            "description": item["snippet"]["description"][:150]
        }
        for item in items
    ]

def youtube_research(token):
    print("  Searching YouTube for trending AI content...")
    queries = [
        "AI art surreal cinematic shorts",
        "surreal dreamscape AI video",
        "cosmic horror AI generated",
        "AI animation bioluminescent",
        "liminal spaces AI art"
    ]
    results = []
    for q in queries:
        hits = search_youtube_trending(q, token)
        results.extend(hits)
        time.sleep(0.5)
    print(f"  Found {len(results)} YouTube videos")
    return results

# ── Reddit Research ───────────────────────────────────────────────────────────

def fetch_reddit_top(subreddit, timeframe="week", limit=10):
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t={timeframe}&limit={limit}"
    try:
        resp = requests.get(url, headers=REDDIT_HEADERS, timeout=10)
        if not resp.ok:
            return []
        posts = resp.json().get("data", {}).get("children", [])
        return [
            {
                "title": p["data"]["title"],
                "score": p["data"]["score"],
                "subreddit": subreddit
            }
            for p in posts
        ]
    except Exception as e:
        print(f"  Reddit {subreddit} failed: {e}")
        return []

def reddit_research():
    print("  Scanning Reddit AI art communities...")
    subreddits = ["AIArt", "MediaSynthesis", "StableDiffusion", "woahdude", "deepdream"]
    results = []
    for sub in subreddits:
        posts = fetch_reddit_top(sub)
        results.extend(posts)
        time.sleep(0.5)
    results.sort(key=lambda x: x["score"], reverse=True)
    print(f"  Found {len(results)} Reddit posts")
    return results[:20]

# ── DuckDuckGo Web Search ────────────────────────────────────────────────────

def web_search(query, max_results=5):
    """Search via DuckDuckGo instant answer API (no key required)."""
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_redirect": "1", "no_html": "1"},
            timeout=10
        )
        data = resp.json()
        results = []
        # Abstract summary
        if data.get("Abstract"):
            results.append(data["Abstract"][:300])
        # Related topics
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(topic["Text"][:200])
        return results
    except Exception as e:
        print(f"  Web search failed for '{query}': {e}")
        return []

def web_research():
    print("  Running web searches...")
    queries = ["AI generated video viral 2026", "surreal AI art trending social media 2026",
               "best performing AI shorts YouTube 2026", "viral dreamcore content creators"]
    results = {}
    for q in queries:
        hits = web_search(q)
        if hits:
            results[q] = hits
        time.sleep(0.3)
    return results

# ── gpt-4o-mini: Filter and score raw data ─────────────────────────────────────
def preprocess_data(yt_data, reddit_data, web_data):
    """Use gpt-4o-mini to filter noise and score relevance before full synthesis."""
    yt_titles     = [v["title"] for v in yt_data[:20]]
    reddit_titles = [f"{p['title']} (score: {p['score']})" for p in reddit_data[:15]]
    web_snippets  = [f"{k}: {v[0]}" for k, v in list(web_data.items())[:4] if v]

    prompt = f"""Filter and score the following raw trend data for relevance to a surreal AI art YouTube Shorts channel (LUCID REALMS).
Remove off-topic items. Identify the 5 most signal-rich items from each source.

YouTube titles this week:
{chr(10).join(f'- {t}' for t in yt_titles)}

Reddit top posts:
{chr(10).join(f'- {p}' for p in reddit_titles)}

Web signals:
{chr(10).join(f'- {s}' for s in web_snippets)}

Return JSON:
{{
  "top_yt_signals": ["<5 most relevant YouTube titles>"],
  "top_reddit_signals": ["<5 most relevant Reddit posts>"],
  "top_web_signals": ["<3 most relevant web insights>"],
  "noise_removed": "<what you filtered out and why>"
}}"""

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=OPENAI_HEADERS,
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
              "response_format": {"type": "json_object"}, "temperature": 0.3}
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

# ── gpt-4o: Final synthesis ───────────────────────────────────────────────────
def synthesize_with_gpt4o(filtered, current_config):
    print("  Synthesizing with gpt-4o...")
    current_themes = current_config.get("content_strategy", {}).get("top_performing_themes", [])
    existing       = current_config.get("trend_research", {})

    prompt = f"""You are the strategic director for LUCID REALMS, a YouTube Shorts channel for surreal AI art.

CURRENT THEMES: {current_themes}
LAST WEEK'S RECOMMENDATION: {existing.get('weekly_recommendation', 'N/A')}

THIS WEEK'S FILTERED TREND SIGNALS:
YouTube: {filtered.get('top_yt_signals', [])}
Reddit:  {filtered.get('top_reddit_signals', [])}
Web:     {filtered.get('top_web_signals', [])}

Return a JSON strategy update:
{{
  "trending_themes_to_add": ["<1-2 NEW themes not in active list that fit LUCID REALMS brand>"],
  "declining_themes_to_retire": ["<themes showing fatigue in the data>"],
  "viral_hook_patterns": ["<3-4 specific hook patterns from top content this week>"],
  "title_insights": "<specific title format working this week — be concrete>",
  "visual_style_trends": "<emerging visual aesthetics gaining traction — be specific>",
  "competitor_gaps": "<one specific content angle no one is covering that fits LUCID REALMS>",
  "weekly_recommendation": "<one concrete direction for this week's 3 daily Shorts — include a sample title>",
  "sources_summary": "<2-3 sentence summary of what the data showed this week>"
}}"""

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=OPENAI_HEADERS,
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": prompt}],
              "response_format": {"type": "json_object"}, "temperature": 0.7}
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

# ── Update Config ─────────────────────────────────────────────────────────────

def update_config(strategy):
    config = json.loads(CONFIG_PATH.read_text())

    # Update trend_research section
    config["trend_research"] = {
        "last_updated":              datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "trending_themes":           strategy.get("trending_themes_to_add", []),
        "declining_themes":          strategy.get("declining_themes_to_retire", []),
        "viral_hook_patterns":       strategy.get("viral_hook_patterns", []),
        "title_insights":            strategy.get("title_insights", ""),
        "visual_style_trends":       strategy.get("visual_style_trends", ""),
        "competitor_gaps":           strategy.get("competitor_gaps", ""),
        "weekly_recommendation":     strategy.get("weekly_recommendation", ""),
        "sources_summary":           strategy.get("sources_summary", "")
    }

    # Merge new themes into top_performing_themes (max 2 new per week)
    current_themes = config["content_strategy"]["top_performing_themes"]
    new_themes     = strategy.get("trending_themes_to_add", [])
    retiring       = strategy.get("declining_themes_to_retire", [])

    # Remove retiring themes
    updated_themes = [t for t in current_themes if t not in retiring]

    # Add new themes (avoid duplicates, cap at 2 new per run)
    added = 0
    for theme in new_themes:
        if theme not in updated_themes and added < 2:
            updated_themes.append(theme)
            added += 1

    config["content_strategy"]["top_performing_themes"] = updated_themes
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    print("  ✓ Config updated")
    return config

def main():
    print(f"\n🔍 LUCID REALMS — Weekly Trend Research")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")
    config = json.loads(CONFIG_PATH.read_text())

    print("1⃣  Refreshing YouTube token...")
    token = get_access_token()
    print("   ✓\n")

    print("2⃣  Gathering raw data...")
    yt_data     = youtube_research(token)
    reddit_data = reddit_research()
    web_data    = web_research()
    print()

    print("3⃣  Filtering + scoring (gpt-4o-mini)...")
    filtered = preprocess_data(yt_data, reddit_data, web_data)
    print(f"   Noise removed: {filtered.get('noise_removed', '')[:80]}\n")

    print("4⃣  Synthesizing strategy (gpt-4o)...")
    strategy = synthesize_with_gpt4o(filtered, config)
    print()

    print("5⃣  Updating config...")
    update_config(strategy)
    print()

    print("─" * 50)
    print(f"📺 LUCID REALMS — Trend Report {datetime.now().strftime('%Y-%m-%d')}")
    print("─" * 50)
    print(f"📈 New themes:   {strategy.get('trending_themes_to_add', [])}")
    print(f"📉 Retiring:     {strategy.get('declining_themes_to_retire', [])}")
    print(f"🎯 This week:    {strategy.get('weekly_recommendation', '')[:100]}")
    print(f"🔬 Models:       gpt-4o-mini (filter) → gpt-4o (synthesis)")
    print("─" * 50)

if __name__ == "__main__":
    main()
