# LUCID REALMS — GitHub Actions Setup Guide

Follow these steps once. After that, videos upload automatically 3x/day even when your laptop is off.

---

## Step 1: Create a GitHub Account (if you don't have one)
Go to https://github.com and sign up. Free account is all you need.

---

## Step 2: Create a New Repository
1. Click the **+** icon (top right) → **New repository**
2. Name it: `lucid-realms-bot`
3. Set to **Private** (keeps your API keys safer)
4. Click **Create repository**

---

## Step 3: Upload These Files to GitHub
On the new repo page, click **uploading an existing file**, then drag the entire contents of this `lucid_realms_bot` folder into the upload area. Include:
- `generate_and_upload.py`
- `analytics_review.py`
- `requirements.txt`
- `config.json`
- `analytics_log.json`
- `.gitignore`
- `.github/` folder (with all 4 workflow files inside)

Click **Commit changes**.

---

## Step 4: Add Your API Keys as GitHub Secrets
This keeps your keys out of the code.

1. In your repo, go to **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret** for each of these:

| Secret Name | Value |
|---|---|
| `OPENAI_API_KEY` | Your OpenAI API key (from config.json) |
| `YOUTUBE_CLIENT_ID` | Your YouTube client ID (from config.json) |
| `YOUTUBE_CLIENT_SECRET` | Your YouTube client secret (from config.json) |
| `YOUTUBE_REFRESH_TOKEN` | Your YouTube refresh token (from config.json) |

---

## Step 5: Enable GitHub Actions
1. Click the **Actions** tab in your repo
2. If prompted, click **I understand my workflows, go ahead and enable them**

---

## Step 6: Test It (Optional but Recommended)
1. Click the **Actions** tab
2. Select **☀️ Afternoon Short (3 PM ET)** from the left sidebar
3. Click **Run workflow** → **Run workflow**
4. Watch the logs — it should generate and upload a video in about 3-4 minutes

---

## Schedule (Eastern Time)
| Workflow | Time |
|---|---|
| 📊 Analytics Review | 8:00 AM ET |
| 🌅 Morning Short | 9:00 AM ET |
| ☀️ Afternoon Short | 3:00 PM ET |
| 🌙 Evening Short | 8:00 PM ET |

> **Daylight Saving Note:** The cron times in the workflow files are set for EDT (summer, UTC-4).
> From November to March (EST, UTC-5), add 1 hour to each cron value.
> The workflows have a comment showing the EST version.

---

## Monitoring
- Click the **Actions** tab anytime to see run history and logs
- `analytics_log.json` in the repo is automatically updated after every upload
- The daily analytics run posts a monetization progress report in its logs

---

## Troubleshooting
- **"Error 403 insufficientPermissions"** — Your refresh token may have expired. Re-run the OAuth flow and update the `YOUTUBE_REFRESH_TOKEN` secret.
- **"ffmpeg: command not found"** — Should not happen on GitHub Actions (ubuntu-latest has it). If it does, the workflow installs it automatically.
- **Workflow not triggering** — GitHub can occasionally delay scheduled workflows by up to 15 minutes. Manual trigger via the Actions tab always works immediately.
