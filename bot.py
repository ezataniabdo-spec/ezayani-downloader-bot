#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# EZAYANI Downloader - ULTIMATE FIX v4
# - Instagram fixed via multiple backends
# - Ad is MANDATORY and cannot be bypassed
# - HD/MP3 also require ad if not unlocked

import asyncio, glob, html, logging, os, re, shutil, sqlite3, tempfile, threading, time, uuid, json
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, constants
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "@EzayaniDownloadBot")
BOT_NAME = os.getenv("BOT_NAME", "EZAYANI Downloader")
CAPTION_CREDIT = os.getenv("CAPTION_CREDIT", "@download_it_bot")
AD_LINK = os.getenv("AD_LINK", "https://shrinkme.io/YOUR_LINK")
ENABLE_AD_STEP = True  # ALWAYS ON NOW
AD_WAIT_SECONDS = int(os.getenv("AD_WAIT_SECONDS", "10"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "49"))
DB_PATH = os.getenv("DB_PATH", "ezayani_bot.db")
TIKWM_API = "https://tikwm.com/api/"
COBALT_INSTANCES = ["https://co.wuk.sh","https://co.otomir23.me","https://downloadapi.stuff.solutions","https://cobalt-api.kwiatekmiki.com","https://capi.oak.li","https://cobalt-backend.canine.tools"]
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8080"))

try:
    import yt_dlp
    HAS_YTDLP=True
except:
    HAS_YTDLP=False
    yt_dlp=None

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger("ezayani")

# --- DB ---
def init_db():
    conn=sqlite3.connect(DB_PATH); c=conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, unlocked_until INTEGER)")
    c.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, user_id INTEGER, url TEXT, platform TEXT, created TEXT)")
    conn.commit(); conn.close()

def is_unlocked(uid):
    conn=sqlite3.connect(DB_PATH); c=conn.cursor()
    c.execute("SELECT unlocked_until FROM users WHERE id=?",(uid,))
    r=c.fetchone(); conn.close()
    if not r: return False
    return r[0] > int(time.time())

def set_unlocked(uid, seconds=86400):
    conn=sqlite3.connect(DB_PATH); c=conn.cursor()
    until=int(time.time())+seconds
    c.execute("INSERT OR REPLACE INTO users(id, unlocked_until) VALUES(?,?)",(uid,until))
    conn.commit(); conn.close()

def job_create(uid, url, plat):
    jid=uuid.uuid4().hex[:12]
    conn=sqlite3.connect(DB_PATH); c=conn.cursor()
    c.execute("INSERT INTO jobs(id,user_id,url,platform,created) VALUES(?,?,?, ?,?)",(jid,uid,url,plat,time.strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit(); conn.close()
    return jid

def job_get(jid):
    conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row; c=conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id=?",(jid,)); r=c.fetchone(); conn.close()
    return dict(r) if r else None

# --- lang ---
def t(lang,k,**kw):
    ar={"start":"👋 أهلا! أرسل رابط من تيكتوك، انستا، يوتيوب...","detect":"🔍 اكتشفت: {plat}\n⏳ الرابط مقفل - شاهد الإعلان إجباري","ad_btn":"▶️ شاهد الإعلان ({sec} ثانية) 💰","ad_wait":"⏳ يجب أن تشاهد الإعلان {sec} ثواني كاملة!","ad_confirm":"✅ شاهدت الإعلان - افتح التحميل","downloading":"⏳ جاري التحميل...","fail":"❌ فشل التحميل، جرب رابط آخر أو انتظر قليلا","btn_hd":"⬇️ تحميل HD","btn_mp3":"🎵 تحميل MP3","btn_share":"📤 Share","caption":"{title}\n\n⬇️ saved by {credit}\n{url}","locked":"🔒 يجب مشاهدة الإعلان أولا! اضغط ▶️ شاهد الإعلان"}
    return ar.get(k,k).format(**kw)

def detect_platform(url):
    u=url.lower()
    if "tiktok" in u: return "tiktok"
    if "instagram" in u or "instagr.am" in u: return "instagram"
    if "facebook" in u or "fb.watch" in u: return "facebook"
    if "youtube" in u or "youtu.be" in u: return "youtube"
    return "other"

# --- DOWNLOAD BACKENDS ---
def ytdlp_instagram(url, audio=False):
    """Try yt-dlp with multiple strategies for Instagram"""
    if not HAS_YTDLP: return None
    for attempt in range(3):
        tmp=tempfile.mkdtemp(prefix="ig_")
        try:
            # Strategy 1: best
            # Strategy 2: mobile user agent
            # Strategy 3: with instagram api v2
            fmt="bestaudio/best" if audio else "bestvideo+bestaudio/best"
            opts={
                "outtmpl": os.path.join(tmp, "%(title)s.%(ext)s"),
                "format": fmt,
                "merge_output_format": "mp4" if not audio else "m4a",
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "nocheckcertificate": True,
                "http_headers": {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"},
            }
            if attempt==1:
                opts["extractor_args"] = {"instagram": {"api_version": ["2"]}}
            if attempt==2:
                opts["extractor_args"] = {"instagram": {"api_version": ["1"]}}
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info=ydl.extract_info(url, download=True)
                files=glob.glob(os.path.join(tmp, "*"))
                # filter only video/audio, not jpg
                video_files=[f for f in files if not f.lower().endswith(('.jpg','.jpeg','.png','.webp'))]
                if not video_files:
                    # if only image, try next attempt
                    shutil.rmtree(tmp, ignore_errors=True)
                    continue
                fp=max(video_files, key=os.path.getsize)
                # check size > 100KB
                if os.path.getsize(fp) < 100*1024:
                    shutil.rmtree(tmp, ignore_errors=True)
                    continue
                return {"kind":"file","path":fp,"cleanup":tmp,"title":info.get("title","Instagram Reels"),"direct":None}
        except Exception as e:
            log.info("ytdlp ig attempt %s fail %s", attempt, e)
            shutil.rmtree(tmp, ignore_errors=True)
            continue
    return None

def cobalt_try(url, audio=False):
    payload={"url":url}
    if audio: payload["isAudioOnly"]=True
    for inst in COBALT_INSTANCES:
        try:
            api=inst.rstrip("/")+"/api/json"
            r=requests.post(api, json=payload, headers={"Accept":"application/json","Content-Type":"application/json","User-Agent":"Mozilla/5.0"}, timeout=12)
            if r.status_code!=200: continue
            j=r.json()
            if j.get("status") in ("redirect","tunnel","stream","picker") and j.get("url"):
                # avoid returning image
                if j.get("url","").lower().endswith(('.jpg','.jpeg','.png','.webp')):
                    continue
                return {"kind":"url","direct":j["url"],"title":j.get("filename") or ""}
        except: continue
    return None

def tikwm_try(url):
    try:
        r=requests.post(TIKWM_API, json={"url":url}, timeout=12)
        j=r.json()
        if j.get("code")==0 and j.get("data"):
            d=j["data"]
            play=d.get("play") or d.get("hdplay")
            if play: return {"kind":"url","direct":play,"title":d.get("title","")}
    except: pass
    return None

def ddinstagram_try(url):
    """Use ddinstagram as fallback - converts instagram.com to ddinstagram.com"""
    try:
        # Convert https://www.instagram.com/reel/XXX/ to https://www.ddinstagram.com/reel/XXX/
        dd_url=url.replace("www.instagram.com","www.ddinstagram.com").replace("instagram.com","ddinstagram.com")
        # ddinstagram returns direct video page, we can try to extract
        # Simple: request dd page and find video URL
        r=requests.get(dd_url, headers={"User-Agent":"Mozilla/5.0"}, timeout=12)
        if r.status_code==200:
            # find mp4 url
            m=re.search(r'"video_url":"([^"]+\.mp4[^"]*)"', r.text)
            if not m:
                m=re.search(r'(https://[^"]+\.mp4[^"]*)', r.text)
            if m:
                video_url=m.group(1).replace("\\u0026","&").replace("\u0026","&").replace("\/","/")
                return {"kind":"url","direct":video_url,"title":"Instagram Reels"}
    except Exception as e:
        log.info("ddinstagram fail %s", e)
    return None

def resolve_url(url, audio=False):
    plat=detect_platform(url)
    # TikTok first via TikWM
    if plat=="tiktok":
        rr=tikwm_try(url)
        if rr: return rr
    # Instagram: try multiple
    if plat=="instagram":
        # 1. ddinstagram (fast and reliable)
        rr=ddinstagram_try(url)
        if rr: return rr
        # 2. yt-dlp
        rr=ytdlp_instagram(url, audio=audio)
        if rr: return rr
        # 3. cobalt
        rr=cobalt_try(url, audio=audio)
        if rr: return rr
        # 4. final yt-dlp generic
        if HAS_YTDLP:
            tmp=tempfile.mkdtemp()
            try:
                opts={"outtmpl": os.path.join(tmp, "%(title)s.%(ext)s"), "format":"best", "quiet":True, "noplaylist":True}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info=ydl.extract_info(url, download=True)
                    files=[f for f in glob.glob(os.path.join(tmp,"*")) if not f.endswith(('.jpg','.png','.webp'))]
                    if files:
                        fp=max(files, key=os.path.getsize)
                        if os.path.getsize(fp)>100*1024:
                            return {"kind":"file","path":fp,"cleanup":tmp,"title":info.get("title","")}
            except: pass
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        # Other platforms: cobalt then yt-dlp
        rr=cobalt_try(url, audio=audio)
        if rr: return rr
        if HAS_YTDLP:
            tmp=tempfile.mkdtemp()
            try:
                fmt="bestaudio/best" if audio else "best"
                opts={"outtmpl": os.path.join(tmp, "%(title)s.%(ext)s"), "format":fmt, "merge_output_format":"mp4", "quiet":True, "noplaylist":True}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info=ydl.extract_info(url, download=True)
                    files=glob.glob(os.path.join(tmp,"*"))
                    if files:
                        fp=max(files, key=os.path.getsize)
                        return {"kind":"file","path":fp,"cleanup":tmp,"title":info.get("title",""),"direct":None}
            except: pass
            shutil.rmtree(tmp, ignore_errors=True)
    
    raise Exception("all failed")

def download_file(direct, max_mb=49):
    tmp=tempfile.mkdtemp()
    path=os.path.join(tmp,"file.mp4")
    with requests.get(direct, stream=True, timeout=60, headers={"User-Agent":"Mozilla/5.0 (iPhone)"}) as r:
        r.raise_for_status()
        with open(path,"wb") as f:
            for chunk in r.iter_content(8192):
                if chunk: f.write(chunk)
    if os.path.getsize(path) < 50*1024:
        raise Exception("file too small - probably blocked")
    return path, tmp

def result_keyboard(lang, jid, url):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang,"btn_hd"), callback_data=f"hd:{jid}"),
         InlineKeyboardButton(t(lang,"btn_mp3"), callback_data=f"mp3:{jid}")],
        [InlineKeyboardButton(t(lang,"btn_share"), switch_inline_query=url)],
    ])

def ad_keyboard(lang, jid, sec=10):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang,"ad_btn", sec=sec), url=AD_LINK)],
        [InlineKeyboardButton(t(lang,"ad_confirm"), callback_data=f"confirm:{jid}")],
    ])

# track when ad button was shown
ad_shown={}

async def cmd_start(update, context):
    await update.message.reply_text(t("ar","start"))

async def handle_link(update, context):
    lang="ar"
    uid=update.effective_user.id
    url=(update.message.text or "").strip()
    if not url.startswith("http"): 
        await update.message.reply_text(t(lang,"start")); return
    plat=detect_platform(url)
    jid=job_create(uid, url, plat)
    # ALWAYS show ad first
    kb=ad_keyboard(lang, jid, AD_WAIT_SECONDS)
    ad_shown[jid]=int(time.time())
    await update.message.reply_text(t(lang,"detect", plat=plat.upper()), reply_markup=kb)

async def on_callback(update, context):
    query=update.callback_query
    await query.answer()
    data=query.data or ""
    lang="ar"
    uid=update.effective_user.id
    
    if data.startswith("confirm:"):
        jid=data.split(":",1)[1]
        # CHECK 10 seconds passed
        shown=ad_shown.get(jid,0)
        elapsed=int(time.time())-shown
        if elapsed < AD_WAIT_SECONDS:
            remain=AD_WAIT_SECONDS-elapsed
            await query.answer(t(lang,"ad_wait", sec=remain), show_alert=True)
            return
        # Unlock user for 24h
        set_unlocked(uid, 86400)
        job=job_get(jid)
        if not job: return
        await query.edit_message_text(t(lang,"downloading"))
        await process_download(query.message, context, jid, job["url"], lang, audio=False, uid=uid)
    
    elif data.startswith("hd:") or data.startswith("mp3:"):
        # CHECK if user unlocked
        if not is_unlocked(uid):
            jid=data.split(":",1)[1]
            kb=ad_keyboard(lang, jid, AD_WAIT_SECONDS)
            ad_shown[jid]=int(time.time())
            await context.bot.send_message(chat_id=query.message.chat_id, text=t(lang,"locked"), reply_markup=kb)
            return
        jid=data.split(":",1)[1]
        job=job_get(jid)
        if not job: return
        audio=data.startswith("mp3:")
        await process_download(None, context, jid, job["url"], lang, audio=audio, uid=uid, chat_id=query.message.chat_id)

    elif data.startswith("go:"):
        jid=data.split(":",1)[1]
        if not is_unlocked(uid):
            kb=ad_keyboard(lang, jid, AD_WAIT_SECONDS)
            ad_shown[jid]=int(time.time())
            await context.bot.send_message(chat_id=query.message.chat_id, text=t(lang,"locked"), reply_markup=kb)
            return
        job=job_get(jid)
        if not job: return
        await process_download(None, context, jid, job["url"], lang, audio=False, uid=uid, chat_id=query.message.chat_id)

async def process_download(status_msg, context, jid, url, lang, audio=False, uid=None, chat_id=None):
    try:
        res=resolve_url(url, audio=audio)
        bot=context.bot
        cid=chat_id or (status_msg.chat_id if status_msg else None)
        if not cid: return
        
        cap=t(lang,"caption", title=res.get("title","")[:200], credit="@download_it_bot", url=url)
        kb=result_keyboard(lang, jid, url)
        
        if res["kind"]=="file":
            path=res["path"]; cleanup=res["cleanup"]
            with open(path,"rb") as fh:
                if audio:
                    await bot.send_audio(chat_id=cid, audio=fh, title=res.get("title","audio")[:200], caption=cap, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
                else:
                    await bot.send_video(chat_id=cid, video=fh, supports_streaming=True, caption=cap, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
            shutil.rmtree(cleanup, ignore_errors=True)
        else:
            direct=res["direct"]
            try:
                if audio:
                    await bot.send_audio(chat_id=cid, audio=direct, title=res.get("title","audio")[:200], caption=cap, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
                else:
                    await bot.send_video(chat_id=cid, video=direct, supports_streaming=True, caption=cap, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
            except TelegramError:
                path, tmp=download_file(direct)
                with open(path,"rb") as fh:
                    if audio:
                        await bot.send_audio(chat_id=cid, audio=fh, title=res.get("title","audio")[:200], caption=cap, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
                    else:
                        await bot.send_video(chat_id=cid, video=fh, supports_streaming=True, caption=cap, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
                shutil.rmtree(tmp, ignore_errors=True)
        
        if status_msg:
            try: await status_msg.delete()
            except: pass
    except Exception as e:
        log.exception("download error %s", url)
        try:
            cid=chat_id or (status_msg.chat_id if status_msg else None)
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 حاول مرة أخرى", callback_data=f"go:{jid}")]])
            if status_msg:
                await status_msg.edit_text(t(lang,"fail"), reply_markup=kb)
            else:
                await context.bot.send_message(chat_id=cid, text=t(lang,"fail"), reply_markup=kb)
        except: pass

def build_app():
    app=Application.builder().token(BOT_TOKEN).connect_timeout(60).read_timeout(120).write_timeout(120).pool_timeout(60).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(on_callback))
    return app

def main():
    init_db()
    app=build_app()
    if WEBHOOK_URL:
        app.run_webhook(listen="0.0.0.0", port=PORT, url_path=BOT_TOKEN, webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}", drop_pending_updates=True)
    else:
        app.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    main()
