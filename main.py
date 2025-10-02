import os
import sqlite3
import time
import feedparser
from telegram import Bot
from dotenv import load_dotenv

# تحميل التوكن واسم القناة
load_dotenv()
BOT_TOKEN = os.getenv("8442162300:AAEQWEBXzxTCW_lLMRgnWSfy6EViTrzycfm")
CHANNEL_ID = os.getenv("@NBAZ_1")

# إعداد البوت
bot = Bot(token="8442162300:AAEQWEBXzxTCW_lLMRgnWSfy6EViTrzycfm")

# إعداد قاعدة البيانات
conn = sqlite3.connect("seen_news.db")
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS seen(id TEXT PRIMARY KEY)""")
conn.commit()

# رابط RSS الرسمي لـ NBA ESPN
RSS_URL = "https://www.espn.com/espn/rss/nba/news"

# فترة التحقق (بالثواني)
POLL_INTERVAL = 300  # كل 5 دقائق

def fetch_rss():
    feed = feedparser.parse(RSS_URL)
    return feed.entries

def news_already_posted(news_id):
    c.execute("SELECT id FROM seen WHERE id=?", (news_id,))
    return c.fetchone() is not None

def mark_news_posted(news_id):
    c.execute("INSERT OR IGNORE INTO seen(id) VALUES (?)", (news_id,))
    conn.commit()

def post_news_to_channel(title, summary, link, image=None):
    text = f"<b>{title}</b>\n{summary}\n<a href='{link}'>اقرأ المزيد</a>"
    try:
        if image:
            bot.send_photo(chat_id=CHANNEL_ID, photo=image, caption=text, parse_mode="HTML")
        else:
            bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML")
        print(f"تم نشر: {title}")
    except Exception as e:
        print(f"خطأ عند النشر: {e}")

def main_loop():
    while True:
        entries = fetch_rss()
        for entry in entries:
            news_id = entry.get('link')
            if news_already_posted(news_id):
                continue

            title = entry.get('title', 'بدون عنوان')
            summary = entry.get('description', '')
            link = entry.get('link', '')
            image = None
            if 'media_content' in entry and entry.media_content:
                image = entry.media_content[0].get('url')

            post_news_to_channel(title, summary, link, image)
            mark_news_posted(news_id)

        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    print("بوت الأخبار NBA بدأ العمل...")
    main_loop()
