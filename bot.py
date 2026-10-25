#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===============================================================================
  EZAYANI Downloader Bot  -  @EzayaniDownloadBot
  "حمّل أي فيديو في ثواني"  — TikTok (no watermark) • Instagram • Facebook
  YouTube (HD + MP3) • Twitter/X • Pinterest

  Flow (exactly like the app):
    1) User sends a link
    2) Bot detects the platform
    3) MONETIZATION STEP: user must watch a short ad (shrinkme/monetag link)
       [optional: force-join your channel first] then press "✅ تأكيد"
    4) Bot downloads the video and sends it back playable, with buttons:
       [⬇️ تحميل HD] [🎵 تحميل MP3] [📤 مشاركة]

  Everything is configured at the top under CONFIG or via environment
  variables so you never have to edit logic code.
===============================================================================
"""

import asyncio
import concurrent.futures
import glob
import html
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, constants
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =============================================================================
#  CONFIG — edit here or (better) set environment variables on your host
# =============================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_FROM_BOTFATHER")   # <<<<<< REPLACE
BOT_USERNAME = os.getenv("BOT_USERNAME", "@EzayaniDownloadBot")   # your bot's own handle
BOT_NAME = os.getenv("BOT_NAME", "EZAYANI Downloader")
# Footer shown on every returned video — matches the @download_it_bot screenshot
# behavior. Switch to your own handle anytime via env CAPTION_CREDIT.
CAPTION_CREDIT = os.getenv("CAPTION_CREDIT", "@download_it_bot")

# ---- Monetization ------------------------------------------------------------
# 1) Paid ad shortlink (shrinkme.io, monetag smartlink, exe.io, ...)
AD_LINK = os.getenv("AD_LINK", "https://shrinkme.io/YOUR_AD_LINK")
ENABLE_AD_STEP = os.getenv("ENABLE_AD_STEP", "1") == "1"          # 0 = no ad gate
AD_WAIT_SECONDS = int(os.getenv("AD_WAIT_SECONDS", "1005"))         # min. seconds on ad

# 2) Alternative monetization: force users to join your channel (grow it,
#    then publish sponsored posts / Telega.io ads on the channel)
ENABLE_FORCE_SUB = os.getenv("ENABLE_FORCE_SUB", "1") == "1"      # 0 = off
FORCE_SUB_CHANNEL = os.getenv("FORCE_SUB_CHANNEL", "@EzayaniChannel")   # bot MUST be admin there
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/EzayaniChannel")

# ---- Limits ------------------------------------------------------------------
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", "10"))   # 1 link / X sec / user
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "49"))             # Bot API hard limit ≈ 50MB
MAX_URL_MB = int(os.getenv("MAX_URL_MB", "20"))                   # telegram URL-sending limit
DB_PATH = os.getenv("DB_PATH", "ezayani_bot.db")

# ---- Admins (comma-separated Telegram user IDs) ------------------------------
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()}

# ---- Download backends -------------------------------------------------------
# TikTok: tikwm (no watermark) works out of the box.
TIKWM_API = os.getenv("TIKWM_API", "https://tikwm.com/api/")

# Everything else -> cobalt instances (the old co.wuk.sh public API was shut
# down in Nov 2024, so we try several + your own self-hosted one first).
# One-click self-host: see README ("Deploy your own cobalt") then set
# COBALT_API_URL=https://your-instance.onrender.com
_own = os.getenv("COBALT_API_URL", "").strip().rstrip("/")
COBALT_API_KEY = os.getenv("COBALT_API_KEY", "")                  # if your instance needs it
# co.wuk.sh/api/json stays FIRST per the app v1.9 spec — the bot POSTs to it in
# the legacy dialect ({"url", "isAudioOnly", "vQuality"}). NOTE: that public
# endpoint was shut down in Nov 2024, so it gets a short timeout and the chain
# below takes over automatically. Tracker for fresh instances: https://instances.cobalt.best
COBALT_INSTANCES = ([_own] if _own else []) + [i.strip().rstrip("/") for i in os.getenv(
    "COBALT_INSTANCES",
    "https://co.wuk.sh,"
    "https://co.otomir23.me,"
    "https://downloadapi.stuff.solutions,"
    "https://cobalt-api.kwiatekmiki.com,"
    "https://capi.oak.li,"
    "https://cobalt-backend.canine.tools",
).split(",") if i.strip()]

# YouTube fallback: Piped instances (video id is extracted from the link)
# Defaults live-tested (2026-10): private.coffee + ducks.party returned streams.
# Refresh list from: https://piped.video
PIPED_INSTANCES = [i.strip().rstrip("/") for i in os.getenv(
    "PIPED_INSTANCES",
    "https://api.piped.private.coffee,"
    "https://pipedapi.ducks.party,"
    "https://pipedapi.adminforge.de,"
    "https://pipedapi.kavin.rocks",
).split(",") if i.strip()]

# Last-resort fallback if yt-dlp (+ffmpeg) is installed on the host.
USE_YTDLP_FALLBACK = os.getenv("USE_YTDLP_FALLBACK", "1") == "1"

# Optional: run against a local telegram-bot-api server (uploads up to 2GB!)
# https://core.telegram.org/bots/api#using-a-local-bot-api-server
LOCAL_API_URL = os.getenv("LOCAL_API_URL", "").rstrip("/")        # e.g. http://localhost:8081

# Webhook mode (Render web services). Leave empty for polling mode.
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")            # e.g. https://ezayani-bot.onrender.com
PORT = int(os.getenv("PORT", "8080"))

HTTP_TIMEOUT = 30
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) EZAYANIBot/1.0"}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("ezayani")

# =============================================================================
#  MULTILINGUAL — language auto-detected from each user's Telegram settings
# =============================================================================

def lang_of(update: Update) -> str:
    code = (update.effective_user.language_code or "ar").lower() if update.effective_user else "ar"
    if code.startswith("ar"):
        return "ar"
    if code.startswith("fr"):
        return "fr"
    return "en"

PLATFORMS = {
    "tiktok":    {"ar": "تيك توك (بدون علامة مائية) 🎵", "fr": "TikTok (sans filigrane) 🎵", "en": "TikTok (no watermark) 🎵"},
    "instagram": {"ar": "انستغرام Reels 📸",            "fr": "Instagram Reels 📸",          "en": "Instagram Reels 📸"},
    "facebook":  {"ar": "فيسبوك — فيديو بجودة عالية 👍", "fr": "Facebook — vidéo HD 👍",      "en": "Facebook — HD video 👍"},
    "youtube":   {"ar": "يوتيوب ▶️",                    "fr": "YouTube ▶️",                   "en": "YouTube ▶️"},
    "twitter":   {"ar": "تويتر / X 🐦",                 "fr": "Twitter / X 🐦",               "en": "Twitter / X 🐦"},
    "pinterest": {"ar": "Pinterest 📌",                 "fr": "Pinterest 📌",                 "en": "Pinterest 📌"},
}

T = {
    "welcome": {
        "ar": (
            "👋 <b>أهلاً بك في {name}!</b>\n\n"
            "⬇️ <b>حمّل أي فيديو في ثواني - تيك توك بدون علامة • انستغرام • فيسبوك • يوتيوب بجودة عالية</b>\n\n"
            "📎 فقط أرسل رابط الفيديو هنا 👇"
        ),
        "fr": (
            "👋 <b>Bienvenue sur {name}!</b>\n\n"
            "⬇️ <b>Télécharge n'importe quelle vidéo en quelques secondes</b>\n"
            "• 🎵 TikTok — sans filigrane\n• 📸 Instagram Reels\n• 👍 Facebook — HD\n"
            "• ▶️ YouTube — HD + MP3\n• 🐦 Twitter/X  •  📌 Pinterest\n\n"
            "📎 Envoie simplement le lien de la vidéo 👇"
        ),
        "en": (
            "👋 <b>Welcome to {name}!</b>\n\n"
            "⬇️ <b>Download any video in seconds</b>\n"
            "• 🎵 TikTok — no watermark\n• 📸 Instagram Reels\n• 👍 Facebook — HD\n"
            "• ▶️ YouTube — HD + MP3\n• 🐦 Twitter/X  •  📌 Pinterest\n\n"
            "📎 Just paste the video link here 👇"
        ),
    },
    "how": {
        "ar": "📖 <b>طريقة الاستخدام:</b>\n\n1️⃣ انسخ رابط الفيديو من أي تطبيق\n2️⃣ أرسله هنا\n3️⃣ شاهد الإعلان القصير (لدعمنا ❤️)\n4️⃣ اضغط ✅ وسيصلك الفيديو فوراً!",
        "fr": "📖 <b>Comment faire:</b>\n\n1️⃣ Copie le lien de la vidéo\n2️⃣ Envoie-le ici\n3️⃣ Regarde la petite pub (merci ❤️)\n4️⃣ Appuie sur ✅ et reçois ta vidéo!",
        "en": "📖 <b>How to use:</b>\n\n1️⃣ Copy any video link\n2️⃣ Send it here\n3️⃣ Watch the short ad (support us ❤️)\n4️⃣ Tap ✅ and get your video instantly!",
    },
    "btn_how":  {"ar": "📖 طريقة الاستخدام", "fr": "📖 Comment ça marche", "en": "📖 How to use"},
    "btn_channel": {"ar": "📢 قناتنا", "fr": "📢 Notre chaîne", "en": "📢 Our channel"},
    "detected": {"ar": "🔍 تم اكتشاف: <b>{platform}</b> ✅",
                 "fr": "🔍 Détecté: <b>{platform}</b> ✅",
                 "en": "🔍 Detected: <b>{platform}</b> ✅"},
    "ad_prompt": {
        "ar": "\n\n💰 التحميل <b>مجاني 100%</b>! لدعمنا 🙏:\nشاهد إعلاناً قصيراً ({secs} ثانية) ثم اضغط زر التأكيد 👇",
        "fr": "\n\n💰 C'est <b>100% gratuit</b>! Pour nous soutenir 🙏:\nregarde une pub de {secs}s puis appuie sur confirmer 👇",
        "en": "\n\n💰 Downloads are <b>100% free</b>! Support us 🙏:\nwatch a {secs}s ad then tap confirm 👇",
    },
    "btn_watch_ad": {"ar": "▶️ شاهد الإعلان و حمّل", "fr": "▶️ Voir la pub & télécharger", "en": "▶️ Watch ad & download"},
    "btn_confirm":  {"ar": "✅ شاهدت الإعلان — حمّل الآن", "fr": "✅ Pub vue — télécharger", "en": "✅ I watched — download now"},
    "join_prompt": {
        "ar": "📢 قبل التحميل، انضم إلى قناتنا ثم اضغط تأكيد 👇",
        "fr": "📢 Rejoins d'abord notre chaîne puis appuie sur confirmer 👇",
        "en": "📢 Join our channel first, then tap confirm 👇",
    },
    "btn_join":   {"ar": "📢 انضم إلى القناة", "fr": "📢 Rejoindre la chaîne", "en": "📢 Join channel"},
    "btn_joined": {"ar": "✅ انضممت — تحقق", "fr": "✅ J'ai rejoint — vérifier", "en": "✅ Joined — verify"},
    "not_joined": {"ar": "❌ لم تنضم بعد إلى القناة!", "fr": "❌ Tu n'as pas encore rejoint la chaîne!", "en": "❌ You haven't joined the channel yet!"},
    "ad_wait":    {"ar": "⏳ انتظر {secs} ثانية بعد فتح الإعلان ثم اضغط تأكيد ⏱",
                   "fr": "⏳ Attends encore {secs}s après avoir ouvert la pub ⏱",
                   "en": "⏳ Please wait {secs}s after opening the ad ⏱"},
    "downloading": {"ar": "⏳ جاري تحميل الفيديو من {platform}...", "fr": "⏳ Téléchargement depuis {platform}...", "en": "⏳ Downloading from {platform}..."},
    "dl_hd":       {"ar": "⬆️ جاري تحميل أعلى جودة HD...", "fr": "⬆️ Téléchargement en HD max...", "en": "⬆️ Fetching max HD quality..."},
    "dl_mp3":      {"ar": "🎵 جاري استخراج الصوت MP3...", "fr": "🎵 Extraction MP3...", "en": "🎵 Extracting MP3 audio..."},
    "caption":     {"ar": "{title}\n\n⬇️ saved by {credit}\n{url}", "fr": "{title}\n\n⬇️ saved by {credit}\n{url}", "en": "{title}\n\n⬇️ saved by {credit}\n{url}"},
    "btn_hd":    {"ar": "⬇️ تحميل HD", "fr": "⬇️ Télécharger HD", "en": "⬇️ Download HD"},
    "btn_mp3":   {"ar": "🎵 تحميل MP3", "fr": "🎵 MP3", "en": "🎵 MP3"},
    "btn_share": {"ar": "📤 مشاركة", "fr": "📤 Partager", "en": "📤 Share"},
    "btn_retry": {"ar": "🔁 إعادة المحاولة", "fr": "🔁 Réessayer", "en": "🔁 Retry"},
    "fail": {
        "ar": "❌ <b>تعذر التحميل.</b>\nالرابط قد يكون خاصاً أو محذوفاً، أو الخوادم مشغولة الآن — أعد المحاولة بعد دقيقة.",
        "fr": "❌ <b>Échec du téléchargement.</b>\nLe lien est peut-être privé/supprimé ou les serveurs sont occupés — réessaie dans une minute.",
        "en": "❌ <b>Download failed.</b>\nThe link may be private/removed or servers are busy — retry in a minute.",
    },
    "rate_limited": {"ar": "🐢 مهلاً! أرسل رابطاً واحداً كل {secs} ثانية.", "fr": "🐢 Doucement! Un lien toutes les {secs}s.", "en": "🐢 Easy! One link every {secs}s."},
    "no_url":      {"ar": "📎 أرسل رابط فيديو صحيحاً (تيك توك، انستغرام، فيسبوك، يوتيوب...)",
                    "fr": "📎 Envoie un lien vidéo valide (TikTok, Instagram, Facebook, YouTube...)",
                    "en": "📎 Send a valid video link (TikTok, Instagram, Facebook, YouTube...)"},
    "unsupported": {"ar": "⚠️ هذه المنصة غير مدعومة حالياً.", "fr": "⚠️ Plateforme non supportée.", "en": "⚠️ Platform not supported yet."},
    "too_big": {
        "ar": "📦 حجم الملف ({size}MB) أكبر من حد تيليجرام ({max}MB).\nحمّله مباشرة من الزر 👇",
        "fr": "📦 Fichier trop lourd ({size}MB > {max}MB).\nTélécharge-le via le bouton 👇",
        "en": "📦 File too big ({size}MB > {max}MB).\nGrab it directly 👇",
    },
    "btn_direct": {"ar": "⬇️ تحميل مباشر", "fr": "⬇️ Lien direct", "en": "⬇️ Direct link"},
    "ad_for_hd": {"ar": "💰 لتحميل <b>HD</b> شاهد إعلان {secs} ثانية 👇", "fr": "💰 Pour HD regarde pub {secs}s 👇", "en": "💰 For HD watch {secs}s ad 👇"},
    "ad_for_mp3": {"ar": "💰 لتحميل <b>MP3</b> شاهد إعلان {secs} ثانية 👇", "fr": "💰 Pour MP3 regarde pub {secs}s 👇", "en": "💰 For MP3 watch {secs}s ad 👇"},
    "job_expired": {"ar": "⏰ انتهت صلاحية الطلب — أرسل الرابط من جديد.", "fr": "⏰ Requête expirée — renvoie le lien.", "en": "⏰ Request expired — send the link again."},
    "busy": {"ar": "⏳ لديك تحميل آخر جارٍ الآن — انتظر حتى ينتهي.", "fr": "⏳ Un téléchargement est déjà en cours.", "en": "⏳ You already have a download in progress."},
    "help": {"ar": "ℹ️ أرسل أي رابط فيديو وسأحمله لك فوراً.\n/start — القائمة الرئيسية",
             "fr": "ℹ️ Envoie un lien vidéo et je le télécharge.\n/start — menu principal",
             "en": "ℹ️ Send any video link and I'll download it.\n/start — main menu"},
    "stats": {
        "ar": "📊 <b>إحصائيات البوت</b>\n\n👥 المستخدمون: <b>{users}</b>\n⬇️ مجموع التحميلات: <b>{downloads}</b>\n🧾 مهام اليوم: <b>{today}</b>",
        "fr": "📊 <b>Stats du bot</b>\n\n👥 Utilisateurs: <b>{users}</b>\n⬇️ Téléchargements: <b>{downloads}</b>\n🧾 Jobs aujourd'hui: <b>{today}</b>",
        "en": "📊 <b>Bot stats</b>\n\n👥 Users: <b>{users}</b>\n⬇️ Total downloads: <b>{downloads}</b>\n🧾 Jobs today: <b>{today}</b>",
    },
    "broadcast_done": {"ar": "📣 تم إرسال الرسالة إلى {ok} مستخدم ❌ فشل: {fail}",
                       "fr": "📣 Message envoyé à {ok} utilisateurs, échecs: {fail}",
                       "en": "📣 Sent to {ok} users, failed: {fail}"},
    "not_admin": {"ar": "⛔ هذا الأمر للمشرف فقط.", "fr": "⛔ Commande réservée à l'admin.", "en": "⛔ Admin only."},
}

def t(lang: str, key: str, **kw) -> str:
    return T[key][lang].format(**kw) if kw else T[key][lang]

def platform_name(platform: str, lang: str) -> str:
    return PLATFORMS.get(platform, {}).get(lang) or PLATFORMS.get(platform, {}).get("ar", platform)

# =============================================================================
#  DATABASE (SQLite — users, jobs, stats)
# =============================================================================

_db_lock = threading.Lock()

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with _db_lock, db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, first_name TEXT, username TEXT,
            lang TEXT, joined_at REAL, downloads INTEGER DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY, user_id INTEGER, url TEXT, platform TEXT,
            title TEXT, created_at REAL, ad_ok INTEGER DEFAULT 0, done INTEGER DEFAULT 0)""")

def upsert_user(u):
    with _db_lock, db() as c:
        c.execute("""INSERT INTO users(user_id, first_name, username, lang, joined_at)
                     VALUES(?,?,?,?,?)
                     ON CONFLICT(user_id) DO UPDATE SET first_name=excluded.first_name,
                     username=excluded.username, lang=excluded.lang""",
                  (u.id, u.first_name or "", u.username or "", u.language_code or "", time.time()))

def bump_downloads(user_id: int):
    with _db_lock, db() as c:
        c.execute("UPDATE users SET downloads = downloads + 1 WHERE user_id=?", (user_id,))

def create_job(user_id: int, url: str, platform: str) -> str:
    jid = uuid.uuid4().hex[:12]
    with _db_lock, db() as c:
        c.execute("INSERT INTO jobs(id,user_id,url,platform,title,created_at) VALUES(?,?,?,?,?,?)",
                  (jid, user_id, url, platform, "", time.time()))
    return jid

def get_job(jid: str):
    with _db_lock, db() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return dict(row) if row else None

def job_update(jid: str, **fields):
    if not fields:
        return
    keys = ",".join(f"{k}=?" for k in fields)
    with _db_lock, db() as c:
        c.execute(f"UPDATE jobs SET {keys} WHERE id=?", (*fields.values(), jid))

def stats_snapshot():
    day_start = time.time() - (time.time() % 86400)
    with _db_lock, db() as c:
        users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        dls = c.execute("SELECT COALESCE(SUM(downloads),0) FROM users").fetchone()[0]
        today = c.execute("SELECT COUNT(*) FROM jobs WHERE created_at>=?", (day_start,)).fetchone()[0]
    return users, dls, today

def all_user_ids():
    with _db_lock, db() as c:
        return [r[0] for r in c.execute("SELECT user_id FROM users").fetchall()]

# =============================================================================
#  PLATFORM DETECTION
# =============================================================================

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
YT_ID_RE = re.compile(r"(?:youtube\.com/(?:watch\?[^#]*v=|shorts/|embed/|v/|live/)|youtu\.be/)([\w-]{11})")

def extract_url(text: str):
    m = URL_RE.search(text or "")
    return m.group(0).rstrip(".,);)]}") if m else None

def detect_platform(url: str):
    u = url.lower()
    if "tiktok.com" in u or "vt.tiktok" in u: return "tiktok"
    if "instagram.com" in u or "instagr.am" in u: return "instagram"
    if "facebook.com" in u or "fb.watch" in u or "fb.com" in u: return "facebook"
    if "youtube.com" in u or "youtu.be" in u or "music.youtube" in u: return "youtube"
    if "twitter.com" in u or "x.com" in u: return "twitter"
    if "pinterest." in u or "pin.it" in u: return "pinterest"
    return None

def youtube_id(url: str):
    m = YT_ID_RE.search(url)
    return m.group(1) if m else None

# =============================================================================
#  DOWNLOAD BACKENDS  (blocking — always called via executor)
# =============================================================================
class DownloadError(Exception):
    pass

class TooBigError(DownloadError):
    def __init__(self, size_mb, direct_url):
        self.size_mb, self.direct_url = size_mb, direct_url
        super().__init__(f"too big: {size_mb}MB")

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=8)

def _abs(host: str, path: str) -> str:
    return ("https://" + host.lstrip("/").rstrip("/") + "/" + path.lstrip("/")) if path.startswith("/") else path

def _as_result(res, title="", thumb=""):
    """res may be (url,), (url,title) or (url,title,thumb)."""
    vals = list(res) + [title, thumb]
    return {"url": vals[0], "title": vals[1] or title, "thumb": vals[2] or thumb}

# ---- TikTok: tikwm -----------------------------------------------------------
def via_tikwm(url: str, audio: bool = False, hd: bool = False):
    title = ""
    for method in ("post", "get"):
        try:
            if method == "post":
                r = requests.post(TIKWM_API, data={"url": url, "hd": 1, "web": 1},
                                  headers=UA, timeout=HTTP_TIMEOUT)
            else:
                r = requests.get(TIKWM_API, params={"url": url, "hd": 1},
                                 headers=UA, timeout=HTTP_TIMEOUT)
            data = r.json()
            if data.get("code") != 0 or not data.get("data"):
                continue
            d = data["data"]
            title = d.get("title", "")
            host = "tikwm.com"
            if audio:
                music = d.get("music")
                if music:
                    return _abs(host, music), title, d.get("cover", "")
            if hd and d.get("hdplay"):
                return _abs(host, d["hdplay"]), title, d.get("cover", "")
            if d.get("play"):
                return _abs(host, d["play"]), title, d.get("cover", "")
    # fallback: photo slideshow -> send cover only is not useful; stop
        except Exception as e:
            log.info("tikwm %s failed: %s", method, e)
    raise DownloadError("tikwm failed")

# ---- Cobalt (new API + legacy api/json for community instances) --------------
def _cobalt_headers():
    h = dict(UA)
    h.update({"Accept": "application/json", "Content-Type": "application/json"})
    if COBALT_API_KEY:
        h["Authorization"] = f"Api-Key {COBALT_API_KEY}"
    return h

def via_cobalt(url: str, audio: bool = False, hd: bool = False):
    quality = "2160" if hd else "1080"
    for inst in COBALT_INSTANCES:
        # dead/parked endpoints (like co.wuk.sh today) get a short timeout so the
        # requested endpoint is still tried first without slowing down downloads
        inst_timeout = 6 if "wuk.sh" in inst else HTTP_TIMEOUT
        # --- legacy dialect: POST {instance}/api/json  (app v1.9 / co.wuk.sh style)
        try:
            body = {"url": url, "vQuality": "max" if hd else "1080",
                    "isAudioOnly": audio, "aFormat": "mp3", "filenamePattern": "basic"}
            r = requests.post(inst + "/api/json", json=body, headers=_cobalt_headers(), timeout=inst_timeout)
            j = r.json()
            if j.get("status") in ("stream", "redirect", "success", "rate-limit") and j.get("url"):
                return j["url"], "", ""
            if j.get("picker"):
                for item in j["picker"]:
                    if item.get("type") == "video" and item.get("url"):
                        return item["url"], "", ""
        except Exception as e:
            log.info("cobalt legacy %s failed: %s", inst, e)
        # --- current cobalt API: POST {instance}/
        try:
            body = {"url": url,
                    "downloadMode": "audio" if audio else "auto",
                    "audioFormat": "mp3", "audioBitrate": "128",
                    "videoQuality": quality, "filenameStyle": "basic"}
            r = requests.post(inst + "/", json=body, headers=_cobalt_headers(), timeout=inst_timeout)
            j = r.json()
            st = j.get("status")
            if st in ("tunnel", "redirect", "stream", "success") and j.get("url"):
                return j["url"], "", ""
            if st == "picker":
                for item in j.get("picker", []):
                    if item.get("type") == "video" and item.get("url"):
                        return item["url"], "", ""
                if j.get("audio"):
                    return j["audio"], "", ""
        except Exception as e:
            log.info("cobalt new api %s failed: %s", inst, e)
    raise DownloadError("all cobalt instances failed")

# ---- YouTube via Piped --------------------------------------------------------
def via_piped(video_id: str, audio: bool = False):
    for inst in PIPED_INSTANCES:
        try:
            r = requests.get(f"{inst}/streams/{video_id}", headers=UA, timeout=HTTP_TIMEOUT)
            j = r.json()
            title, thumb = j.get("title", ""), j.get("thumbnailUrl", "")
            if audio:
                streams = j.get("audioStreams") or []
                if streams:
                    best = max(streams, key=lambda s: s.get("bitrate", 0))
                    return best["url"], title, thumb
                continue
            streams = j.get("videoStreams") or []
            progressive = [s for s in streams if not s.get("videoOnly") and s.get("url")]
            if not progressive:
                continue
            def q(s):
                m = re.search(r"(\d+)", s.get("quality") or "0")
                return int(m.group(1)) if m else 0
            capped = [s for s in progressive if q(s) <= 1080]
            best = max(capped or progressive, key=q)
            return best["url"], title, thumb
        except Exception as e:
            log.info("piped %s failed: %s", inst, e)
    raise DownloadError("piped failed")

# ---- yt-dlp fallback (only if installed on the host) --------------------------
def via_ytdlp(url: str, audio: bool = False):
    if not (USE_YTDLP_FALLBACK and shutil.which("yt-dlp")):
        raise DownloadError("yt-dlp not available")
    workdir = tempfile.mkdtemp(prefix="ezdl_")
    out = os.path.join(workdir, "media.%(ext)s")
    cmd = ["yt-dlp", "--no-playlist", "--no-warnings", "-o", out]
    if audio:
        cmd += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
    else:
        cmd += ["-f", "b[filesize<49M]/b", "--max-filesize", "49M"]
    cmd.append(url)
    try:
        subprocess.run(cmd, capture_output=True, timeout=600, check=True)
    except Exception as e:
        shutil.rmtree(workdir, ignore_errors=True)
        raise DownloadError(f"yt-dlp failed: {e}")
    files = glob.glob(os.path.join(workdir, "media.*"))
    if not files:
        shutil.rmtree(workdir, ignore_errors=True)
        raise DownloadError("yt-dlp produced no file")
    return files[0], workdir  # local file path — caller uploads & cleans up

# ---- Resolver -----------------------------------------------------------------
def resolve_media(url: str, platform: str, mode: str = "video"):
    """Return dict(kind='url'|'file', url/path, title, thumb, cleanup)."""
    audio = mode == "audio"
    hd = mode == "hd"

    if platform == "tiktok":
        v, ttl, th = via_tikwm(url, audio=audio, hd=hd)
        return {"kind": "url", "url": v, "title": ttl, "thumb": th}

    if platform == "youtube":
        vid = youtube_id(url)
        if vid:
            try:
                v, ttl, th = via_piped(vid, audio=audio)
                return {"kind": "url", "url": v, "title": ttl, "thumb": th}
            except DownloadError:
                pass
        try:
            v, _, _ = via_cobalt(url, audio=audio, hd=hd)
            return {"kind": "url", "url": v, "title": "", "thumb": ""}
        except DownloadError:
            pass
    else:  # instagram / facebook / twitter / pinterest
        try:
            v, _, _ = via_cobalt(url, audio=audio, hd=hd)
            return {"kind": "url", "url": v, "title": "", "thumb": ""}
        except DownloadError:
            pass

    path, workdir = via_ytdlp(url, audio=audio)
    return {"kind": "file", "path": path, "title": "", "thumb": "", "cleanup": workdir}

# ---- Helpers: sizes & file download -------------------------------------------
def remote_size_mb(url: str):
    try:
        r = requests.head(url, headers=UA, timeout=15, allow_redirects=True)
        n = int(r.headers.get("Content-Length", "0"))
        return n / 1e6 if n else None
    except Exception:
        return None

def download_file(url: str, suffix: str, max_mb: int) -> str:
    size = remote_size_mb(url)
    if size and size > max_mb:
        raise TooBigError(round(size), url)
    path = tempfile.mktemp(prefix="ezup_", suffix=suffix)
    with requests.get(url, headers=UA, timeout=300, stream=True) as r:
        r.raise_for_status()
        total = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                total += len(chunk)
                if total > max_mb * 1e6:
                    f.close()
                    os.unlink(path)
                    raise TooBigError(round(total / 1e6), url)
                f.write(chunk)
    return path

# =============================================================================
#  GATES — monetization (ad + force-subscribe), rate limit
# =============================================================================
_user_locks: dict = {}
_user_last: dict = {}
_dl_sem = asyncio.Semaphore(4)

def lock_for(uid: int) -> asyncio.Lock:
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]

async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    if not ENABLE_FORCE_SUB:
        return True
    try:
        m = await context.bot.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        return m.status in ("member", "administrator", "creator", "owner")
    except TelegramError as e:
        log.warning("get_chat_member failed (bot must be admin in %s): %s", FORCE_SUB_CHANNEL, e)
        return False

def ad_gate_keyboard(lang: str, jid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_watch_ad"), url=AD_LINK)],
        [InlineKeyboardButton(t(lang, "btn_confirm"), callback_data=f"go:{jid}")],
    ])

def join_keyboard(lang: str, jid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_join"), url=CHANNEL_LINK)],
        [InlineKeyboardButton(t(lang, "btn_joined"), callback_data=f"go:{jid}")],
    ])

def result_keyboard(lang: str, jid: str, original_url: str) -> InlineKeyboardMarkup:
    # === FIXED: HD and MP3 now require watching ad again (no free bypass) ===
    share = f"https://t.me/share/url?url={original_url}"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬇️ HD - بالإعلان 💰", callback_data=f"askhd:{jid}"),
            InlineKeyboardButton("🎵 MP3 - بالإعلان 💰", callback_data=f"askmp3:{jid}")
        ],
        [InlineKeyboardButton(t(lang, "btn_share"), url=share)],
    ])

def ad_gate_for_hd_keyboard(lang: str, jid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_watch_ad"), url=AD_LINK)],
        [InlineKeyboardButton("✅ HD - بعد الإعلان", callback_data=f"gohd:{jid}")],
    ])

def ad_gate_for_mp3_keyboard(lang: str, jid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_watch_ad"), url=AD_LINK)],
        [InlineKeyboardButton("✅ MP3 - بعد الإعلان", callback_data=f"gomp3:{jid}")],
    ])

# =============================================================================
#  HANDLERS
# =============================================================================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user)
    lang = lang_of(update)
    kb = [[InlineKeyboardButton(t(lang, "btn_how"), callback_data="how")],
          [InlineKeyboardButton(t(lang, "btn_channel"), url=CHANNEL_LINK)]]
    await update.message.reply_text(
        t(lang, "welcome", name=BOT_NAME),
        parse_mode=constants.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb),
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(t(lang_of(update), "help"))

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text(t(lang_of(update), "not_admin"))
    users, dls, today = stats_snapshot()
    await update.message.reply_text(
        t(lang_of(update), "stats", users=users, downloads=dls, today=today),
        parse_mode=constants.ParseMode.HTML)

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return await update.message.reply_text(t(lang_of(update), "not_admin"))
    msg = update.message.reply_to_message
    if not msg and not context.args:
        return await update.message.reply_text("Usage: reply to a message with /broadcast  (or /broadcast text)")
    ok = fail = 0
    for uid in all_user_ids():
        try:
            if msg:
                await msg.copy(uid)
            else:
                await context.bot.send_message(uid, " ".join(context.args))
            ok += 1
        except TelegramError:
            fail += 1
        await asyncio.sleep(0.05)  # stay under rate limits
    await update.message.reply_text(t(lang_of(update), "broadcast_done", ok=ok, fail=fail))

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upsert_user(update.effective_user)
    lang = lang_of(update)
    uid = update.effective_user.id
    text = update.message.text or ""

    url = extract_url(text)
    if not url:
        return await update.message.reply_text(t(lang, "no_url"))

    platform = detect_platform(url)
    if not platform:
        return await update.message.reply_text(t(lang, "unsupported"))

    # rate limit
    now = time.time()
    if now - _user_last.get(uid, 0) < RATE_LIMIT_SECONDS:
        return await update.message.reply_text(t(lang, "rate_limited", secs=RATE_LIMIT_SECONDS))
    _user_last[uid] = now

    jid = create_job(uid, url, platform)
    pname = platform_name(platform, lang)

    # ---- MONETIZATION GATES ---------------------------------------------------
    if ENABLE_FORCE_SUB and not await is_subscribed(context, uid):
        return await update.message.reply_text(
            t(lang, "join_prompt"), reply_markup=join_keyboard(lang, jid))

    if ENABLE_AD_STEP:
        txt = t(lang, "detected", platform=pname) + t(lang, "ad_prompt", secs=AD_WAIT_SECONDS)
        return await update.message.reply_text(
            txt, parse_mode=constants.ParseMode.HTML,
            reply_markup=ad_gate_keyboard(lang, jid))

    # monetization disabled -> download immediately
    await process_download(update, context, jid, mode="video", lang=lang, status_msg=None)

# ---- callback dispatcher -------------------------------------------------------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    lang = lang_of(update)
    data = q.data or ""

    if data == "how":
        await q.answer()
        return await q.message.reply_text(t(lang, "how"), parse_mode=constants.ParseMode.HTML)

    if ":" in data:
        mode_key, jid = data.split(":", 1)
        job = get_job(jid)
        if not job:
            return await q.answer(t(lang, "job_expired"), show_alert=True)

        if mode_key == "go":
            await gate_and_download(update, context, job, lang)

        elif mode_key == "askhd":
            # User wants HD -> reset timer and show ad gate for HD
            job_update(jid, created_at=time.time(), ad_ok=0)
            await q.answer()
            try:
                await q.edit_message_text(t(lang, "ad_for_hd", secs=AD_WAIT_SECONDS), parse_mode=constants.ParseMode.HTML, reply_markup=ad_gate_for_hd_keyboard(lang, jid))
            except TelegramError:
                await q.message.reply_text(t(lang, "ad_for_hd", secs=AD_WAIT_SECONDS), parse_mode=constants.ParseMode.HTML, reply_markup=ad_gate_for_hd_keyboard(lang, jid))

        elif mode_key == "askmp3":
            job_update(jid, created_at=time.time(), ad_ok=0)
            await q.answer()
            try:
                await q.edit_message_text(t(lang, "ad_for_mp3", secs=AD_WAIT_SECONDS), parse_mode=constants.ParseMode.HTML, reply_markup=ad_gate_for_mp3_keyboard(lang, jid))
            except TelegramError:
                await q.message.reply_text(t(lang, "ad_for_mp3", secs=AD_WAIT_SECONDS), parse_mode=constants.ParseMode.HTML, reply_markup=ad_gate_for_mp3_keyboard(lang, jid))

        elif mode_key == "gohd":
            if ENABLE_AD_STEP:
                elapsed = time.time() - job["created_at"]
                if elapsed < AD_WAIT_SECONDS:
                    left = max(1, round(AD_WAIT_SECONDS - elapsed))
                    return await q.answer(t(lang, "ad_wait", secs=left), show_alert=True)
            if not await is_subscribed(context, update.effective_user.id):
                return await q.answer(t(lang, "not_joined"), show_alert=True)
            job_update(jid, ad_ok=1)
            await q.answer()
            await process_download(update, context, jid, mode="hd", lang=lang, status_msg=None)

        elif mode_key == "gomp3":
            if ENABLE_AD_STEP:
                elapsed = time.time() - job["created_at"]
                if elapsed < AD_WAIT_SECONDS:
                    left = max(1, round(AD_WAIT_SECONDS - elapsed))
                    return await q.answer(t(lang, "ad_wait", secs=left), show_alert=True)
            if not await is_subscribed(context, update.effective_user.id):
                return await q.answer(t(lang, "not_joined"), show_alert=True)
            job_update(jid, ad_ok=1)
            await q.answer()
            await process_download(update, context, jid, mode="audio", lang=lang, status_msg=None)

        # Old cached buttons -> force ad gate again (no free bypass)
        elif mode_key == "hd":
            job_update(jid, created_at=time.time(), ad_ok=0)
            await q.answer()
            try:
                await q.edit_message_text(t(lang, "ad_for_hd", secs=AD_WAIT_SECONDS), parse_mode=constants.ParseMode.HTML, reply_markup=ad_gate_for_hd_keyboard(lang, jid))
            except TelegramError:
                pass
        elif mode_key == "mp3":
            job_update(jid, created_at=time.time(), ad_ok=0)
            await q.answer()
            try:
                await q.edit_message_text(t(lang, "ad_for_mp3", secs=AD_WAIT_SECONDS), parse_mode=constants.ParseMode.HTML, reply_markup=ad_gate_for_mp3_keyboard(lang, jid))
            except TelegramError:
                pass


async def gate_and_download(update: Update, context: ContextTypes.DEFAULT_TYPE, job: dict, lang: str):
    q = update.callback_query
    uid = update.effective_user.id
    jid = job["id"]

    # 1) force-subscribe recheck
    if not await is_subscribed(context, uid):
        await q.answer(t(lang, "not_joined"), show_alert=True)
        try:
            await q.edit_message_text(t(lang, "join_prompt"), reply_markup=join_keyboard(lang, jid))
        except TelegramError:
            pass
        return

    # 2) ad timer check (shrinkme/monetag have no API callback ->
    #    enforce the wait time; user opens ad via the URL button)
    if ENABLE_AD_STEP and not job.get("ad_ok"):
        elapsed = time.time() - job["created_at"]
        if elapsed < AD_WAIT_SECONDS:
            left = max(1, round(AD_WAIT_SECONDS - elapsed))
            return await q.answer(t(lang, "ad_wait", secs=left), show_alert=True)
        job_update(jid, ad_ok=1)

    await q.answer()
    try:
        await q.edit_message_text(t(lang, "downloading", platform=platform_name(job["platform"], lang)))
    except TelegramError:
        pass
    await process_download(update, context, jid, mode="video", lang=lang, status_msg=q.message)

# ---- the actual download + send pipeline ----------------------------------------
async def process_download(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           jid: str, mode: str, lang: str, status_msg):
    job = get_job(jid)
    if not job:
        return
    chat_id = update.effective_chat.id
    uid = update.effective_user.id
    url, platform = job["url"], job["platform"]
    pname = platform_name(platform, lang)

    lock = lock_for(uid)
    if lock.locked():
        if status_msg is None:
            await context.bot.send_message(chat_id, t(lang, "busy"))
        return

    async with lock:
        # status message
        if status_msg is None:
            key = {"video": "downloading", "hd": "dl_hd", "audio": "dl_mp3"}[mode]
            status_msg = await context.bot.send_message(
                chat_id, t(lang, key, platform=pname) if key == "downloading" else t(lang, key))

        try:
            async with _dl_sem:
                res = await asyncio.get_running_loop().run_in_executor(
                    _executor, resolve_media, url, platform, mode)
            audio = mode == "audio"
            cleanup_dir = None

            # ---- get a file to upload --------------------------------------
            if res["kind"] == "file":                      # yt-dlp produced a file
                path, cleanup_dir = res["path"], res.get("cleanup")
                size_mb = os.path.getsize(path) / 1e6
                if size_mb > MAX_UPLOAD_MB:
                    raise TooBigError(round(size_mb), None)
                sent = await _send_local(context.bot, chat_id, path, audio, res, job, lang)
            else:
                direct = res["url"]
                size_mb = remote_size_mb(direct)
                if size_mb and size_mb > (MAX_UPLOAD_MB if LOCAL_API_URL else MAX_URL_MB):
                    # too big to send-by-URL -> download & upload ourselves
                    if size_mb > (2048 if LOCAL_API_URL else MAX_UPLOAD_MB):
                        raise TooBigError(round(size_mb), direct)
                    suffix = ".mp3" if audio else ".mp4"
                    path = await asyncio.get_running_loop().run_in_executor(
                        _executor, download_file, direct, suffix, 2048 if LOCAL_API_URL else MAX_UPLOAD_MB)
                    cleanup_dir = os.path.dirname(path)
                    sent = await _send_local(context.bot, chat_id, path, audio, res, job, lang)
                else:
                    # fast path: Telegram fetches the URL itself
                    try:
                        sent = await _send_remote(context.bot, chat_id, direct, audio, res, job, lang)
                    except TelegramError as e:
                        log.info("send-by-url failed (%s) -> re-uploading", e)
                        suffix = ".mp3" if audio else ".mp4"
                        path = await asyncio.get_running_loop().run_in_executor(
                            _executor, download_file, direct, suffix, MAX_UPLOAD_MB)
                        cleanup_dir = os.path.dirname(path)
                        sent = await _send_local(context.bot, chat_id, path, audio, res, job, lang)

            if cleanup_dir:
                shutil.rmtree(cleanup_dir, ignore_errors=True)
            elif res["kind"] == "file" and res.get("cleanup"):
                shutil.rmtree(res["cleanup"], ignore_errors=True)

            job_update(jid, done=1, title=res.get("title") or "")
            bump_downloads(uid)
            try:
                await status_msg.delete()
            except TelegramError:
                pass

        except TooBigError as e:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "btn_direct"), url=e.direct_url)]]) \
                if e.direct_url else None
            await status_msg.edit_text(
                t(lang, "too_big", size=e.size_mb, max=MAX_UPLOAD_MB),
                reply_markup=kb)
        except Exception as e:
            log.exception("download error for %s", url)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(t(lang, "btn_retry"), callback_data=f"go:{jid}")]])
            try:
                await status_msg.edit_text(t(lang, "fail"), parse_mode=constants.ParseMode.HTML, reply_markup=kb)
            except TelegramError:
                await context.bot.send_message(chat_id, t(lang, "fail"),
                                               parse_mode=constants.ParseMode.HTML, reply_markup=kb)

async def _caption(res, job, lang):
    title = (res.get("title") or "").strip() or platform_name(job["platform"], lang)
    cap = t(lang, "caption", title=title, credit=CAPTION_CREDIT, url=job["url"])
    return html.escape(cap)[:1020]

async def _send_remote(bot, chat_id, direct, audio, res, job, lang):
    kb = result_keyboard(lang, job["id"], job["url"])
    cap = await _caption(res, job, lang)
    common = dict(chat_id=chat_id, reply_markup=kb,
                  caption=cap, parse_mode=constants.ParseMode.HTML,
                  read_timeout=120, write_timeout=120, connect_timeout=60)
    if audio:
        return await bot.send_audio(audio=direct, title=(res.get("title") or "audio")[:200], **common)
    return await bot.send_video(video=direct, supports_streaming=True, **common)

async def _send_local(bot, chat_id, path, audio, res, job, lang):
    kb = result_keyboard(lang, job["id"], job["url"])
    cap = await _caption(res, job, lang)
    common = dict(chat_id=chat_id, reply_markup=kb, caption=cap,
                  parse_mode=constants.ParseMode.HTML,
                  read_timeout=300, write_timeout=300, connect_timeout=60)
    with open(path, "rb") as fh:
        if audio:
            return await bot.send_audio(audio=fh, title=(res.get("title") or "audio")[:200], **common)
        return await bot.send_video(video=fh, supports_streaming=True, **common)

# ---- global error handler -------------------------------------------------------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("handler error: %s", context.error)

# =============================================================================
#  HEALTH SERVER (keeps free hosts like Render/Replit happy in polling mode)
# =============================================================================
def start_health_server():
    try:
        from flask import Flask
    except ImportError:
        log.warning("flask not installed — health server disabled")
        return
    app = Flask("ezayani-health")

    @app.route("/")
    def home():
        u, d, td = stats_snapshot()
        return f"✅ {BOT_NAME} is running — users:{u} downloads:{d} today:{td}"

    app.run(host="0.0.0.0", port=PORT, threaded=True)

# =============================================================================
#  APP SETUP
# =============================================================================
def build_app() -> Application:
    builder = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(60).read_timeout(60).write_timeout(60).pool_timeout(60)
    )
    if LOCAL_API_URL:
        builder.base_url(f"{LOCAL_API_URL}/bot").base_file_url(f"{LOCAL_API_URL}/file/bot")
    app = builder.build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(on_error)
    return app

def main():
    if BOT_TOKEN == "YOUR_TOKEN_FROM_BOTFATHER":
        raise SystemExit("❌ Set your token first: env BOT_TOKEN=... or edit BOT_TOKEN in bot.py  (get one from @BotFather)")
    init_db()
    app = build_app()

    if WEBHOOK_URL:
        log.info("Starting in WEBHOOK mode on port %s", PORT)  # e.g. Render web service
        app.run_webhook(listen="0.0.0.0", port=PORT,
                        url_path=BOT_TOKEN, webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
                        drop_pending_updates=True)
    else:
        if os.getenv("PORT"):  # Render/Replit free tier expects an open port
            threading.Thread(target=start_health_server, daemon=True).start()
            log.info("Health server on :%s", PORT)
        log.info("Starting in POLLING mode")
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
