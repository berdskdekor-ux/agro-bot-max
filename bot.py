




# bot.py — Агроном-бот для MAX
import os
import json
import time
import threading
import uuid
import secrets
import string
from datetime import datetime, timedelta, date
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, HTMLResponse

from maxapi import Bot, Dispatcher
from maxapi.types import (
    MessageCreated, BotStarted, MessageCallback,
    CallbackButton, Command
)
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.filters import F

from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotification
import requests

# ─────────────────────────────
# Переменные окружения
# ─────────────────────────────
MAX_BOT_TOKEN = os.getenv ( " MAX_BOT_TOKEN" )
YOOKASSA_SHOP_ID = os.getenv ( " YOOKASSA_SHOP_ID" )
YOOKASSA_SECRET_KEY = os.getenv ( " YOOKASSA_SECRET_KEY" )
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
YANDEX_SEARCH_TOKEN = os.getenv("YANDEX_SEARCH_TOKEN")
PLANTNET_API_KEY = os.getenv("PLANTNET_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

required = {
    "MAX_BOT_TOKEN": MAX_BOT_TOKEN,
    "YOOKASSA_SHOP_ID": YOOKASSA_SHOP_ID,
    "YOOKASSA_SECRET_KEY": YOOKASSA_SECRET_KEY,
    "YANDEX_API_KEY": YANDEX_API_KEY,
    "YANDEX_FOLDER_ID": YANDEX_FOLDER_ID,
    "PLANTNET_API_KEY": PLANTNET_API_KEY,
    "WEATHER_API_KEY": WEATHER_API_KEY,
}
missing = [k for k, v in required.items() if not v]
if missing:
    raise ValueError(f"Отсутствуют обязательные переменные: {', '.join(missing)}")

Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

# ─────────────────────────────
# Администраторы (замени 0 на свой ID после первого запуска)
# ─────────────────────────────
ADMIN_IDS = [
    0,
]

# ─────────────────────────────
# FastAPI + MAX
# ─────────────────────────────
app = FastAPI(title="Агроном-бот MAX")
bot = Bot(MAX_BOT_TOKEN)
dp = Dispatcher()
try:
    main_loop = asyncio.get_running_loop()
except RuntimeError:
    main_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(main_loop)
# ─────────────────────────────
# Данные
# ─────────────────────────────
DATA_FILE = "data.json"
user_data = {}

FREE_LIMITS = {
    "photos": 2,
    "reminders": 1,
    "gpt_queries": 5
}

STATE_WAIT_REGION = "wait_region"
STATE_ADD_REM_TEXT = "add_rem_text"
STATE_ADD_REM_DATE = "add_rem_date"
STATE_ADD_REM_TIME = "add_rem_time"
STATE_EDIT_REM_VALUE = "edit_rem_value"
STATE_WAIT_OTHER_CULTURE = "wait_other_culture"
STATE_WAIT_GIFT_TOKEN = "wait_gift_token"
STATE_ADMIN_PIN = "admin_pin"

CATEGORIES = {
    "🥦 Овощи": ["🍅 Томаты", "🥒 Огурцы", "🌶 Перец", "🥬 Капуста", "🥕 Морковь", "🫑 Свёкла", "🥔 Картофель", "🧅 Лук", "🧄 Чеснок", "🍆 Баклажаны", "🥬 Кабачки"],
    "🍎 Фрукты": ["🍓 Клубника", "🍇 Малина", "🍉 Арбуз", "🍈 Дыня", "🍏 Яблоки", "🍐 Груши", "🍒 Вишня"],
    "🌸 Цветы": ["🌺 Петуния", "🌼 Бархатцы", "🌹 Розы", "🌷 Лилии", "🌻 Астры"],
    "🌳 Кустарники, плодовые деревья": ["🍇 Смородина", "🥝 Крыжовник", "🍇 Малина", "🍇 Виноград", "🍎 Яблоня", "🍐 Груша"],
    "🌿 Другие культуры": []
}
ALL_CULTURES = [c for cats in CATEGORIES.values() for c in cats]

def load_data():
    global user_data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                user_data = json.load(f)
            print("Данные загружены")
        except Exception as e:
            print(f"Ошибка загрузки: {e}")
            user_data = {}
    else:
        user_data = {}

def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения: {e}")

load_data()

# ─────────────────────────────
# Подарочные токены (7 дней)
# ─────────────────────────────
def generate_gift_token() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "GIFT-" + "".join(secrets.choice(alphabet) for _ in range(10))

def create_gift_token(created_by: int) -> str:
    token = generate_gift_token()
    gifts = user_data.setdefault("gift_tokens", {})
    gifts[token] = {
        "created_by": created_by,
        "created_at": datetime.now().isoformat(),
        "used_by": None,
        "used_at": None,
        "active": True
    }
    save_data()
    return token

def activate_gift_token(uid: str, token: str) -> tuple[bool, str]:
    gifts = user_data.get("gift_tokens", {})
    token = token.strip().upper()
    if token not in gifts:
        return False, "Токен не найден."
    gift = gifts[token]
    if not gift.get("active") or gift.get("used_by"):
        return False, "Этот токен уже был использован."
    
    user = user_data.setdefault(uid, {})
    now = datetime.now()
    until = now + timedelta(days=7)
    user["premium"] = True
    user["premium_until"] = until.isoformat()
    
    gift["used_by"] = uid
    gift["used_at"] = now.isoformat()
    gift["active"] = False
    save_data()
    return True, f"Подарочный премиум активирован до {until.strftime('%d.%m.%Y %H:%M')}!"

# ─────────────────────────────
# Лимиты и премиум
# ─────────────────────────────
def is_premium_active(uid: str) -> bool:
    user = user_data.get(uid, {})
    if not user.get("premium", False):
        return False
    until_str = user.get("premium_until")
    if not until_str:
        return False
    try:
        return datetime.now() < datetime.fromisoformat(until_str)
    except:
        return False

def can_use_feature(uid: str, feature: str) -> tuple[bool, int]:
    user = user_data.setdefault(uid, {})
    if is_premium_active(uid):
        return True, 999
    today = date.today().isoformat()
    key_last = f"{feature}_last_date"
    key_count = f"{feature}_count"
    if user.get(key_last) != today:
        user[key_last] = today
        user[key_count] = 0
    count = user.get(key_count, 0)
    max_count = FREE_LIMITS.get(feature, 999)
    if count >= max_count:
        return False, 0
    return True, max(0, max_count - count - 1)

def use_feature(uid: str, feature: str):
    if is_premium_active(uid):
        return
    user = user_data.setdefault(uid, {})
    today = date.today().isoformat()
    user[f"{feature}_last_date"] = today
    user[f"{feature}_count"] = user.get(f"{feature}_count", 0) + 1
    save_data()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ─────────────────────────────
# Напоминания
# ─────────────────────────────
def get_user_reminders(uid: str):
    return user_data.get(uid, {}).get("reminders", [])

def save_reminder(uid: str, text: str, dt_iso: str):
    user = user_data.setdefault(uid, {})
    reminders = user.setdefault("reminders", [])
    new_id = max([r.get("id", 0) for r in reminders], default=0) + 1
    reminders.append({"id": new_id, "text": text.strip(), "datetime": dt_iso, "sent": False})
    save_data()

def delete_reminder(uid: str, rem_id: int) -> bool:
    user = user_data.get(uid, {})
    if "reminders" not in user:
        return False
    old_len = len(user["reminders"])
    user["reminders"] = [r for r in user["reminders"] if r.get("id") != rem_id]
    if len(user["reminders"]) < old_len:
        save_data()
        return True
    return False

def mark_reminder_sent(uid: str, rem_id: int):
    for r in user_data.get(uid, {}).get("reminders", []):
        if r.get("id") == rem_id:
            r["sent"] = True
            save_data()
            return True
    return False

# ─────────────────────────────
# YandexGPT + Поиск + Погода
# ─────────────────────────────
def search_yandex_web(query: str, max_results: int = 5) -> str:
    if not YANDEX_SEARCH_TOKEN or not YANDEX_FOLDER_ID:
        return ""
    url = "https://searchapi.api.cloud.yandex.net/v2/web/search"
    headers = {
        "Authorization": f"Bearer {YANDEX_SEARCH_TOKEN}",
        "x-folder-id": YANDEX_FOLDER_ID.strip(),
        "Content-Type": "application/json"
    }
    payload = {
        "query": {"query_text": query, "search_type": "SEARCH_TYPE_RU", "language": "ru"},
        "page_size": max_results,
        "sort": "relevance"
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code == 200:
            items = r.json().get("items", [])
            if not items:
                return ""
            lines = ["🔍 Свежие данные из Яндекса:"]
            for item in items[:max_results]:
                title = item.get("title", "—")
                snippet = item.get("snippet", "")[:280].strip()
                url_ = item.get("url", "—")
                if snippet:
                    lines.append(f"**{title}**\n{snippet}…\n{url_}")
            return "\n\n".join(lines) + "\n"
        return ""
    except Exception as e:
        print(f"[SEARCH] {e}")
        return ""

def ask_yandexgpt(region: str, question: str) -> str:
    search_results = search_yandex_web(question)
    system_prompt = (
        f"Ты агроном-консультант. Регион: {region}. "
        "Отвечай на русском, понятно, пошагово, по делу. "
        "Если есть свежие данные из поиска — опирайся на них."
    )
    messages = [{"role": "system", "text": system_prompt}]
    if search_results:
        messages.append({"role": "user", "text": f"Свежие данные:\n{search_results}\n\nВопрос: {question}"})
    else:
        messages.append({"role": "user", "text": question})

    try:
        url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        headers = {"Authorization": f"Api-Key {YANDEX_API_KEY}", "Content-Type": "application/json"}
        data = {
            "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt-lite",
            "completionOptions": {"stream": False, "temperature": 0.45, "maxTokens": 1400},
            "messages": messages
        }
        r = requests.post(url, headers=headers, json=data, timeout=18)
        r.raise_for_status()
        text = r.json()["result"]["alternatives"][0]["message"]["text"].strip()
        if search_results:
            text += "\n\n(использованы свежие данные поиска Яндекса)"
        return text
    except Exception as e:
        print(f"[GPT] {e}")
        return f"Ошибка ответа агронома: {str(e)}"

def get_week_weather(city: str) -> str:
    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
        resp = requests.get(url, timeout=10).json()
        if resp.get("cod") != "200":
            return f"Ошибка погоды: {resp.get('message')}"
        days = {}
        for item in resp["list"]:
            d = item["dt_txt"].split()[0]
            days.setdefault(d, []).append((item["main"]["temp"], item["weather"][0]["description"]))
        lines = ["🌦 Прогноз на 5 дней:"]
        for d, vals in list(days.items())[:5]:
            avg = sum(v[0] for v in vals) / len(vals)
            lines.append(f"{d}: {vals[0][1].capitalize()}, ≈{round(avg,1)}°C")
        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка погоды: {str(e)}"

# ─────────────────────────────
# Клавиатуры
# ─────────────────────────────
def main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="🌦 Погода", payload="menu_weather"),
        CallbackButton(text="📸 Диагностика", payload="menu_diag")
    )
    builder.row(
        CallbackButton(text="⏰ Напоминание", payload="menu_reminder"),
        CallbackButton(text="💎 Премиум", payload="menu_premium")
    )
    builder.row(
        CallbackButton(text="📅 Календарь посадок", payload="menu_calendar"),
        CallbackButton(text="📖 Инструкция", payload="menu_help")
    )
    builder.row(CallbackButton(text="🎁 Ввести подарочный токен", payload="menu_gift"))
    return builder.as_markup()

def premium_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="🟡 День — 10 ₽", payload="premium_day"))
    builder.row(CallbackButton(text="🟢 Неделя — 50 ₽", payload="premium_week"))
    builder.row(CallbackButton(text="🔵 Месяц — 150 ₽", payload="premium_month"))
    builder.row(CallbackButton(text="🟣 Год — 1500 ₽", payload="premium_year"))
    builder.row(CallbackButton(text="⬅️ Назад", payload="back_main"))
    return builder.as_markup()

def reminder_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="➕ Добавить напоминание", payload="rem_add"))
    builder.row(CallbackButton(text="📋 Мои напоминания", payload="rem_list"))
    builder.row(CallbackButton(text="⬅️ Назад", payload="back_main"))
    return builder.as_markup()

def category_keyboard():
    builder = InlineKeyboardBuilder()
    cats = list(CATEGORIES.keys())
    for i in range(0, len(cats), 2):
        row = [CallbackButton(text=c, payload=f"cat_{c}") for c in cats[i:i+2]]
        builder.row(*row)
    builder.row(CallbackButton(text="⬅️ Назад", payload="back_main"))
    return builder.as_markup()

def help_text():
    return (
        "📖 <b>Инструкция по работе с ботом</b>\n\n"
        "Я — бот-агроном. Вот что я умею:\n\n"
        "🌦 <b>Погода</b> — прогноз на 5 дней\n"
        "📸 <b>Диагностика</b> — пришлите фото растения\n"
        "⏰ <b>Напоминания</b> — полив, посадка и т.д.\n"
        "📅 <b>Календарь посадок</b> — лунный календарь + рекомендации\n"
        "💎 <b>Премиум</b> — снимает все лимиты\n\n"
        "<b>Как правильно задавать вопросы:</b>\n"
        "• Пишите конкретно: «Когда сажать томаты в Новосибирской области»\n"
        "• Указывайте регион и культуру\n"
        "• Можно просто писать вопросы текстом\n\n"
        "<b>Лимиты бесплатного режима:</b>\n"
        "• 2 фото в день\n"
        "• 5 вопросов агроному в день\n"
        "• 1 напоминание\n\n"
        "Есть подарочный токен? Нажмите «🎁 Ввести подарочный токен»"
    )

# ─────────────────────────────
# Хелперы
# ─────────────────────────────
async def answer(event, text: str, keyboard=None):
    attachments = [keyboard] if keyboard else None
    await event.message.answer(text, attachments=attachments)

# ─────────────────────────────
# Старт бота
# ─────────────────────────────
@dp.bot_started()
async def on_bot_started(event: BotStarted):
    uid = str(event.user.user_id)
    user = user_data.setdefault(uid, {})
    user["max_user_id"] = event.user.user_id
    save_data()

    if "region" in user and user["region"].strip():
        await event.bot.send_message(
            chat_id=event.chat_id,
            text=f"С возвращением!\nВаш регион: <b>{user['region']}</b>\n\nВыберите действие:",
            attachments=[main_keyboard()]
        )
    else:
        user["state"] = STATE_WAIT_REGION
        save_data()
        await event.bot.send_message(
            chat_id=event.chat_id,
            text="Привет! Я бот-агроном 🌱\n\nУкажи свой регион (например: Новосибирская область):"
        )

@dp.message_created(Command("start"))
async def cmd_start(event: MessageCreated):
    uid = str(event.message.sender.user_id)
    user = user_data.setdefault(uid, {})
    user["max_user_id"] = event.message.sender.user_id
    save_data()

    if "region" in user and user["region"].strip():
        await answer(event, f"С возвращением! Ваш регион: <b>{user['region']}</b>\n\nВыберите действие:", main_keyboard())
    else:
        user["state"] = STATE_WAIT_REGION
        save_data()
        await answer(event, "Привет! Я бот-агроном 🌱\n\nУкажи свой регион (например: Московская область):")

# ─────────────────────────────
# Главный текстовый обработчик
# ─────────────────────────────
@dp.message_created(F.message.body.text)
async def message_handler(event: MessageCreated):
    uid = str(event.message.sender.user_id)
    text = (event.message.body.text or "").strip()
    user = user_data.setdefault(uid, {})
    state = user.get("state")
    user_id = event.message.sender.user_id

    # Админ: закрепление сообщения
    if state == STATE_ADMIN_PIN and is_admin(user_id):
        user_data["pinned_message"] = {
            "text": text,
            "from_admin": uid,
            "created_at": datetime.now().isoformat()
        }
        user.pop("state", None)
        save_data()
        await answer(event, "✅ Сообщение закреплено.")
        return

    if state == STATE_WAIT_REGION:
        if len(text) < 3:
            await answer(event, "Название региона слишком короткое.")
            return
        user["region"] = text
        user.pop("state", None)
        save_data()
        await answer(event, f"Отлично! Запомнил: <b>{text}</b> 🌍\n\nВыберите действие:", main_keyboard())
        return

    if state == STATE_WAIT_GIFT_TOKEN:
        success, msg = activate_gift_token(uid, text)
        user.pop("state", None)
        save_data()
        await answer(event, msg, main_keyboard())
        return

    if state == STATE_ADD_REM_TEXT:
        if not text:
            await answer(event, "Текст не может быть пустым.")
            return
        user["temp_rem_text"] = text
        user["state"] = STATE_ADD_REM_DATE
        save_data()
        await answer(event, "Укажите дату (дд.мм.гггг):\nПример: 15.08.2026")
        return

    if state == STATE_ADD_REM_DATE:
        try:
            parts = text.replace(" ", "").split(".")
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            dt_date = datetime(y, m, d)
            if dt_date.date() < date.today():
                await answer(event, "Дата должна быть в будущем.")
                return
            user["temp_rem_date"] = dt_date.isoformat()
            user["state"] = STATE_ADD_REM_TIME
            save_data()
            await answer(event, "Укажите время (чч:мм):\nПример: 14:30")
        except:
            await answer(event, "Неверный формат даты. Нужно: 15.08.2026")
        return

    if state == STATE_ADD_REM_TIME:
        try:
            h, mm = map(int, text.replace(" ", "").split(":"))
            dt_date = datetime.fromisoformat(user["temp_rem_date"])
            dt = dt_date.replace(hour=h, minute=mm)
            if dt < datetime.now():
                await answer(event, "Дата и время должны быть в будущем.")
                return
            can_use, _ = can_use_feature(uid, "reminders")
            if not can_use and not is_premium_active(uid):
                await answer(event, "Лимит бесплатных напоминаний исчерпан.", main_keyboard())
                user.pop("state", None)
                user.pop("temp_rem_text", None)
                user.pop("temp_rem_date", None)
                save_data()
                return
            save_reminder(uid, user["temp_rem_text"], dt.isoformat())
            if not is_premium_active(uid):
                use_feature(uid, "reminders")
            user.pop("state", None)
            user.pop("temp_rem_text", None)
            user.pop("temp_rem_date", None)
            save_data()
            await answer(event, f"✅ Напоминание создано на {dt.strftime('%d.%m.%Y %H:%M')}", main_keyboard())
        except:
            await answer(event, "Неверный формат времени. Пример: 14:30")
        return

    if state == STATE_WAIT_OTHER_CULTURE:
        if not text:
            await answer(event, "Название культуры не может быть пустым.")
            return
        can_use, _ = can_use_feature(uid, "gpt_queries")
        if not can_use:
            await answer(event, "🚫 Лимит запросов исчерпан.", main_keyboard())
            return
        use_feature(uid, "gpt_queries")
        region = user.get("region", "Россия")
        year = datetime.now().year
        prompt = f"Для культуры '{text}' в регионе {region} на {year} год: оптимальное время посадки, сорта, рекомендации."
        ans = ask_yandexgpt(region, prompt)
        user.pop("state", None)
        save_data()
        await answer(event, ans, main_keyboard())
        return

    # Обычный вопрос агроному
    can_use, _ = can_use_feature(uid, "gpt_queries")
    if not can_use:
        await answer(event, "🚫 Лимит бесплатных запросов исчерпан (5 шт).", main_keyboard())
        return
    use_feature(uid, "gpt_queries")
    region = user.get("region", "Россия")
    ans = ask_yandexgpt(region, text)
    await answer(event, ans, main_keyboard())

# ─────────────────────────────
# Callback-кнопки
# ─────────────────────────────
@dp.message_callback(F.callback.payload == "menu_help")
async def show_help(event: MessageCallback):
    await event.message.answer(help_text(), attachments=[main_keyboard()])

@dp.message_callback(F.callback.payload == "menu_weather")
async def menu_weather(event: MessageCallback):
    uid = str(event.callback.user.user_id)
    region = user_data.get(uid, {}).get("region", "Moscow")
    await event.message.answer(get_week_weather(region), attachments=[main_keyboard()])

@dp.message_callback(F.callback.payload == "menu_diag")
async def menu_diag(event: MessageCallback):
    await event.message.answer(
        "Пришлите фото растения крупным планом (лист, цветок, плод или повреждения).",
        attachments=[main_keyboard()]
    )

@dp.message_callback(F.callback.payload == "menu_premium")
async def menu_premium(event: MessageCallback):
    uid = str(event.callback.user.user_id)
    status = ""
    if is_premium_active(uid):
        until = user_data[uid].get("premium_until", "")[:16].replace("T", " ")
        status = f"\n\n✅ Премиум активен до <b>{until}</b>"
    text = (
        "💎 <b>Premium-доступ</b>\n\n"
        "• Безлимитная диагностика\n"
        "• Безлимитные вопросы агроному\n"
        "• Безлимитные напоминания\n\n"
        "Выберите тариф:" + status
    )
    await event.message.answer(text, attachments=[premium_keyboard()])

@dp.message_callback(F.callback.payload == "menu_gift")
async def menu_gift(event: MessageCallback):
    uid = str(event.callback.user.user_id)
    user_data.setdefault(uid, {})["state"] = STATE_WAIT_GIFT_TOKEN
    save_data()
    await event.message.answer("🎁 Введите подарочный токен (например GIFT-XXXXXXXXXX):")

@dp.message_callback(F.callback.payload == "back_main")
async def back_main(event: MessageCallback):
    await event.message.answer("Главное меню:", attachments=[main_keyboard()])

@dp.message_callback(F.callback.payload == "menu_reminder")
async def menu_reminder(event: MessageCallback):
    await event.message.answer("⏰ Управление напоминаниями:", attachments=[reminder_keyboard()])

@dp.message_callback(F.callback.payload == "rem_add")
async def rem_add(event: MessageCallback):
    uid = str(event.callback.user.user_id)
    user_data.setdefault(uid, {})["state"] = STATE_ADD_REM_TEXT
    save_data()
    await event.message.answer("Напишите текст напоминания:")

@dp.message_callback(F.callback.payload == "rem_list")
async def rem_list(event: MessageCallback):
    uid = str(event.callback.user.user_id)
    reminders = get_user_reminders(uid)
    if not reminders:
        text = "У вас пока нет напоминаний."
    else:
        lines = ["Ваши напоминания:"]
        for r in sorted(reminders, key=lambda x: x.get("datetime", "")):
            try:
                dt = datetime.fromisoformat(r["datetime"])
                status = "✅" if r.get("sent") else "⏳"
                lines.append(f"{status} #{r['id']} | {dt.strftime('%d.%m.%Y %H:%M')} | {r['text'][:50]}")
            except:
                lines.append(f"#{r['id']} | {r['text'][:50]}")
        text = "\n".join(lines)
    await event.message.answer(text, attachments=[reminder_keyboard()])

@dp.message_callback(F.callback.payload == "menu_calendar")
async def menu_calendar(event: MessageCallback):
    uid = str(event.callback.user.user_id)
    can_use, _ = can_use_feature(uid, "gpt_queries")
    if not can_use:
        await event.message.answer("🚫 Лимит запросов исчерпан.", attachments=[main_keyboard()])
        return
    use_feature(uid, "gpt_queries")
    region = user_data.get(uid, {}).get("region", "Россия")
    year = datetime.now().year
    prompt = (
        f"Дай общий лунный посевной календарь на {year} год для России/СНГ, "
        "с благоприятными днями по месяцам для вершков и корешков, запрещёнными днями."
    )
    calendar_text = ask_yandexgpt(region, prompt)
    await event.message.answer(calendar_text + "\n\nВыберите категорию:", attachments=[category_keyboard()])

@dp.message_callback(F.callback.payload.startswith("cat_"))
async def choose_category(event: MessageCallback):
    category = event.callback.payload[4:]
    if category == "🌿 Другие культуры":
        uid = str(event.callback.user.user_id)
        user_data.setdefault(uid, {})["state"] = STATE_WAIT_OTHER_CULTURE
        save_data()
        await event.message.answer("Напишите название культуры:")
        return
    cultures = CATEGORIES.get(category, [])
    builder = InlineKeyboardBuilder()
    for i in range(0, len(cultures), 2):
        row = [CallbackButton(text=c, payload=f"cult_{c}") for c in cultures[i:i+2]]
        builder.row(*row)
    builder.row(CallbackButton(text="⬅️ Назад", payload="menu_calendar"))
    await event.message.answer(f"Выберите культуру ({category}):", attachments=[builder.as_markup()])

@dp.message_callback(F.callback.payload.startswith("cult_"))
async def choose_culture(event: MessageCallback):
    culture = event.callback.payload[5:]
    uid = str(event.callback.user.user_id)
    can_use, _ = can_use_feature(uid, "gpt_queries")
    if not can_use:
        await event.message.answer("🚫 Лимит запросов исчерпан.", attachments=[main_keyboard()])
        return
    use_feature(uid, "gpt_queries")
    region = user_data.get(uid, {}).get("region", "Россия")
    year = datetime.now().year
    prompt = f"Для культуры '{culture}' в регионе {region} на {year} год: оптимальное время посадки, сорта, рекомендации."
    ans = ask_yandexgpt(region, prompt)
    await event.message.answer(ans, attachments=[main_keyboard()])

@dp.message_callback(F.callback.payload.startswith("premium_"))
async def process_premium(event: MessageCallback):
    plan = event.callback.payload.split("_")[1]
    uid = str(event.callback.user.user_id)
    plans = {
        "day":   {"amount": "10.00", "desc": "Премиум на 1 день", "days": 1},
        "week":  {"amount": "50.00", "desc": "Премиум на 7 дней", "days": 7},
        "month": {"amount": "150.00", "desc": "Премиум на 30 дней", "days": 30},
        "year":  {"amount": "1500.00", "desc": "Премиум на 365 дней", "days": 365},
    }
    if plan not in plans:
        return
    p = plans[plan]
    try:
        payment = Payment.create({
            "amount": {"value": p["amount"], "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": "https://ваш-домен.onrender.com/success"},
            "capture": True,
            "description": p["desc"],
            "metadata": {"user_id": uid, "plan": plan}
        }, str(uuid.uuid4()))
        await event.message.answer(
            f"Для активации премиума перейдите по ссылке:\n\n{payment.confirmation.confirmation_url}\n\n"
            "После оплаты премиум активируется автоматически."
        )
    except Exception as e:
        await event.message.answer(f"Ошибка создания платежа: {e}")

# ─────────────────────────────
# Админ-команды
# ─────────────────────────────
@dp.message_created(Command("gift"))
async def admin_create_gift(event: MessageCreated):
    if not is_admin(event.message.sender.user_id):
        await answer(event, "Только для администраторов.")
        return
    token = create_gift_token(event.message.sender.user_id)
    await answer(event, f"🎁 Подарочный токен на 7 дней:\n\n<code>{token}</code>\n\nОдноразовый.")

@dp.message_created(Command("pin"))
async def admin_pin_start(event: MessageCreated):
    if not is_admin(event.message.sender.user_id):
        await answer(event, "Только для администраторов.")
        return
    uid = str(event.message.sender.user_id)
    user_data.setdefault(uid, {})["state"] = STATE_ADMIN_PIN
    save_data()
    await answer(event, "📌 Отправьте сообщение для закрепления.\nДля отмены: /cancel")

@dp.message_created(Command("cancel"))
async def cancel_state(event: MessageCreated):
    uid = str(event.message.sender.user_id)
    user_data.setdefault(uid, {}).pop("state", None)
    save_data()
    await answer(event, "Режим отменён.", main_keyboard())

# ─────────────────────────────
# Фото (диагностика)
# ─────────────────────────────
async def analyze_plantnet(file_url: str, region: str) -> str:
    temp_path = f"temp_plant_{uuid.uuid4().hex[:8]}.jpg"
    try:
        resp = requests.get(file_url, timeout=20)
        if resp.status_code != 200:
            return "Не удалось скачать фото."
        with open(temp_path, "wb") as f:
            f.write(resp.content)
        if os.path.getsize(temp_path) > 5 * 1024 * 1024:
            return "Фото слишком большое (>5 МБ)."

        url = "https://my-api.plantnet.org/v2/identify/all"
        params = {"api-key": PLANTNET_API_KEY, "lang": "ru"}
        with open(temp_path, "rb") as img:
            files = {"images": ("photo.jpg", img, "image/jpeg")}
            response = requests.post(url, files=files, params=params, timeout=30)

        if response.status_code != 200:
            return f"Pl@ntNet ошибка {response.status_code}"
        data = response.json()
        if not data.get("results"):
            return "Растение не распознано."

        best = data["results"][0]
        species = best["species"]
        sci_name = species.get("scientificNameWithoutAuthor", "—")
        family = species.get("family", {}).get("scientificNameWithoutAuthor", "—")
        common = ", ".join(species.get("commonNames", [])[:3]) or "—"
        score = best["score"] * 100

        desc = f"**{sci_name}**\nСемейство: {family}\nНазвания: {common}\nУверенность: {score:.1f}%"
        prompt = f"Растение: {sci_name} ({family}). Вероятность {score:.0f}%. Болезни, вредители, 2-3 совета по уходу в регионе {region}."
        advice = ask_yandexgpt(region, prompt)
        return f"Анализ фото:\n{desc}\n\n{advice}"
    except Exception as e:
        return f"Ошибка анализа: {e}"
    finally:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass

@dp.message_created(F.message.body.attachments)
async def handle_photo(event: MessageCreated):
    uid = str(event.message.sender.user_id)
    user = user_data.get(uid, {})
    if "region" not in user:
        await answer(event, "Сначала укажите регион через /start")
        return

    photo_url = None
    for att in (event.message.body.attachments or []):
        photo_url = getattr(att, "url", None) or getattr(getattr(att, "payload", None), "url", None)
        if photo_url:
            break
    if not photo_url:
        await answer(event, "Не удалось получить фото.")
        return

    can_use, _ = can_use_feature(uid, "photos")
    if not can_use:
        await answer(event, "🚫 Лимит диагностики исчерпан (2 фото).", main_keyboard())
        return

    use_feature(uid, "photos")
    await answer(event, "🔬 Анализирую фото...")
    result = await analyze_plantnet(photo_url, user.get("region", "Россия"))
    await answer(event, result, main_keyboard())

# ─────────────────────────────
# ЮKassa webhook
# ─────────────────────────────
@app.post("/yookassa-webhook")
async def yookassa_webhook(request: Request):
    try:
        data = await request.json()
        notification = WebhookNotification(data)
        if notification.event == "payment.succeeded":
            meta = notification.object.metadata or {}
            uid = meta.get("user_id")
            plan = meta.get("plan")
            if uid and plan:
                days = {"day": 1, "week": 7, "month": 30, "year": 365}.get(plan, 30)
                until = datetime.now() + timedelta(days=days)
                user = user_data.setdefault(str(uid), {})
                user["premium"] = True
                user["premium_until"] = until.isoformat()
                save_data()
                asyncio.run_coroutine_threadsafe(
                    bot.send_message(chat_id=int(uid), text=f"🎉 Премиум активирован до {until.strftime('%d.%m.%Y %H:%M')}!"),
                    main_loop
                )
        return PlainTextResponse("OK")
    except Exception as e:
        print(f"YooKassa error: {e}")
        return PlainTextResponse("OK")

@app.get("/success")
async def payment_success():
    return HTMLResponse("<h1 style='text-align:center;margin-top:50px;color:green;'>Оплата прошла успешно! 🎉</h1><p style='text-align:center;'>Можете вернуться в MAX.</p>")

# ─────────────────────────────
# Фоновые задачи
# ─────────────────────────────
def reminders_checker():
    while True:
        try:
            now = datetime.now()
            for uid_str, user in list(user_data.items()):
                for rem in user.get("reminders", []):
                    if rem.get("sent"):
                        continue
                    try:
                        if datetime.fromisoformat(rem["datetime"]) <= now:
                            asyncio.run_coroutine_threadsafe(
                                bot.send_message(chat_id=int(uid_str), text=f"🔔 Напоминание!\n{rem['text']}"),
                                main_loop
                            )
                            mark_reminder_sent(uid_str, rem["id"])
                    except: pass
        except Exception as e:
            print(f"[REM] {e}")
        time.sleep(60)

def premium_expiration_checker():
    while True:
        now = datetime.now()
        for uid_str, user in list(user_data.items()):
            if user.get("premium") and user.get("premium_until"):
                try:
                    if now >= datetime.fromisoformat(user["premium_until"]):
                        user["premium"] = False
                        user.pop("premium_until", None)
                        save_data()
                        asyncio.run_coroutine_threadsafe(
                            bot.send_message(chat_id=int(uid_str), text="⚠️ Премиум закончился. Вернулись обычные лимиты."),
                            main_loop
                        )
                except: pass
        time.sleep(300)

@app.get("/health")
async def health():
    return {"status": "OK"}

@app.on_event("startup")
async def on_startup():
    print("Запуск бота MAX...")
    threading.Thread(target=reminders_checker, daemon=True).start()
    threading.Thread(target=premium_expiration_checker, daemon=True).start()
    print("Фоновые задачи запущены")

print("Бот готов к запуску. Ожидается MAX_BOT_TOKEN")
