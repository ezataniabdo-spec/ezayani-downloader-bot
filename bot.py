#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# EZAYANI Downloader - FIXED IG VERSION - HD/MP3 direct no ad

import asyncio, glob, html, logging, os, re, shutil, sqlite3, tempfile, threading, time, uuid
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, constants
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "@EzayaniDownloadBot")
BOT_NAME = os.getenv("BOT_NAME", "EZAYANI Downloader")
CAPTION_CREDIT = os.getenv("CAPTION_CREDIT", "@download_it_bot")
AD_LINK = os.getenv("AD_LINK", "https://shrinkme.io/YOUR_LINK")
ENABLE_AD_STEP = os.getenv("ENABLE_AD_STEP", "1") == "1"
AD_WAIT_SECONDS = int(os.getenv("AD_WAIT_SECONDS", "10"))
ENABLE_FORCE_SUB = os.getenv("ENABLE_FORCE_SUB", "0") == "1"
FORCE_SUB_CHANNEL = os.getenv("FORCE_SUB_CHANNEL", "@EzayaniChannel")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/EzayaniChannel")
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", "5"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "49"))
DB_PATH = os.getenv("DB_PATH", "ezayani_bot.db")

TIKWM_API = "https://tikwm.com/api/"
_own = os.getenv("COBALT_API_URL", "").strip().rstrip("/")
COBALT_API_KEY = os.getenv("COBALT_API_KEY", "")
COBALT_INSTANCES = ([_own] if _own else []) + [i.strip().rstrip("/") for i in "https://co.wuk.sh,https://co.otomir23.me,https://downloadapi.stuff.solutions,https://cobalt-api.kwiatekmiki.com,https://capi.oak.li,https://cobalt-backend.canine.tools".split(",") if i.strip()]
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
PORT = int(os.getenv("PORT", "8080"))
HTTP_TIMEOUT = 30

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
    c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, first_seen TEXT, last_seen TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, user_id INTEGER, url TEXT, platform TEXT, created TEXT, status TEXT, title TEXT, file_id TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, val INTEGER)")
    conn.commit(); conn.close()

def bump_user(uid):
    conn=sqlite3.connect(DB_PATH); c=conn.cursor()
    now=time.strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT OR IGNORE INTO users(id,first_seen,last_seen) VALUES(?,?,?)",(uid,now,now))
    c.execute("UPDATE users SET last_seen=? WHERE id=?",(now,uid))
    conn.commit(); conn.close()

def job_create(uid, url, plat):
    jid=uuid.uuid4().hex[:12]; conn=sqlite3.connect(DB_PATH); c=conn.cursor()
    c.execute("INSERT INTO jobs(id,user_id,url,platform,created,status) VALUES(?,?,?,?,?,?)",(jid,uid,url,plat,time.strftime("%Y-%m-%d %H:%M:%S"),"new"))
    conn.commit(); conn.close(); return jid

def job_get(jid):
    conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row; c=conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id=?",(jid,)); r=c.fetchone(); conn.close()
    return dict(r) if r else None

def job_update(jid, **kw):
    conn=sqlite3.connect(DB_PATH); c=conn.cursor()
    for k,v in kw.items(): c.execute(f"UPDATE jobs SET {k}=? WHERE id=?",(v,jid))
    conn.commit(); conn.close()

# --- lang ---
def lang_of(update):
    code=(update.effective_user.language_code or "ar").lower() if update.effective_user else "ar"
    return "ar" if code.startswith("ar") else "en"

T={
"ar":{"start":"👋 أهلا! أرسل رابط من تيكتوك، انستا، يوتيوب، فيسبوك...","detect":"🔍 اكتشفت: {plat}\n⏳ الرابط محمي - شاهد الإعلان أولا","ad_btn":"▶️ شاهد الإعلان ({sec} ثانية)","ad_wait":"⏳ شاهد الإعلان {sec} ثانية ثم ارجع واضغط تأكيد","ad_confirm":"✅ شاهدت الإعلان - افتح التحميل","downloading":"⏳ جاري التحميل...","too_big":"❌ الملف كبير {size}MB (الحد {max}MB)","fail":"❌ فشل التحميل، جرب رابط آخر","btn_hd":"⬇️ تحميل HD","btn_mp3":"🎵 تحميل MP3","btn_share":"📤 Share","btn_direct":"🔗 رابط مباشر","btn_retry":"🔄 حاول مرة أخرى","caption":"{title}\n\n⬇️ saved by {credit}\n{url}","rate":"⏳ انتظر {sec} ثانية"},
"en":{"start":"👋 Hi! Send a link from TikTok, Insta, YouTube...","detect":"🔍 Detected: {plat}\n⏳ Link locked - watch ad first","ad_btn":"▶️ Watch Ad ({sec}s)","ad_wait":"⏳ Watch ad {sec}s then press confirm","ad_confirm":"✅ I watched - Unlock","downloading":"⏳ Downloading...","too_big":"❌ File too big {size}MB (max {max}MB)","fail":"❌ Download failed","btn_hd":"⬇️ Download HD","btn_mp3":"🎵 Download MP3","btn_share":"📤 Share","btn_direct":"🔗 Direct link","btn_retry":"🔄 Retry","caption":"{title}\n\n⬇️ saved by {credit}\n{url}","rate":"⏳ Wait {sec}s"},
}
def t(lang,k,**kw): return T.get(lang,T["ar"]).get(k,k).format(**kw)
def platform_name(p,lang): return p

# --- download logic ---
def detect_platform(url):
    u=url.lower()
    if "tiktok" in u: return "tiktok"
    if "instagram" in u or "instagr.am" in u: return "instagram"
    if "facebook" in u or "fb.watch" in u: return "facebook"
    if "youtube" in u or "youtu.be" in u: return "youtube"
    if "twitter" in u or "x.com" in u: return "twitter"
    return "other"

def ytdlp_direct(url, audio=False):
    if not HAS_YTDLP: return None
    tmp=tempfile.mkdtemp(prefix="yt_")
    try:
        fmt="bestaudio[ext=m4a]/bestaudio/best" if audio else "bestvideo+bestaudio/best"
        opts={"outtmpl":os.path.join(tmp,"%(title)s.%(ext)s"),"format":fmt,"merge_output_format":"mp4" if not audio else "m4a","quiet":True,"no_warnings":True,"noplaylist":True,"nocheckcertificate":True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info=ydl.extract_info(url, download=True)
            files=glob.glob(os.path.join(tmp,"*"))
            if not files: return None
            fp=max(files, key=os.path.getsize)
            return {"kind":"file","path":fp,"cleanup":tmp,"title":info.get("title",""),"direct":None}
    except Exception as e:
        log.info("ytdlp fail %s %s", url, e)
        shutil.rmtree(tmp, ignore_errors=True)
        return None

def cobalt_try(url, audio=False):
    payload={"url":url}
    if audio: payload["isAudioOnly"]=True
    for inst in COBALT_INSTANCES:
        try:
            api=inst.rstrip("/")+"/api/json" if not inst.endswith("/api/json") else inst
            headers={"Accept":"application/json","Content-Type":"application/json","User-Agent":"Mozilla/5.0"}
            if COBALT_API_KEY: headers["Authorization"]=f"Api-Key {COBALT_API_KEY}"
            r=requests.post(api, json=payload, headers=headers, timeout=15)
            if r.status_code!=200: continue
            j=r.json()
            if j.get("status") in ("redirect","tunnel","picker") and j.get("url"):
                return {"kind":"url","direct":j["url"],"title":j.get("filename") or j.get("text") or ""}
            if j.get("status")=="stream" and j.get("url"):
                return {"kind":"url","direct":j["url"],"title":""}
        except Exception as e:
            log.info("cobalt %s fail %s", inst, e)
            continue
    return None

def tikwm_try(url):
    try:
        r=requests.post(TIKWM_API, json={"url":url}, timeout=15)
        j=r.json()
        if j.get("code")==0 and j.get("data"):
            d=j["data"]
            play=d.get("play") or d.get("hdplay") or d.get("wmplay")
            if play: return {"kind":"url","direct":play,"title":d.get("title","")}
    except Exception as e:
        log.info("tikwm fail %s", e)
    return None

def resolve_url(url, audio=False):
    # 1) tiktok via tikwm first
    if "tiktok.com" in url.lower():
        rr=tikwm_try(url)
        if rr: return rr
    # 2) INSTAGRAM -> ytdlp first (FIX)
    if "instagram.com" in url.lower() or "instagr.am" in url.lower():
        rr=ytdlp_direct(url, audio=audio)
        if rr: return rr
    # 3) cobalt
    rr=cobalt_try(url, audio=audio)
    if rr: return rr
    # 4) ytdlp fallback for everything
    rr=ytdlp_direct(url, audio=audio)
    if rr: return rr
    raise Exception("all backends failed")

def download_file(direct, suffix, max_mb):
    tmp=tempfile.mkdtemp()
    path=os.path.join(tmp, "file"+suffix)
    with requests.get(direct, stream=True, timeout=120, headers={"User-Agent":"Mozilla/5.0"}) as r:
        r.raise_for_status()
        size=0
        with open(path,"wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
                    size+=len(chunk)
                    if size>max_mb*1024*1024:
                        raise Exception("too big")
    return path

def result_keyboard(lang, jid, url):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang,"btn_hd"), callback_data=f"hd:{jid}"),
         InlineKeyboardButton(t(lang,"btn_mp3"), callback_data=f"mp3:{jid}")],
        [InlineKeyboardButton(t(lang,"btn_share"), switch_inline_query=url)],
    ])

def ad_keyboard(lang, jid):
    # First step: only ad
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang,"ad_btn", sec=AD_WAIT_SECONDS), url=AD_LINK)],
        [InlineKeyboardButton(t(lang,"ad_confirm"), callback_data=f"confirm:{jid}")],
    ])

# --- handlers ---
_rate={}
def check_rate(uid):
    now=time.time()
    last=_rate.get(uid,0)
    if now-last<RATE_LIMIT_SECONDS: return RATE_LIMIT_SECONDS - (now-last)
    _rate[uid]=now
    return 0

async def cmd_start(update, context):
    lang=lang_of(update)
    bump_user(update.effective_user.id)
    await update.message.reply_text(t(lang,"start"))

async def handle_link(update, context):
    lang=lang_of(update)
    uid=update.effective_user.id
    bump_user(uid)
    wait=check_rate(uid)
    if wait>0:
        await update.message.reply_text(t(lang,"rate", sec=int(wait)))
        return
    url=(update.message.text or "").strip()
    if not url.startswith("http"):
        await update.message.reply_text(t(lang,"start")); return
    plat=detect_platform(url)
    jid=job_create(uid, url, plat)
    if ENABLE_AD_STEP:
        kb=ad_keyboard(lang, jid)
        await update.message.reply_text(t(lang,"detect", plat=plat.upper()), reply_markup=kb)
    else:
        await process_download(update, context, jid, url, lang, audio=False)

async def on_callback(update, context):
    query=update.callback_query
    await query.answer()
    data=query.data or ""
    lang=lang_of(update)
    if data.startswith("confirm:"):
        jid=data.split(":",1)[1]
        job=job_get(jid)
        if not job:
            await query.edit_message_text(t(lang,"fail")); return
        await query.edit_message_text(t(lang,"downloading"))
        await process_download(update, context, jid, job["url"], lang, audio=False, edit_msg=query.message)
    elif data.startswith("hd:"):
        jid=data.split(":",1)[1]
        job=job_get(jid)
        if not job: return
        await process_download(update, context, jid, job["url"], lang, audio=False, edit_msg=None, new_msg=True, chat_id=query.message.chat_id)
    elif data.startswith("mp3:"):
        jid=data.split(":",1)[1]
        job=job_get(jid)
        if not job: return
        await process_download(update, context, jid, job["url"], lang, audio=True, new_msg=True, chat_id=query.message.chat_id)
    elif data.startswith("go:"):
        jid=data.split(":",1)[1]
        job=job_get(jid)
        if not job: return
        await process_download(update, context, jid, job["url"], lang, audio=False)

async def process_download(update, context, jid, url, lang, audio=False, edit_msg=None, new_msg=False, chat_id=None):
    try:
        res=resolve_url(url, audio=audio)
        # if file already downloaded via ytdlp
        if res["kind"]=="file":
            path=res["path"]; cleanup=res["cleanup"]
            kb=result_keyboard(lang, jid, url)
            cap=t(lang,"caption", title=res.get("title","")[:200], credit=CAPTION_CREDIT, url=url)
            # send
            bot=context.bot
            cid=chat_id or (edit_msg.chat_id if edit_msg else update.effective_chat.id)
            with open(path,"rb") as fh:
                if audio:
                    await bot.send_audio(chat_id=cid, audio=fh, title=res.get("title","audio")[:200], caption=cap, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
                else:
                    await bot.send_video(chat_id=cid, video=fh, supports_streaming=True, caption=cap, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
            shutil.rmtree(cleanup, ignore_errors=True)
            if edit_msg:
                try: await edit_msg.delete()
                except: pass
            return
        # url kind
        direct=res["direct"]
        kb=result_keyboard(lang, jid, url)
        cap=t(lang,"caption", title=res.get("title","")[:200], credit=CAPTION_CREDIT, url=url)
        bot=context.bot
        cid=chat_id or (edit_msg.chat_id if edit_msg else update.effective_chat.id)
        # try send by url
        try:
            if audio:
                await bot.send_audio(chat_id=cid, audio=direct, title=res.get("title","audio")[:200], caption=cap, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
            else:
                await bot.send_video(chat_id=cid, video=direct, supports_streaming=True, caption=cap, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
        except TelegramError:
            # download then upload
            path=download_file(direct, ".mp3" if audio else ".mp4", MAX_UPLOAD_MB)
            with open(path,"rb") as fh:
                if audio:
                    await bot.send_audio(chat_id=cid, audio=fh, title=res.get("title","audio")[:200], caption=cap, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
                else:
                    await bot.send_video(chat_id=cid, video=fh, supports_streaming=True, caption=cap, parse_mode=constants.ParseMode.HTML, reply_markup=kb)
            os.remove(path)
        if edit_msg and not new_msg:
            try: await edit_msg.delete()
            except: pass
    except Exception as e:
        log.exception("download error %s", url)
        kb=InlineKeyboardMarkup([[InlineKeyboardButton(t(lang,"btn_retry"), callback_data=f"go:{jid}")]])
        try:
            if edit_msg:
                await edit_msg.edit_text(t(lang,"fail"), reply_markup=kb)
            else:
                await context.bot.send_message(chat_id=chat_id or update.effective_chat.id, text=t(lang,"fail"), reply_markup=kb)
        except:
            pass

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
