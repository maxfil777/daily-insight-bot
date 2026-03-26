# версия v2.1

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
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# Конфигурация
API_TOKEN = os.getenv('BOT_TOKEN')
WEATHER_API_KEY = os.getenv('WEATHER_KEY')
DEFAULT_CITY = os.getenv('CITY', 'Moscow')
MORNING_TIME = os.getenv('NOTIFY_TIME', '08:30')
DB_PATH = os.path.join(os.path.dirname(__file__), 'bot_users.db')

RSS_URLS = [
    'https://rssexport.rbc.ru/rbc/news/free/full.rss',
    'https://habr.com/ru/rss/best/daily/'
]

# --- СОСТОЯНИЯ (FSM) ---
class UserSettings(StatesGroup):
    waiting_for_city = State()

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()

# --- БАЗА ДАННЫХ С МИГРАЦИЕЙ ---

def init_db():
    # Экранируем одинарные кавычки для безопасности в DEFAULT
    safe_default_city = DEFAULT_CITY.replace("'", "''")
    
    with sqlite3.connect(DB_PATH) as conn:
        # 1. Создание таблицы
        conn.execute(f'''CREATE TABLE IF NOT EXISTS users 
                        (user_id INTEGER PRIMARY KEY, city TEXT DEFAULT '{safe_default_city}')''')
        
        # 2. Миграция
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN city TEXT DEFAULT '{safe_default_city}'")
            logger.info("Миграция: колонка city добавлена.")
        except sqlite3.OperationalError:
            pass
        conn.commit()

def add_user(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,))
        conn.commit()

def update_user_city(user_id, city):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('UPDATE users SET city = ? WHERE user_id = ?', (city, user_id))
        conn.commit() # Явный коммит для надежности

def get_user_city(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        res = conn.execute('SELECT city FROM users WHERE user_id = ?', (user_id,)).fetchone()
        return res[0] if res else DEFAULT_CITY

def get_all_users_data():
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute('SELECT user_id, city FROM users').fetchall()

def remove_user(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
        conn.commit()

# --- СБОР ДАННЫХ ---
def get_weather(city):
    url = f"http://api.weatherapi.com/v1/current.json?key={WEATHER_API_KEY}&q={city}&lang=ru"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            d = r.json()
            temp = round(d["current"]["temp_c"])
            cond = d["current"]["condition"]["text"]
            return f"🌡 <b>Погода в {city}:</b> {temp}°C, {cond}\n"
        return None
    except: return None

def get_rates():
    try:
        r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=10)
        d = r.json()
        usd, eur = d['Valute']['USD']['Value'], d['Valute']['EUR']['Value']
        return f"\n💵 <b>Курс ЦБ:</b>\nUSD {usd:.2f} ₽ | EUR {eur:.2f} ₽\n"
    except: return "\n⚠️ Курсы временно недоступны.\n"

def get_news():
    text = "\n📰 <b>Главное за утро:</b>\n"
    count = 0
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:2]:
                count += 1
                text += f"{count}. <a href='{entry.link}'>{entry.title}</a>\n"
        except: continue
    return text if count > 0 else "\nНовости не найдены."

async def build_digest(city):
    weather = get_weather(city) or "⚠️ Ошибка загрузки погоды.\n"
    return f"☀️ <b>Утренний дайджест</b>\n\n{weather}{get_rates()}{get_news()}"

# --- КЛАВИАТУРА ---
def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📰 Сводка сейчас"), KeyboardButton(text="📍 Сменить город")],
        [KeyboardButton(text="❌ Отписаться")]
    ], resize_keyboard=True)

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    add_user(message.from_user.id)
    city = get_user_city(message.from_user.id)
    await message.answer(
        f"👋 <b>Бот запущен!</b>\nГород: {city}. Время: {MORNING_TIME}",
        parse_mode=ParseMode.HTML, reply_markup=get_main_kb()
    )

# FSM: Начало смены города
@dp.message(F.text == "📍 Сменить город")
@dp.message(Command("setcity"))
async def set_city_start(message: types.Message, state: FSMContext):
    await state.set_state(UserSettings.waiting_for_city)
    await message.answer("Напишите название города (например, <i>Sochi</i> или <i>Москва</i>):", 
                         parse_mode=ParseMode.HTML, reply_markup=ReplyKeyboardRemove())

# FSM: Обработка ввода города
@dp.message(UserSettings.waiting_for_city)
async def set_city_process(message: types.Message, state: FSMContext):
    city_name = message.text.strip()
    # Проверка города через API
    if get_weather(city_name):
        update_user_city(message.from_user.id, city_name)
        await state.clear()
        await message.answer(f"✅ Город установлен: <b>{city_name}</b>", 
                             parse_mode=ParseMode.HTML, reply_markup=get_main_kb())
    else:
        await message.answer("❌ Не удалось найти такой город. Попробуйте еще раз или напишите другой.")

@dp.message(F.text == "📰 Сводка сейчас")
@dp.message(Command("now"))
async def cmd_now(message: types.Message):
    city = get_user_city(message.from_user.id)
    digest = await build_digest(city)
    await message.answer(digest, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    city = get_user_city(message.from_user.id)
    await message.answer(f"📖 <b>Справка</b>\nГород: {city}\nРассылка: {MORNING_TIME}\n\n/setcity — сменить локацию", parse_mode=ParseMode.HTML)

@dp.message(F.text == "❌ Отписаться")
@dp.message(Command("stop"))
async def cmd_stop(message: types.Message):
    remove_user(message.from_user.id)
    await message.answer("📴 Вы отписаны.", reply_markup=ReplyKeyboardRemove())

@dp.message(Command("admin_users"))
async def cmd_admin_users(message: types.Message):
    if str(message.from_user.id) == os.getenv('MY_ID'):
        data = get_all_users_data()
        text = f"👥 <b>Подписчиков: {len(data)}</b>\n\n"
        text += "\n".join([f"• <code>{u[0]}</code> ({u[1]})" for u in data])
        await message.answer(text, parse_mode=ParseMode.HTML)

# --- РАССЫЛКА ---
async def daily_broadcast():
    users_data = get_all_users_data()
    for user_id, city in users_data:
        try:
            digest = await build_digest(city)
            await bot.send_message(user_id, digest, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            await asyncio.sleep(0.05)
        except: pass

async def main():
    init_db()
    h, m = MORNING_TIME.split(":")
    scheduler.add_job(daily_broadcast, "cron", hour=int(h), minute=int(m))
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
