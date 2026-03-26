import os
import asyncio
import logging
import sqlite3
import requests
import feedparser
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

load_dotenv()

# Конфигурация
API_TOKEN = os.getenv('BOT_TOKEN')
WEATHER_API_KEY = os.getenv('WEATHER_KEY')
CITY = os.getenv('CITY', 'Moscow')
MORNING_TIME = os.getenv('NOTIFY_TIME', '08:30')
DB_PATH = os.path.join(os.path.dirname(__file__), 'bot_users.db')

RSS_URLS = [
    'https://rssexport.rbc.ru/rbc/news/free/full.rss',
    'https://habr.com/ru/rss/best/daily/'
]

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# --- БАЗА ДАННЫХ (Только ID) ---
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)')
        conn.commit()

def add_user(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))

def remove_user(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('DELETE FROM users WHERE user_id = ?', (user_id,))

def get_all_users():
    with sqlite3.connect(DB_PATH) as conn:
        return [row[0] for row in conn.execute('SELECT user_id FROM users').fetchall()]

# --- СБОР ДАННЫХ ---
def get_weather():
    url = f"http://api.weatherapi.com/v1/current.json?key={WEATHER_API_KEY}&q={CITY}&lang=ru"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            d = r.json()
            temp = round(d["current"]["temp_c"])
            cond = d["current"]["condition"]["text"]
            feels = round(d["current"]["feelslike_c"])
            return f"🌡 <b>Погода в {CITY}:</b> {temp}°C, {cond}\n<i>Ощущается как: {feels}°C</i>\n"
    except: pass
    return "⚠️ Погода временно недоступна.\n"

def get_rates():
    try:
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=10)
        d = r.json()
        usd = d['Valute']['USD']['Value']
        eur = d['Valute']['EUR']['Value']
        # Отступ \n сверху для разделения блоков
        return f"\n💵 <b>Курс ЦБ:</b>\nUSD {usd:.2f} ₽ | EUR {eur:.2f} ₽\n"
    except:
        return "\n⚠️ Курсы валют недоступны.\n"

def get_news():
    text = "\n📰 <b>Главное за утро:</b>\n"
    count = 0
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:3]:
                count += 1
                text += f"{count}. <a href='{entry.link}'>{entry.title}</a>\n"
        except: continue
    return text if count > 0 else "\nНовости не найдены."

async def build_digest():
    return f"☀️ <b>Утренний дайджест</b>\n\n{get_weather()}{get_rates()}{get_news()}"

# --- КЛАВИАТУРА ---
def get_main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📰 Получить сводку сейчас")],
            [KeyboardButton(text="❌ Отписаться от рассылки")]
        ], 
        resize_keyboard=True
    )

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    add_user(message.from_user.id)
    await message.answer(
        f"👋 <b>Бот запущен!</b>\nРассылка в {MORNING_TIME}.",
        parse_mode=ParseMode.HTML, reply_markup=get_main_kb()
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "📖 <b>Справка:</b>\n\n"
        "/start — Подписаться\n"
        "/now — Сводка сейчас\n"
        "/stop — Отписаться\n\n"
        f"Город: {CITY}\nРассылка: {MORNING_TIME}"
    )
    await message.answer(text, parse_mode=ParseMode.HTML)

@dp.message(F.text == "❌ Отписаться от рассылки")
@dp.message(Command("stop"))
async def cmd_stop(message: types.Message):
    remove_user(message.from_user.id)
    await message.answer("📴 Вы отписаны.", reply_markup=ReplyKeyboardRemove())

@dp.message(F.text == "📰 Получить сводку сейчас")
@dp.message(Command("now"))
async def cmd_now(message: types.Message):
    digest = await build_digest()
    await message.answer(digest, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# Админская команда для просмотра ID
@dp.message(Command("admin_users"))
async def cmd_admin_users(message: types.Message):
    if message.from_user.id == int(os.getenv('MY_ID')):
        users = get_all_users()
        await message.answer(f"👥 <b>Подписчиков: {len(users)}</b>\n\n" + "\n".join([f"• <code>{u}</code>" for u in users]), parse_mode=ParseMode.HTML)

# --- РАССЫЛКА ---
async def daily_broadcast():
    users = get_all_users()
    digest = await build_digest()
    for user_id in users:
        try:
            await bot.send_message(user_id, digest, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            await asyncio.sleep(0.05)
        except: pass

async def main():
    init_db()
    h, m = MORNING_TIME.split(":")
    scheduler.add_job(daily_broadcast, "cron", hour=int(h), minute=int(m))
    scheduler.start()
    logger.info(f"Бот запущен. База: {DB_PATH}")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

