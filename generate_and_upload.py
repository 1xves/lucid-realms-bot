#!/usr/bin/env python3
"""
LUCID REALMS — YouTube Shorts Auto-Generator
Runs on GitHub Actions 3x/day to generate and upload AI-animated Shorts.
No browser required — all API calls are direct HTTP requests.
"""

import os
import sys
import json
import time
import requests
import subprocess
import textwrap
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── Config from environment variables (GitHub Secrets) ───────────────────────

OPENAI_API_KEY    = os.environ["OPENAI_API_KEY"]
YT_CLIENT_ID      = os.environ["YOUTUBE_CLIENT_ID"]
YT_CLIENT_SECRET  = os.environ["YOUTUBE_CLIENT_SECRET"]
YT_REFRESH_TOKEN  = os.environ["YOUTUBE_REFRESH_TOKEN"]
UPLOAD_SLOT       = os.environ.get("UPLOAD_SLOT", "morning")  # morning | afternoon | evening

CHANNEL_THEME = (
    "Surreal AI art: cinematic journeys through impossible worlds. Each Short is a 45-second "
    "visual odyssey — glitching dreamscapes, cosmic horror, bioluminescent alien worlds, and "
    "breathtaking sci-fi realms. Use strong curiosity-gap titles with an emoji. Open every Short "
    "with a jaw-dropping scene that stops the scroll. Narration should be poetic and mysterious, "
    "8-12 words per line. Visual style: deep purple, electric blue, gold, teal. Make each scene "
    "flow into the next like a fever dream. Optimize for rewatch loops — end on an image that "
    "makes viewers want to start over."
)

TOP_THEMES = [
    "surreal dreamscape", "cosmic horror", "bioluminescent worlds",
    "impossible architecture", "alien civilizations", "time collapsing"
]

TAGS = [
    "AI art", "surreal art", "AI video", "shorts", "cosmic horror",
    "dreamscape", "sci-fi art", "AI generated", "bioluminescent",
    "impossible worlds", "visual odyssey", "lucid realms", "alien worlds", "AI animation"
]

ANALYTICS_LOG = Path("analytics_log.json")

# ── Step 1: OAuth ─────────────────────────────────────────────────────────────

def get_access_token():
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     YT_CLIENT_ID,
        "client_secret": YT_CLIENT_SECRET,
        "refresh_token": YT_REFRESH_TOKEN,
        "grant_type":    "refresh_token"
    })
    resp.raise_for_status()
    return resp.json()["access_token"]

# ── Step 2: Concept Generation ────────────────────────────────────────────────

def get_recent_themes():
    if not ANALYTICS_LOG.exists():
        return []
    log = json.loads(ANALYTICS_LOG.read_text())
    return [e.get("theme") for e in log[-6:] if e.get("theme")]

def generate_concept():
    recent = get_recent_themes()
    avoid  = ", ".join(recent) if recent else "none"

    prompt = f"""You are the creative director for LUCID REALMS, a YouTube Shorts channel.
Channel theme: {CHANNEL_THEME}

Available themes: {', '.join(TOP_THEMES)}
Recently used (avoid repeating): {avoid}

Generate a unique concept that maximizes rewatch loops and shareability.
Return ONLY valid JSON — no markdown, no explanation:

{{
  "theme": "<one of the available themes>",
  "title": "<emoji> <curiosity-gap hook under 55 chars> #Shorts",
  "description": "🌌 Welcome to LUCID REALMS — where AI dreams become reality.\\n\\n<2-3 sentence immersive description of this video>\\n\\n🔔 Subscribe for daily surreal AI journeys → @LucidRealms\\n\\n#AIArt #Shorts #SurrealArt #AIVideo #CosmicHorror #DreamWorld #SciFiArt #AIGenerated #VisualArt #SurrealDream",
  "narration": [
    "<line 1, 8-12 words, builds tension>",
    "<line 2>",
    "<line 3>",
    "<line 4>",
    "<line 5>",
    "<line 6>",
    "<line 7>",
    "Subscribe to enter the next realm."
  ],
  "scenes": [
    "<DALL-E prompt 1 — most visually shocking opening scene, ultra-cinematic, 9:16 portrait, deep purple/electric blue/gold/teal palette, photorealistic lighting, no text, no watermarks>",
    "<DALL-E prompt 2 — continuation, escalating wonder>",
    "<DALL-E prompt 3>",
    "<DALL-E prompt 4>",
    "<DALL-E prompt 5>",
    "<DALL-E prompt 6 — loops visually back to scene 1 energy>"
  ],
  "pinned_comment": "🌌 <engaging question that drives comments, 10-15 words> 👇"
}}"""

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
            "response_format": {"type": "json_object"}
        }
    )
    resp.raise_for_status()
    return json.loads(resp.json()["choices"][0]["message"]["content"])

# ── Step 3: DALL-E 3 Image Generation ────────────────────────────────────────

def generate_image(prompt, index, output_dir):
    print(f"  Generating scene {index + 1}/6...")
    resp = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={
            "model":   "dall-e-3",
            "prompt":  prompt,
            "size":    "1024x1792",
            "quality": "hd",
            "n":       1
        }
    )
    resp.raise_for_status()
    image_url = resp.json()["data"][0]["url"]

    img_data = requests.get(image_url)
    img_data.raise_for_status()

    path = output_dir / f"scene_{index:02d}.png"
    path.write_bytes(img_data.content)
    return path

# ── Step 4: Text Overlay ──────────────────────────────────────────────────────

def add_text_overlay(scene_path, narration_line, frame_path):
    img = Image.open(scene_path).convert("RGBA")
    img = img.resize((1080, 1920), Image.LANCZOS)

    # Gradient overlay at bottom third
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    for y in range(1450, 1920):
        alpha = int(210 * (y - 1450) / 470)
        ov_draw.line([(0, y), (1080, y)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img, overlay)

    draw = ImageDraw.Draw(img)

    # Font — try system fonts in order
    font = None
    for fp in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        try:
            font = ImageFont.truetype(fp, 54)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    wrapped = textwrap.fill(narration_line, width=24)
    bbox    = draw.textbbox((0, 0), wrapped, font=font)
    text_w  = bbox[2] - bbox[0]
    x = (1080 - text_w) // 2
    y = 1680

    # Drop shadow then white text
    draw.text((x + 3, y + 3), wrapped, font=font, fill=(0, 0, 0, 200))
    draw.text((x,     y    ), wrapped, font=font, fill=(255, 255, 255, 255))

    img.convert("RGB").save(frame_path, quality=95)

# ── Step 5: ffmpeg Assembly ───────────────────────────────────────────────────

def build_video(work_dir, output_path):
    concat_path = work_dir / "concat.txt"
    durations   = [7, 7, 7, 8, 8, 8]

    with open(concat_path, "w") as f:
        for i, dur in enumerate(durations):
            frame = (work_dir / f"frame_{i:02d}.jpg").absolute()
            f.write(f"file '{frame}'\nduration {dur}\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-vf", (
            "scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(output_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("ffmpeg stderr:", result.stderr[-2000:])
        raise RuntimeError("ffmpeg failed")
    size_kb = output_path.stat().st_size // 1024
    print(f"  Video assembled: {size_kb} KB")

# ── Step 6: YouTube Upload ────────────────────────────────────────────────────

def upload_video(video_path, title, description, access_token):
    file_size = video_path.stat().st_size

    # Initiate resumable upload
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization":          f"Bearer {access_token}",
            "Content-Type":           "application/json",
            "X-Upload-Content-Type":  "video/mp4",
            "X-Upload-Content-Length": str(file_size)
        },
        json={
            "snippet": {
                "title":           title,
                "description":     description,
                "tags":            TAGS,
                "categoryId":      "22",
                "defaultLanguage": "en"
            },
            "status": {
                "privacyStatus":            "public",
                "selfDeclaredMadeForKids":  False
            }
        }
    )
    init.raise_for_status()
    upload_url = init.headers["Location"]

    # Upload binary
    print("  Uploading video binary...")
    with open(video_path, "rb") as f:
        video_data = f.read()

    upload = requests.put(
        upload_url,
        headers={
            "Content-Type":   "video/mp4",
            "Content-Length": str(len(video_data))
        },
        data=video_data
    )
    upload.raise_for_status()
    video_id = upload.json()["id"]
    print(f"  Uploaded! ID: {video_id}")
    return video_id

# ── Step 7: Pin Comment ───────────────────────────────────────────────────────

def post_comment(video_id, text, access_token):
    resp = requests.post(
        "https://www.googleapis.com/youtube/v3/commentThreads?part=snippet",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {"snippet": {"textOriginal": text}}
            }
        }
    )
    if resp.ok:
        print(f"  Comment posted: {resp.json()['id']}")
    else:
        print(f"  Comment skipped ({resp.status_code}): {resp.text[:200]}")

# ── Step 8: Analytics Log ─────────────────────────────────────────────────────

def update_log(video_id, title, theme):
    log = json.loads(ANALYTICS_LOG.read_text()) if ANALYTICS_LOG.exists() else []
    log.append({
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "upload_slot": UPLOAD_SLOT,
        "video_id":    video_id,
        "video_url":   f"https://www.youtube.com/shorts/{video_id}",
        "title":       title,
        "theme":       theme,
        "status":      "uploaded"
    })
    ANALYTICS_LOG.write_text(json.dumps(log, indent=2))
    print(f"  Log updated ({len(log)} total uploads)")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n🌌 LUCID REALMS — {UPLOAD_SLOT.upper()} Short")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        print("1️⃣  Refreshing YouTube token...")
        token = get_access_token()
        print("   ✓ Token ready\n")

        print("2️⃣  Generating concept with GPT-4o...")
        concept = generate_concept()
        title   = concept["title"]
        desc    = concept["description"]
        narr    = concept["narration"]
        scenes  = concept["scenes"]
        theme   = concept["theme"]
        comment = concept.get("pinned_comment", "🌌 Which realm calls to you? Comment below 👇")
        print(f"   ✓ Theme: {theme}")
        print(f"   ✓ Title: {title}\n")

        print("3️⃣  Generating 6 DALL-E 3 scenes...")
        for i, scene_prompt in enumerate(scenes):
            generate_image(scene_prompt, i, work)
            time.sleep(1)  # avoid rate limit
        print("   ✓ All scenes generated\n")

        print("4️⃣  Adding text overlays...")
        for i in range(6):
            add_text_overlay(
                work / f"scene_{i:02d}.png",
                narr[i],
                work / f"frame_{i:02d}.jpg"
            )
        print("   ✓ Overlays applied\n")

        print("5️⃣  Assembling video with ffmpeg...")
        video_path = work / "output_short.mp4"
        build_video(work, video_path)
        print("   ✓ Video ready\n")

        print("6️⃣  Uploading to YouTube...")
        video_id = upload_video(video_path, title, desc, token)

        print("\n7️⃣  Posting pinned comment...")
        post_comment(video_id, comment, token)

        print("\n8️⃣  Updating analytics log...")
        update_log(video_id, title, theme)

        print(f"\n✅  SUCCESS — {UPLOAD_SLOT} Short live!")
        print(f"    https://www.youtube.com/shorts/{video_id}")
        print(f"    {title}\n")

if __name__ == "__main__":
    main()
