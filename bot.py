#!/usr/bin/env python3
"""
Telegram Movie Search Bot (Public-Domain Only)
Searches Internet Archive + Pexels + OMDb for Hindi/Marathi/English movies.

Requirements:
    pip install python-telegram-bot==20.6 requests fuzzywuzzy python-Levenshtein
"""

import logging
import requests
from urllib.parse import quote_plus
from fuzzywuzzy import fuzz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# === CONFIG ===
BOT_TOKEN = "8476398372:AAFr0EBXKX-auyUb1DgFF9Jpxlc0LbzVC7w"
OMDB_API_KEY = "193a5635"  # you already have this key
SEARCH_ROWS = 5
USER_AGENT = "telegram-ia-bot/1.1 (+https://archive.org)"

# === LOGGING ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === INTERNET ARCHIVE HELPERS ===
IA_SEARCH_URL = "https://archive.org/advancedsearch.php"
IA_METADATA_URL = "https://archive.org/metadata/{}"

def ia_search(title: str, rows: int = SEARCH_ROWS):
    """Search Internet Archive for movies by title."""
    q = f'title:("{title}") AND mediatype:(movies) AND (language:(hindi OR english OR marathi))'
    params = {
        "q": q,
        "fl[]": ["identifier", "title", "creator", "date"],
        "rows": rows,
        "page": 1,
        "output": "json"
    }
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(IA_SEARCH_URL, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json().get("response", {}).get("docs", [])

def ia_get_files(identifier: str):
    """Fetch metadata for an item and extract video file links."""
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(IA_METADATA_URL.format(identifier), headers=headers, timeout=15)
    r.raise_for_status()
    meta = r.json()
    files = meta.get("files", [])
    base = f"https://archive.org/download/{identifier}/"
    results = []
    for f in files:
        name = f.get("name", "").lower()
        if name.endswith((".mp4", ".mkv", ".webm", ".ogv")):
            url = base + quote_plus(f.get("name"))
            try:
                head = requests.head(url, timeout=8)
                if head.status_code == 200:
                    results.append({"name": f.get("name"), "url": url})
            except Exception:
                continue
    return results

# === PEXELS VIDEO SEARCH ===
def pexels_search(title: str):
    """Search Pexels (free, short videos) for matching movie clips."""
    API_KEY = "563492ad6f91700001000001"  # Pexels demo key (safe to use)
    headers = {"Authorization": API_KEY}
    r = requests.get(f"https://api.pexels.com/videos/search?query={quote_plus(title)}&per_page=3", headers=headers, timeout=10)
    if r.status_code != 200:
        return []
    data = r.json().get("videos", [])
    results = []
    for v in data:
        url = v.get("video_files", [{}])[0].get("link", "")
        if url:
            results.append({"name": v.get("user", {}).get("name", "Pexels Video"), "url": url})
    return results

# === OMDb TITLE CORRECTION ===
def omdb_correct_title(title: str):
    """Try to correct the spelling and get poster/info."""
    url = f"https://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={quote_plus(title)}"
    r = requests.get(url, timeout=10)
    if r.status_code == 200 and r.json().get("Response") == "True":
        return r.json()
    return None

# === TELEGRAM COMMANDS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 Hello! Send a movie name (Hindi, Marathi, or English).\n"
        "I'll find free, legal movies and clips for you."
    )

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /search <movie title>")
        return
    title = " ".join(context.args)
    await search_and_reply(update, title)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text:
        await search_and_reply(update, text)

async def search_and_reply(update: Update, title: str):
    msg = await update.message.reply_text(f"🔍 Searching for *{title}*...", parse_mode="Markdown")
    omdb_data = omdb_correct_title(title)
    if omdb_data:
        correct_title = omdb_data.get("Title")
        if fuzz.ratio(correct_title.lower(), title.lower()) < 90:
            title = correct_title
        poster = omdb_data.get("Poster", "")
    else:
        poster = ""

    results = []
    try:
        results += ia_search(title)
    except Exception:
        pass
    try:
        pexels_results = pexels_search(title)
        results += [{"identifier": "pexels", "title": r["name"], "extra": r["url"]} for r in pexels_results]
    except Exception:
        pass

    if not results:
        await msg.edit_text("😕 No results found. Try a different or more specific title.")
        return
    await msg.delete()

    if poster and poster != "N/A":
        await update.message.reply_photo(poster, caption=f"*{title}*", parse_mode="Markdown")

    for doc in results[:5]:
        if doc.get("identifier") == "pexels":
            buttons = [[InlineKeyboardButton("🎥 Watch Video", url=doc["extra"])]]
            await update.message.reply_text(f"🎬 *{doc['title']}* (Pexels Free Video)", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
            continue

        identifier = doc.get("identifier")
        title_doc = doc.get("title") or identifier
        files = ia_get_files(identifier)
        buttons = []
        for f in files[:3]:
            label = f["name"][:30] + ("..." if len(f["name"]) > 30 else "")
            buttons.append([InlineKeyboardButton(label, url=f["url"])])

        if not buttons:
            buttons = [[InlineKeyboardButton("View on Archive.org", url=f"https://archive.org/details/{identifier}")]]

        await update.message.reply_text(
            f"🎬 *{title_doc}* (Internet Archive)",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

# === MAIN ===
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
