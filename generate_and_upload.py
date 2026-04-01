#!/usr/bin/env python3
"""
LUCID REALMS — Enhanced Video Generator & Uploader
- Multi-model: gpt-4o-mini for concepts/comments, DALL-E 3 for images
- A/B title testing: generates two variants, uploads with A, logs B for later swap
- Motion video: animates one scene via Runway Gen-3 if RUNWAY_API_KEY is set
- Runs 3x daily on GitHub Actions (morning / afternoon / evening slots)
"""

import os
import json
import time
import base64
import random
import requests
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── Credentials ─────────────────────────────────────────────────────────────
OPENAI_API_KEY    = os.environ["OPENAI_API_KEY"]
YT_CLIENT_ID      = os.environ["YOUTUBE_CLIENT_ID"]
YT_CLIENT_SECRET  = os.environ["YOUTUBE_CLIENT_SECRET"]
YT_REFRESH_TOKEN  = os.environ["YOUTUBE_REFRESH_TOKEN"]
UPLOAD_SLOT       = os.environ.get("UPLOAD_SLOT", "morning")
RUNWAY_API_KEY    = os.environ.get("RUNWAY_API_KEY", "")   # optional

CONFIG_PATH       = Path("config.json")
ANALYTICS_LOG     = Path("analytics_log.json")

OPENAI_HEADERS = {
    "Authorization": f"Bearer {OPENAI_API_KEY}",
    "Content-Type":  "application/json"
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

# ── Concept + A/B Titles (gpt-4o-mini) ───────────────────────────────────────
def generate_concept(config):
    """Use gpt-4o-mini for fast, cheap concept + two title variants."""
    strategy   = config.get("content_strategy", {})
    themes     = strategy.get("top_performing_themes", ["cosmic horror", "bioluminescent worlds"])
    seo        = strategy.get("seo", {})
    hooks      = seo.get("hooks", ["What lies beyond the edge of reality?"])
    trending   = config.get("trend_research", {}).get("viral_hook_patterns", [])
    weekly_rec = config.get("trend_research", {}).get("weekly_recommendation", "")

    prompt = f"""You are the creative director for LUCID REALMS, a YouTube Shorts channel posting surreal AI art.

Channel themes: {themes}
Slot: {UPLOAD_SLOT}
Hook styles: {hooks}
Weekly trend insight: {weekly_rec}
Viral hook patterns observed this week: {trending}

Generate a concept for one 30-second surreal AI Short. Return JSON:
{{
  "title_a": "<primary title — curiosity gap, ≤60 chars, no hashtags>",
  "title_b": "<alternate title — different angle, same video, ≤60 chars, no hashtags>",
  "description": "<2-3 sentences, include channel hook, relevant hashtags at end>",
  "scenes": [
    {{"prompt": "<detailed DALL-E image prompt, surreal/cosmic/bioluminescent>", "caption": "<2-5 word overlay text>"}},
    {{"prompt": "...", "caption": "..."}},
    {{"prompt": "...", "caption": "..."}},
    {{"prompt": "...", "caption": "..."}},
    {{"prompt": "...", "caption": "..."}},
    {{"prompt": "...", "caption": "..."}}
  ],
  "tags": ["<10 SEO tags>"],
  "motion_scene_index": 2
}}

Rules:
- title_a and title_b must feel DIFFERENT — different emotional angle or curiosity hook
- motion_scene_index: index of the scene (0-5) most suited for Runway animation
- All prompts: portrait orientation, 1080x1920, deep purple/electric blue/gold/teal palette
- First scene prompt must stop the scroll — the most visually striking"""

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=OPENAI_HEADERS,
        json={
            "model":           "gpt-4o-mini",
            "messages":        [{"role": "user", "content": prompt}],
            "temperature":     0.85,
            "response_format": {"type": "json_object"}
        }
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

# ── DALL-E 3 Image Generation ─────────────────────────────────────────────────
def generate_image(prompt):
    resp = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers=OPENAI_HEADERS,
        json={
            "model":   "dall-e-3",
            "prompt":  prompt + " Portrait orientation. Cinematic surreal art. Deep space aesthetic.",
            "size":    "1024x1792",
            "quality": "hd",
            "n":       1
        }
    )
    resp.raise_for_status()
    img_url = resp.json()["data"][0]["url"]
    img_resp = requests.get(img_url)
    img_resp.raise_for_status()
    return img_resp.content

# ── Text Overlay (Pillow) ─────────────────────────────────────────────────────
def add_text_overlay(img_bytes, caption, watermark="LUCID REALMS"):
    img = Image.open(__import__("io").BytesIO(img_bytes)).convert("RGBA")
    img = img.resize((1080, 1920), Image.LANCZOS)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    # Gradient bar at bottom
    for y in range(1600, 1920):
        alpha = int(200 * (y - 1600) / 320)
        draw.rectangle([(0, y), (1080, y)], fill=(10, 0, 30, alpha))

    try:
        font_cap  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
        font_wm   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    except Exception:
        font_cap = font_wm = ImageFont.load_default()

    # Caption text
    draw.text((540, 1820), caption.upper(), font=font_cap, fill=(255, 220, 100, 255), anchor="ms")
    # Watermark
    draw.text((540, 1880), watermark, font=font_wm, fill=(180, 180, 255, 180), anchor="ms")

    composite = Image.alpha_composite(img, overlay).convert("RGB")
    buf = __import__("io").BytesIO()
    composite.save(buf, format="JPEG", quality=95)
    return buf.getvalue()

# ── Runway Motion Video (optional) ────────────────────────────────────────────
def animate_with_runway(img_bytes, prompt_hint):
    """Animate a still image with Runway Gen-3 Turbo. Returns video bytes or None."""
    if not RUNWAY_API_KEY:
        return None

    try:
        print("  🎬 Animating scene with Runway Gen-3...")
        b64_image = base64.b64encode(img_bytes).decode()

        # Submit generation task
        resp = requests.post(
            "https://api.dev.runwayml.com/v1/image_to_video",
            headers={
                "Authorization": f"Bearer {RUNWAY_API_KEY}",
                "Content-Type":  "application/json",
                "X-Runway-Version": "2024-11-06"
            },
            json={
                "model":          "gen3a_turbo",
                "promptImage":    f"data:image/jpeg;base64,{b64_image}",
                "promptText":     f"Slow cinematic pan, surreal dreamscape. {prompt_hint}",
                "duration":       5,
                "ratio":          "720:1280",
                "watermark":      False
            },
            timeout=30
        )
        resp.raise_for_status()
        task_id = resp.json().get("id")
        if not task_id:
            return None

        # Poll for completion (max 3 min)
        for _ in range(36):
            time.sleep(5)
            poll = requests.get(
                f"https://api.dev.runwayml.com/v1/tasks/{task_id}",
                headers={"Authorization": f"Bearer {RUNWAY_API_KEY}", "X-Runway-Version": "2024-11-06"}
            )
            data = poll.json()
            status = data.get("status")
            if status == "SUCCEEDED":
                video_url = data["output"][0]
                video_resp = requests.get(video_url, timeout=60)
                print("  ✓ Runway animation complete")
                return video_resp.content
            elif status in ("FAILED", "CANCELLED"):
                print(f"  ⚠ Runway task {status} — using static frames")
                return None

        print("  ⚠ Runway timed out — using static frames")
        return None

    except Exception as e:
        print(f"  ⚠ Runway error: {e} — using static frames")
        return None

# ── ffmpeg Video Assembly ─────────────────────────────────────────────────────
def build_video(scenes_data, images, motion_clip=None, motion_index=None):
    """Assemble frames into a 1080x1920 MP4 with xfade transitions."""
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        frame_paths = []

        for i, img_bytes in enumerate(images):
            p = tmp / f"frame_{i:02d}.jpg"
            p.write_bytes(img_bytes)
            frame_paths.append(p)

        # If motion clip exists, write it as a separate video segment
        motion_video_path = None
        if motion_clip and motion_index is not None:
            mv_path = tmp / "motion_clip.mp4"
            mv_path.write_bytes(motion_clip)
            motion_video_path = mv_path

        # Build filter complex with xfade
        filter_parts = []
        inputs = []

        for i, fp in enumerate(frame_paths):
            if motion_video_path and i == motion_index:
                inputs += ["-i", str(motion_video_path)]
            else:
                inputs += ["-loop", "1", "-t", "5", "-i", str(fp)]

        n = len(frame_paths)
        streams = [f"[{i}:v]" for i in range(n)]

        # Scale all to 1080x1920
        scale_parts = []
        for i in range(n):
            scale_parts.append(f"{streams[i]}scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v{i}]")

        # xfade chain
        xfade_parts = []
        prev = "v0"
        for i in range(1, n):
            out = f"xf{i}" if i < n - 1 else "vout"
            offset = i * 5 - i * 0.5
            xfade_parts.append(f"[{prev}][v{i}]xfade=transition=fade:duration=0.5:offset={offset:.1f}[{out}]")
            prev = out

        filter_complex = ";".join(scale_parts + xfade_parts)

        out_path = tmp / "output.mp4"
        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + ["-filter_complex", filter_complex,
               "-map", "[vout]",
               "-c:v", "libx264", "-preset", "fast", "-crf", "23",
               "-pix_fmt", "yuv420p",
               "-r", "30",
               str(out_path)]
        )
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")
        return out_path.read_bytes()

# ── YouTube Upload ────────────────────────────────────────────────────────────
def upload_video(video_bytes, title, description, tags, token):
    metadata = {
        "snippet": {
            "title":       title,
            "description": description,
            "tags":        tags,
            "categoryId":  "22"
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}
    }

    # Initiate resumable upload
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization":     f"Bearer {token}",
            "Content-Type":      "application/json",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(len(video_bytes))
        },
        json=metadata
    )
    init.raise_for_status()
    upload_url = init.headers["Location"]

    # Upload video data
    resp = requests.put(
        upload_url,
        headers={"Content-Type": "video/mp4", "Content-Length": str(len(video_bytes))},
        data=video_bytes
    )
    resp.raise_for_status()
    video_id = resp.json()["id"]
    print(f"  ✓ Uploaded: https://youtube.com/shorts/{video_id}")
    return video_id

# ── Comment Post ──────────────────────────────────────────────────────────────
def post_comment(video_id, concept, token):
    """Post a pinned comment using gpt-4o-mini."""
    prompt = f"""Write a short engaging pinned comment for this YouTube Short titled "{concept.get('title_a', '')}".
The channel is LUCID REALMS — surreal AI art. Keep it under 150 chars. Make it mysterious and encourage interaction.
Return just the comment text, nothing else."""

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=OPENAI_HEADERS,
        json={
            "model":       "gpt-4o-mini",
            "messages":    [{"role": "user", "content": prompt}],
            "temperature": 0.9,
            "max_tokens":  80
        }
    )
    comment_text = resp.json()["choices"][0]["message"]["content"].strip()

    requests.post(
        "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {"snippet": {"textOriginal": comment_text}}
            }
        }
    )
    print(f"  ✓ Comment posted")

# ── Analytics Log ─────────────────────────────────────────────────────────────
def update_log(video_id, concept, slot, used_motion):
    log = json.loads(ANALYTICS_LOG.read_text()) if ANALYTICS_LOG.exists() else []
    log.append({
        "date":         datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "time_utc":     datetime.now(timezone.utc).strftime("%H:%M"),
        "slot":         slot,
        "video_id":     video_id,
        "title_a":      concept.get("title_a", ""),
        "title_b":      concept.get("title_b", ""),
        "ab_tested":    False,
        "active_title": "a",
        "used_motion":  used_motion,
        "tags":         concept.get("tags", [])
    })
    ANALYTICS_LOG.write_text(json.dumps(log, indent=2))

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\n🌀 LUCID REALMS — {UPLOAD_SLOT.capitalize()} Short")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")

    config = json.loads(CONFIG_PATH.read_text())

    print("1⃣  Refreshing YouTube token...")
    token = get_access_token()
    print("   ✓\n")

    print("2⃣  Generating concept (gpt-4o-mini)...")
    concept = generate_concept(config)
    print(f"   Title A: {concept['title_a']}")
    print(f"   Title B: {concept['title_b']}\n")

    print("3⃣  Generating scenes (DALL-E 3)...")
    images = []
    for i, scene in enumerate(concept["scenes"]):
        print(f"   Scene {i+1}/6...")
        raw = generate_image(scene["prompt"])
        processed = add_text_overlay(raw, scene["caption"])
        images.append(processed)
        time.sleep(1)
    print()

    # Optional Runway animation
    motion_clip  = None
    motion_index = concept.get("motion_scene_index", 2)
    used_motion  = False

    if RUNWAY_API_KEY:
        print("4⃣  Runway motion video...")
        motion_clip = animate_with_runway(
            images[motion_index],
            concept["scenes"][motion_index]["prompt"]
        )
        used_motion = motion_clip is not None
        print()
    else:
        print("4⃣  Runway not configured — using static frames\n")

    print("5⃣  Assembling video (ffmpeg)...")
    video_bytes = build_video(concept["scenes"], images, motion_clip, motion_index if used_motion else None)
    print(f"   {len(video_bytes)/1024/1024:.1f} MB\n")

    print("6⃣  Uploading to YouTube...")
    video_id = upload_video(video_bytes, concept["title_a"], concept["description"], concept.get("tags", []), token)
    print()

    print("7⃣  Posting comment (gpt-4o-mini)...")
    post_comment(video_id, concept, token)
    print()

    print("8⃣  Logging A/B test data...")
    update_log(video_id, concept, UPLOAD_SLOT, used_motion)
    print("   ✓\n")

    print("─" * 50)
    print(f"✅ {UPLOAD_SLOT.capitalize()} Short live!")
    print(f"   🅰  {concept['title_a']}")
    print(f"   🅱  {concept['title_b']} (queued for A/B test in 24h)")
    if used_motion:
        print(f"   🎬  Runway motion on scene {motion_index+1}")
    print("─" * 50)

if __name__ == "__main__":
    main()
