# 🤖 EZAYANI Downloader Bot — @EzayaniDownloadBot

A Telegram video-downloader bot like **@download_it_bot / SnapTube-style** apps:
user sends a link → bot detects the platform → user watches a short ad (**your
money link**) → bot downloads and sends the video back playable in chat, with
**⬇️ HD / 🎵 MP3 / 📤 Share** buttons under it.

**Supported:** TikTok (no watermark) • Instagram Reels • Facebook • YouTube
(HD + MP3) • Twitter/X • Pinterest.
**Languages:** auto-detected per user — 🇲🇦 Arabic (default) • 🇫🇷 French • 🇬🇧 English.
**Monetization:** ad shortlink gate (shrinkme.io / Monetag) + optional
force-subscribe to your channel (grow it → sell sponsored posts).

---

## 1️⃣ Create the bot with @BotFather (2 minutes)

1. Open Telegram → search **`@BotFather`** → `/start`
2. Send **`/newbot`**
   - Name: `EZAYANI Downloader Bot`
   - Username: `EzayaniDownloadBot` (must end in `bot`; if taken, pick a variant
     and update `BOT_USERNAME` in the config)
3. **Copy the token** → it looks like `1234567890:AAxxxxxxxx...`
4. Optional polish (paste into BotFather):
   - `/setdescription` → `حمّل أي فيديو في ثواني — تيك توك بدون علامة • انستغرام • فيسبوك • يوتيوب HD + MP3`
   - `/setabouttext` → `Download any video in seconds 🚀`
   - `/setuserpic` → upload your logo
   - `/setcommands` →
     ```
     start - القائمة الرئيسية / Menu
     help - مساعدة / Help
     ```
5. Disable privacy not needed (bot only reads direct messages by default).

---

## 2️⃣ Configure

Copy `.env.example` → `.env` (or set the variables in your host dashboard):

| Variable | What it does |
|---|---|
| `BOT_TOKEN` | **Required.** Token from BotFather |
| `CAPTION_CREDIT` | Footer on returned videos. Default `@download_it_bot` (screenshot behavior) — set e.g. `@EzayaniDownloadBot` to rebrand |
| `AD_LINK` | **Your money link** (shrinkme.io etc.) shown before every download |
| `AD_WAIT_SECONDS` | Seconds the user must spend before ✅ works (default 15) |
| `ENABLE_AD_STEP` | `1`/`0` — turn the ad gate on/off |
| `ENABLE_FORCE_SUB` | `1`/`0` — user must join your channel first |
| `FORCE_SUB_CHANNEL` | e.g. `@EzayaniChannel` — **add the bot as admin there!** |
| `ADMIN_IDS` | Your Telegram user ID (get it from `@userinfobot`) for `/stats` and `/broadcast` |
| `COBALT_API_URL` | Your own cobalt instance (recommended — see §5) |

---

## 3️⃣ Run locally (test it now)

```bash
pip install -r requirements.txt
BOT_TOKEN="paste_your_token" python bot.py
```

Open your bot in Telegram → `/start` → send a TikTok link. ✅

---

## 4️⃣ Deploy free 24/7

### Option A — Render (recommended, polling mode)
1. Push these files to a GitHub repo
2. [render.com](https://render.com) → **New → Background Worker** → connect repo
   (or just import `render.yaml` via **New → Blueprint**)
3. Build: `pip install -r requirements.txt` • Start: `python bot.py`
4. Add env vars: `BOT_TOKEN`, `AD_LINK`, … → **Deploy**

### Option B — Replit
1. New Repl → Python → upload `bot.py` + `requirements.txt`
2. **Secrets** tab → add `BOT_TOKEN`, `AD_LINK`, etc.
3. Run. The built-in health server answers on `PORT` — point
   [UptimeRobot](https://uptimerobot.com) (free) at the Repl URL every 5 min
   so it never sleeps.

### Option C — Webhook instead of polling
Set `WEBHOOK_URL=https://your-service.onrender.com` and deploy as a Render
**Web Service** — the bot binds `0.0.0.0:$PORT` and registers the webhook
automatically.

---

## 5️⃣ Download engines (important — read this)

The code tries backends **in order** until one works:

| Platform | Engines used (in order) |
|---|---|
| TikTok | `tikwm.com/api` (no watermark, HD) — works out of the box ✅ |
| YouTube | Piped instances → cobalt chain → yt-dlp |
| Facebook / Instagram / Twitter / Pinterest | cobalt chain → yt-dlp |

The cobalt chain tries, in order: **`https://co.wuk.sh/api/json`** (the exact
app v1.9 endpoint & dialect: `{"url", "isAudioOnly", "vQuality"}`) → community
instances → your own `COBALT_API_URL` if set (actually tried first when set).

⚠️ **Heads-up:** `co.wuk.sh`'s public API was shut down in Nov 2024, so today
it fails fast (6s cap) and the chain takes over — downloads keep working.
For a bot with real traffic you should host your own cobalt instance (free,
5 min): [Railway one-click cobalt deploy](https://railway.com/deploy/cobalt-tools)
→ copy your instance URL → set `COBALT_API_URL=https://your-app.up.railway.app`.
Community fallback instances are preconfigured and auto-updatable via
`COBALT_INSTANCES`.

**Best reliability addon (optional):** install `yt-dlp` + `ffmpeg` on the host
and the bot auto-uses them as the final fallback for every platform:

```bash
pip install yt-dlp && apt-get install ffmpeg   # on Render: add to build command
```

---

## 6️⃣ 💰 Monetization setup

### Route 1 — Paid ad link (per click)
1. Create a free account on **shrinkme.io** (or exe.io / shrinkforearn…)
2. Shorten any link → copy your `https://shrinkme.io/xxxxx`
3. Set `AD_LINK=https://shrinkme.io/xxxxx` → every download = 1 monetized view
   (~$3–$15 per 1000 views depending on country; MA/FR/EG traffic pays decently)
4. The bot forces a 15-second `AD_WAIT_SECONDS` dwell so users actually stay on
   the ad page (URL shorteners have no "watched" callback — this time-gate is
   how the big downloader bots do it).

### Route 2 — Monetag direct link (higher CPM, popunder)
Get a *Direct Link* in your Monetag publisher dashboard → set it as `AD_LINK`.

### Route 3 — Channel monetization
Keep `ENABLE_FORCE_SUB=1` → every user must join `@EzayaniChannel` → sell
sponsored posts on the channel yourself or list it on **Telega.io**.

You can run **all three** at once (join gate + ad gate + priority MP3 ads…).

---

## 7️⃣ Admin commands

- `/stats` — users, total downloads, jobs today
- `/broadcast` (reply to any message) — send a message to all users
  (perfect to announce new ad campaigns 😉)

---

## 8️⃣ Troubleshooting

| Problem | Fix |
|---|---|
| "تعذر التحميل" on videos sometimes | Backend busy — bot retries automatically via the 🔁 button; add your own `COBALT_API_URL` |
| Files over 50MB | Telegram Bot API limit. Run a [local bot-api server](https://core.telegram.org/bots/api#using-a-local-bot-api-server) and set `LOCAL_API_URL` → uploads up to **2GB**; otherwise the bot sends a direct-link button |
| Force-sub check always fails | Add the bot as **admin** in `@EzayaniChannel` |
| Instagram asks for login | Use your own cobalt instance (fresh IP) or yt-dlp fallback |
| Want to change texts | All strings are in the `T` dict at the top of `bot.py` (ar/fr/en) |

---

## ⚖️ Legal note

Only download content you own or that is freely redistributable; YouTube/Meta
ToS restrict unauthorized downloading. Keep the bot's `description` honest,
and comply with Telegram's bot rules (including their ad policies). You're
responsible for how you monetize and operate the bot.
