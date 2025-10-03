# main.py
import os
import time
import logging
import feedparser
import requests
import sqlite3
from html import unescape
from telegram import Bot
from telegram.error import TelegramError
from datetime import datetime

# Optional postgres
USE_POSTGRES = bool(os.getenv("DATABASE_URL"))

# Config
BOT_TOKEN ="8442162300:AAEQWEBXzxTCW_lLMRgnWSfy6EViTrzycfM"
CHANNEL_ID ="@NBAZ_1"  # e.g. @NBAZ_1 or -100...
RSS_URL = os.getenv("RSS_URL", "https://www.espn.com/espn/rss/nba/news")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "300"))  # seconds, default 5 minutes

if not BOT_TOKEN or not CHANNEL_ID:
    raise SystemExit("Missing TG_BOT_TOKEN or CHANNEL_ID in environment variables.")

# Logging -> Railway logs will show this
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

bot = Bot(token=BOT_TOKEN)

# Database helpers
if USE_POSTGRES:
    import psycopg2
    from urllib.parse import urlparse

    DATABASE_URL = os.getenv("DATABASE_URL")
    logging.info("Using Postgres database for seen-news storage.")
    def init_db_postgres():
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS seen (
                id TEXT PRIMARY KEY,
                created_at TIMESTAMP NOT NULL
            )
        """)
        conn.commit()
        cur.close()
        conn.close()

    def seen_postgres(id_):
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM seen WHERE id=%s", (id_,))
        r = cur.fetchone()
        cur.close()
        conn.close()
        return r is not None

    def mark_postgres(id_):
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO seen (id, created_at) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (id_, datetime.utcnow()))
        conn.commit()
        cur.close()
        conn.close()

    init_db_postgres()
else:
    DB_PATH = "seen_news.db"
    logging.info(f"Using local SQLite DB at {DB_PATH} for seen-news storage.")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, created_at TIMESTAMP)""")
    conn.commit()

    def seen_sqlite(id_):
        cur.execute("SELECT 1 FROM seen WHERE id=?", (id_,))
        return cur.fetchone() is not None

    def mark_sqlite(id_):
        cur.execute("INSERT OR IGNORE INTO seen (id, created_at) VALUES (?, ?)", (id_, datetime.utcnow()))
        conn.commit()

# Util functions
def get_entries():
    logging.info("Fetching RSS feed...")
    feed = feedparser.parse(RSS_URL)
    if feed.bozo:
        logging.warning("feedparser reported a bozo (malformed) feed: %s", getattr(feed, 'bozo_exception', ''))
    return feed.entries if hasattr(feed, 'entries') else []

def extract_image(entry):
    # try media_content
    if 'media_content' in entry and entry.media_content:
        try:
            return entry.media_content[0].get('url')
        except Exception:
            pass
    # try enclosure
    if 'links' in entry:
        for l in entry.links:
            if l.get('rel') == 'enclosure' and l.get('type','').startswith('image'):
                return l.get('href')
    # try to find <img> in summary/description
    summary = entry.get('summary', '') or entry.get('description', '')
    m = None
    if summary:
        import re
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, re.I)
    if m:
        return m.group(1)
    return None

def format_message(entry):
    title = unescape(entry.get('title','بدون عنوان'))
    summary = unescape(entry.get('summary','') or entry.get('description','') or '')
    # remove html tags lightly
    import re
    plain = re.sub(r'<[^>]+>', '', summary)
    plain = plain.strip()
    if len(plain) > 700:
        plain = plain[:700].rsplit(' ',1)[0] + "..."
    link = entry.get('link','')
    msg = f"<b>{escape_html(title)}</b>\n\n{escape_html(plain)}\n\n<a href=\"{link}\">اقرأ المزيد</a>"
    return msg

def escape_html(s):
    if not s: return ""
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def already_posted(news_id):
    if USE_POSTGRES:
        return seen_postgres(news_id)
    else:
        return seen_sqlite(news_id)

def mark_posted(news_id):
    if USE_POSTGRES:
        mark_postgres(news_id)
    else:
        mark_sqlite(news_id)

def send_to_channel(text, image_url=None):
    try:
        if image_url:
            # try send photo first
            try:
                bot.send_photo(chat_id=CHANNEL_ID, photo=image_url, caption=text, parse_mode="HTML", disable_notification=False)
                return True
            except TelegramError as e:
                logging.warning("send_photo failed, falling back to send_message: %s", e)
        # fallback
        bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML", disable_web_page_preview=False)
        return True
    except Exception as e:
        logging.exception("Failed to send message to Telegram: %s", e)
        return False

def main_loop():
    logging.info("Starting main loop. Poll interval: %s seconds.", POLL_INTERVAL)
    while True:
        try:
            entries = get_entries()
            # entries often newest-first; we want to post oldest-first among new ones
            entries = list(reversed(entries))  # now oldest->newest
            for entry in entries:
                news_id = entry.get('id') or entry.get('link') or entry.get('title')
                if not news_id:
                    continue
                if already_posted(news_id):
                    continue
                title = entry.get('title','')
                logging.info("Posting news: %s", title)
                message = format_message(entry)
                image = extract_image(entry)
                ok = send_to_channel(message, image_url=image)
                if ok:
                    mark_posted(news_id)
                    logging.info("Posted and marked: %s", news_id)
                else:
                    logging.warning("Failed to post: %s", news_id)
                time.sleep(1.0)  # small delay between posts
        except Exception as e:
            logging.exception("Error in main loop: %s", e)
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main_loop()
