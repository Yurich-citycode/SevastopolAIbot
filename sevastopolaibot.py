# -*- coding: utf-8 -*-
"""
Sevastopol AI Bot — телеграм-гид по Севастополю.
Данные из Google Sheets, кэш в памяти, обновление в фоне.

Запуск:
    pip install -r requirements.txt
    python sevastopolaibot.py

Переменные окружения — см. .env.example
"""

import asyncio
import html
import io
import json
import logging
import math
import os
import random
import re
import sys
import urllib.parse
from datetime import datetime, timedelta

import pandas as pd
import requests
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ────────────────────── конфигурация ──────────────────────

def _load_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception as e:
        logging.warning("Не удалось прочитать %s: %s", path, e)

_load_env()

TG_TOKEN = os.getenv("TG_TOKEN", "").strip()
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1RaHoS_8Ov-kNKSZJK015ceC6H3fsWnW-D-8Yee4ckQI").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "6106999216"))
NEWS_CHANNEL_URL = os.getenv("NEWS_CHANNEL_URL", "https://t.me/Sevastopol_AI").strip()
if not NEWS_CHANNEL_URL.startswith(("http://", "https://")):
    NEWS_CHANNEL_URL = "https://t.me/Sevastopol_AI"
SUGGEST_FORM_URL = os.getenv(
    "SUGGEST_FORM_URL",
    "https://yurich-citycode.github.io/SevastopolAIbot/suggest.html",
).strip()
REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "600"))
STATE_FILE = os.getenv("STATE_FILE", "bot_state.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ────────────────────── кэш ──────────────────────

TABLE_CACHE = {"Где поесть": [], "Локации": [], "Маршруты": [], "События": []}
ANALYTICS_ROWS: list[dict] = []
LAST_CACHE_UPDATE = None
CACHE_LOCK = asyncio.Lock()

FOOD_CATEGORIES = ["Кофе", "Рестораны", "Кафе", "Пекарни", "Кондитерские", "Доставки"]
CAT_MAP = {
    "coffee": "Кофе",
    "rest": "Рестораны",
    "cafe": "Кафе",
    "bakery": "Пекарни",
    "sweets": "Кондитерские",
    "delivery": "Доставки",
}

def pick(row: dict, *keys, default: str = "") -> str:
    for k in keys:
        if k not in row:
            continue
        v = row[k]
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in ("nan", "none", "nat"):
            return s
    return default

def valid_rows(rows: list, require_date: bool = False) -> list[dict]:
    """Отбрасывает мусорные строки таблицы: пустые и без названия.

    Google-таблица легко разрастается пустыми строками (форматирование,
    «на всякий случай»), и тогда бот показывает карточку «Без названия».
    Здесь чистим кэш один раз на загрузке — дальше код работает с чистыми данными.
    """
    out: list[dict] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        if not pick(r, "Название"):
            continue
        if require_date and not pick(r, "Дата"):
            continue
        out.append(r)
    return out

def _download_xlsx(url: str) -> bytes:
    resp = requests.get(url, timeout=60, headers={"User-Agent": "SevastopolAIbot/1.0"})
    resp.raise_for_status()
    content = resp.content
    if not content.startswith(b"PK"):
        raise ValueError(
            "Google вернул не XLSX. Проверь доступ к таблице: Файл → Настройки доступа → «Все, у кого есть ссылка» → Читатель."
        )
    return content

async def refresh_cache_once():
    global LAST_CACHE_UPDATE
    loop = asyncio.get_running_loop()
    url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=xlsx"
    logger.info("🔄 Кэш: обновление из Google Sheets")
    content = await loop.run_in_executor(None, _download_xlsx, url)
    excel_file = await loop.run_in_executor(None, pd.ExcelFile, io.BytesIO(content))
    sheet_names = [n.strip() for n in excel_file.sheet_names]
    cleaned = {n: n for n in sheet_names}

    async with CACHE_LOCK:
        food_name = next((n for n in ("Где поесть?", "Где поесть") if n in cleaned), sheet_names[0] if sheet_names else None)
        if food_name:
            df = await loop.run_in_executor(None, lambda s=food_name: pd.read_excel(excel_file, sheet_name=s).fillna(""))
            rows = valid_rows(df.to_dict(orient="records"))
            TABLE_CACHE["Где поесть"] = rows
            logger.info("Кэш '%s': %d строк", food_name, len(rows))

        for key in ("Локации", "Маршруты", "События"):
            if key in cleaned:
                df = await loop.run_in_executor(None, lambda s=key: pd.read_excel(excel_file, sheet_name=s).fillna(""))
                rows = valid_rows(df.to_dict(orient="records"), require_date=(key == "События"))
                TABLE_CACHE[key] = rows
                logger.info("Кэш '%s': %d строк", key, len(rows))
            else:
                logger.warning("Кэш: вкладка '%s' не найдена", key)

        LAST_CACHE_UPDATE = datetime.now()
    logger.info("✅ Кэш обновлён")

async def update_sheets_cache():
    while True:
        await asyncio.sleep(REFRESH_SECONDS)
        try:
            await refresh_cache_once()
        except Exception as e:
            logger.error("Ошибка обновления кэша: %s", e)

def get_places_from_sheet(target_name: str) -> list[dict]:
    """Мгновенная выдача из кэша в памяти."""
    if target_name in FOOD_CATEGORIES:
        return [
            r for r in TABLE_CACHE.get("Где поесть", []) if str(r.get("Категория", "")).strip() == target_name
        ]
    return list(TABLE_CACHE.get(target_name, []))

# ────────────────────── состояние ──────────────────────

def save_state():
    """Атомарно: сначала во временный файл, потом os.replace.

    Падение посреди записи не должно превращать bot_state.json в битый файл —
    иначе при следующем старте теряются все паспорта и XP.
    """
    try:
        if len(ANALYTICS_ROWS) > 2000:      # держим файл компактным и в памяти тоже
            del ANALYTICS_ROWS[:-2000]
        payload = {
            "passports": {str(k): v for k, v in PASSPORTS.items()},
            "referrals": {str(k): v for k, v in REFERRALS.items()},
            "analytics": ANALYTICS_ROWS[-2000:],
        }
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        logger.warning("Не удалось сохранить состояние: %s", e)

def _normalize_passport(p) -> dict | None:
    """bot_state.json мог прийти из старой версии — дополняем недостающие поля."""
    if not isinstance(p, dict):
        return None
    try:
        xp = int(p.get("xp") or 0)
    except (TypeError, ValueError):
        xp = 0
    p["xp"] = max(0, xp)
    p.setdefault("name", "Гость")
    p.setdefault("username", "")
    p.setdefault("daily_xp", {})
    p.setdefault("passport_id", "CC-000000")
    return p

def load_state():
    global ANALYTICS_ROWS
    try:
        if not os.path.exists(STATE_FILE):
            return
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("ожидался объект")
        for k, v in (data.get("passports") or {}).items():
            try:
                uid = int(k)
            except (TypeError, ValueError):
                continue
            fixed = _normalize_passport(v)
            if fixed:
                PASSPORTS[uid] = fixed
        for k, v in (data.get("referrals") or {}).items():
            try:
                REFERRALS[int(k)] = v
            except (TypeError, ValueError):
                continue
        rows = data.get("analytics") or []
        ANALYTICS_ROWS = [r for r in rows if isinstance(r, dict) and "action" in r]
        logger.info("Восстановлено: %d паспортов, %d действий", len(PASSPORTS), len(ANALYTICS_ROWS))
    except Exception as e:
        logger.warning("Не удалось загрузить состояние: %s", e)

# ────────────────────── аналитика ──────────────────────

def log_action(user_id, username, action):
    try:
        ANALYTICS_ROWS.append(
            {"date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "user_id": user_id, "username": username or "", "action": action}
        )
        if len(ANALYTICS_ROWS) > 2500:
            del ANALYTICS_ROWS[:-2000]
        logger.info("LOG %s %s %s", user_id, username, action)
        save_state()
    except Exception as e:
        logger.warning("Analytics error: %s", e)

# ────────────────────── паспорт / XP ──────────────────────

PASSPORTS: dict[int, dict] = {}
REFERRALS: dict[int, dict] = {}

def calculate_level(xp: int) -> int:
    return int((xp / 100) ** 0.5)

def get_rank(xp: int) -> str:
    if xp < 100:
        return "Гость города"
    if xp < 300:
        return "Житель"
    if xp < 800:
        return "Исследователь"
    if xp < 2000:
        return "Проводник"
    if xp < 4000:
        return "Амбассадор"
    if xp < 7000:
        return "Легенда города"
    return "City Code"

def get_progress_bar(xp: int) -> str:
    levels = [0, 100, 300, 800, 2000, 4000, 7000]
    for i in range(len(levels) - 1):
        if xp < levels[i + 1]:
            progress = int((xp - levels[i]) / (levels[i + 1] - levels[i]) * 10)
            return "▓" * max(0, min(10, progress)) + "░" * (10 - max(0, min(10, progress)))
    return "▓" * 10

def xp_to_next(xp: int) -> int:
    for lvl in [100, 300, 800, 2000, 4000, 7000]:
        if xp < lvl:
            return lvl - xp
    return 0

def create_passport_if_not_exists(user):
    if user.id in PASSPORTS:
        return
    PASSPORTS[user.id] = {
        "name": user.full_name,
        "username": user.username or "",
        "xp": 10,
        "passport_id": f"CC-{str(user.id)[-6:]}",
    }
    save_state()
    logger.info("Паспорт создан: %s (+10 XP)", user.full_name)

def get_ref_link(user_id: int) -> str:
    return f"https://t.me/SevastopolAIBot?start=ref_{user_id}"

REFERRAL_XP = 25
REFERRAL_BONUS_XP = 40
REFERRAL_BONUS_DAYS = 7

async def process_referral(new_user_id: int, referrer_id: int):
    if referrer_id == new_user_id or new_user_id in REFERRALS:
        return
    REFERRALS[new_user_id] = {"referrer": referrer_id, "date": datetime.now().isoformat(), "bonus_given": False}
    if referrer_id in PASSPORTS:
        PASSPORTS[referrer_id]["xp"] += REFERRAL_XP
        logger.info("+%d XP рефералу %d", REFERRAL_XP, referrer_id)
    save_state()

async def check_referral_bonuses():
    today = datetime.now()
    for new_id, info in list(REFERRALS.items()):
        if isinstance(info, int):
            continue
        if info.get("bonus_given"):
            continue
        try:
            ref_date = datetime.fromisoformat(info["date"])
        except Exception:
            continue
        if (today - ref_date).days < REFERRAL_BONUS_DAYS:
            continue
        active = any(row.get("user_id") == new_id for row in ANALYTICS_ROWS)
        if not active:
            continue
        ref_id = info.get("referrer")
        if ref_id in PASSPORTS:
            PASSPORTS[ref_id]["xp"] += REFERRAL_BONUS_XP
            info["bonus_given"] = True
            save_state()
            logger.info("+%d XP: реферал %d активен %d+ дней", REFERRAL_BONUS_XP, new_id, REFERRAL_BONUS_DAYS)
            try:
                await bot.send_message(
                    ref_id,
                    f"🎉 Твой друг в боте уже неделю и активно гуляет по городу! Тебе начислено <b>+{REFERRAL_BONUS_XP} XP</b>.",
                    parse_mode="HTML",
                )
            except Exception:
                pass

XP_ACTIVITY_REWARDS = {
    "BTN_MAIN_MENU": 1,
    "BTN_FOOD": 3,
    "BTN_LOCATIONS": 3,
    "BTN_ROUTES": 3,
    "BTN_EVENTS": 3,
    "NEARBY_FOOD": 2,
    "GEO_FIND": 2,
    "SUGGEST_PLACE": 5,
}

def award_activity_xp(user, action: str) -> int:
    amount = XP_ACTIVITY_REWARDS.get(action)
    if amount is None:
        return 0
    create_passport_if_not_exists(user)
    passport = PASSPORTS[user.id]
    today = datetime.now().strftime("%Y-%m-%d")
    daily = passport.setdefault("daily_xp", {})
    for old_day in [d for d in list(daily.keys()) if d < today]:
        daily.pop(old_day, None)
    day_actions = daily.get(today, {})
    if action in day_actions:
        return 0
    day_actions[action] = amount
    daily[today] = day_actions
    passport["xp"] += amount
    save_state()
    logger.info("+%d XP %s (%s) → %d", amount, user.full_name, action, passport["xp"])
    return amount

def xp_today(user_id: int) -> int:
    passport = PASSPORTS.get(user_id)
    if not passport:
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(passport.get("daily_xp", {}).get(today, {}).values())

# ────────────────────── вспомогательное ──────────────────────

bot: Bot | None = None
cache_task: asyncio.Task | None = None
dp = Dispatcher()

main_reply_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🏠 Главное меню"), KeyboardButton(text="💬 Связь")],
        [KeyboardButton(text="🛂 City Passport")],
        [KeyboardButton(text="👥 Пригласить друга")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

def esc(value) -> str:
    return html.escape(str(value), quote=False)

def strip_html(text) -> str:
    return re.sub(r"<[^>]+>", "", str(text))

def clean_url(value) -> str:
    """Возвращает http(s)-URL или пустую строку."""
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return ""
    if not s.startswith(("http://", "https://")):
        if "." in s.split("/")[0]:
            s = "https://" + s
        else:
            return ""
    return s

def is_direct_image_url(url: str) -> bool:
    """True, если по ссылке лежит картинка, которую Telegram сам скачает.

    В базе часть фото указана ссылками на посты Telegram (https://t.me/...):
    это не картинка, send_photo по такой ссылке всегда падает с ошибкой 400.
    Такие карточки сразу отдаём текстом — без лишнего запроса к Telegram API.
    """
    if not url:
        return False
    host = url.split("/")[2].lower() if url.count("/") >= 2 else url.lower()
    if any(d in host for d in ("t.me", "telegram.me", "telegram.dog")):
        return False
    return True

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def parse_cat_index(data: str):
    parts = data.split("_")
    return "_".join(parts[2:-1]), int(parts[-1])

def parse_foodnear(data: str):
    parts = data.split("_")
    return parts[1], "_".join(parts[2:-1]), int(parts[-1])

async def edit_or_reply_text(call: types.CallbackQuery, text: str, reply_markup):
    msg = call.message
    try:
        if msg.photo:
            await msg.delete()
            await msg.answer(text=text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await msg.edit_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        logger.warning("edit_or_reply_text failed: %s", e)
        try:
            await msg.answer(text=strip_html(text)[:1000], reply_markup=reply_markup)
        except Exception:
            pass

def yandex_maps_url(coords: str) -> str:
    # coords "44.61, 33.52" → безопасный URL
    cleaned = coords.replace(" ", "")
    return f"https://yandex.ru/maps/?text={urllib.parse.quote(cleaned)}"

def _truncate_for_caption(text: str, limit: int = 1000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"

# Шапка колонки в Google-таблице исторически набрана с латинской «B»,
# поэтому поддерживаем оба варианта — иначе время работы/ВК пропадали бы.
WORK_TIME_KEYS = ("Время работы", "Bремя работы")
VK_KEYS = ("Вконтакте", "Bконтакте")

# Подпись к фото в Telegram — максимум 1024 символа, текст — 4096.
CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096

def fit_caption(head: str, description: str, desc_prefix: str) -> str:
    """Собирает подпись к фото так, чтобы она точно влезла в 1024 символа.

    Режем описание, а не всю карточку: адрес, часы и телефон важнее хвоста текста.
    """
    body = head + desc_prefix + esc(description) if description else head
    if len(body) <= CAPTION_LIMIT:
        return body
    budget = CAPTION_LIMIT - len(head) - len(desc_prefix) - 1
    if budget <= 30:
        return _truncate_for_caption(head, CAPTION_LIMIT)
    return head + desc_prefix + esc(description[:budget]).rstrip() + "…"

# ────────────────────── карусели ──────────────────────

def create_carousel_card(places, index: int, category_key: str):
    if not places or index < 0 or index >= len(places):
        return "Заведение не найдено", None, None
    item = places[index]
    total = len(places)
    name = pick(item, "Название", default="Без названия")
    raw_photo = clean_url(pick(item, "Ссылка на фото"))
    photo_url = raw_photo if is_direct_image_url(raw_photo) else ""
    description = pick(item, "Описание")
    address = pick(item, "Адрес", default="Адрес не указан")
    district = pick(item, "Район")
    coords = pick(item, "Координаты")
    phone = pick(item, "Телефон")
    work_time = pick(item, *WORK_TIME_KEYS)

    distance_block = ""
    if "distance" in item:
        dist = item["distance"]
        if dist < 1000:
            distance_block = f"\n📍 <b>Расстояние до вас:</b> ~{int(dist)} м"
        else:
            distance_block = f"\n📍 <b>Расстояние до вас:</b> ~{dist / 1000:.1f} км"

    address_text = f"{address} ({district})" if district else address
    if coords:
        address_block = f"📍 <b>Адрес:</b> {esc(address_text)} — <a href='{yandex_maps_url(coords)}'>🗺 Показать на карте</a>{distance_block}"
    else:
        address_block = f"📍 <b>Адрес:</b> {esc(address_text)}{distance_block}"

    head = f"<b>{esc(name)}</b>\n\n{address_block}\n\n"
    if work_time:
        head += f"🕒 <b>Время работы:</b> {esc(work_time)}\n\n"
    if phone:
        head += f"📞 <b>Телефон:</b> {esc(phone)}\n\n"

    desc_prefix = "💬 <b>О заведении:</b>\n"
    if photo_url:
        # подпись к фото — максимум 1024 символа
        text = fit_caption(head, description, desc_prefix)
    else:
        text = head + (desc_prefix + esc(description) if description else "")

    inline_keyboard = []
    site_url = clean_url(pick(item, "Сайт"))
    if site_url:
        inline_keyboard.append([InlineKeyboardButton(text="🌐 Еще и сайт есть", url=site_url)])

    social_row = []
    for label, value in (
        ("👥 ВКонтакте", clean_url(pick(item, *VK_KEYS))),
        ("📱 Telegram", clean_url(pick(item, "Telegram"))),
        ("📸 Instagram", clean_url(pick(item, "Instagram"))),
    ):
        if value:
            social_row.append(InlineKeyboardButton(text=label, url=value))
    if social_row:
        inline_keyboard.append(social_row)

    share_text = f"🔥 Нашёл классное место в Севастополе: «{name}»\n\n📍 Адрес: {address_text}"
    if work_time:
        share_text += f"\n🕒 Время работы: {work_time}"
    if phone:
        share_text += f"\n📞 Телефон: {phone}"
    share_text += "\n\nСкинула Кира из Sevastopol AI: https://t.me/SevastopolAiBot"
    share_link = yandex_maps_url(coords) if coords else "https://t.me"
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(share_link)}&text={urllib.parse.quote(share_text)}"
    inline_keyboard.append([InlineKeyboardButton(text="⭐ Сохранить / Скинуть другу", url=share_url)])

    prev_index = (index - 1) % total
    next_index = (index + 1) % total
    inline_keyboard.append(
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page_{category_key}_{prev_index}"),
            InlineKeyboardButton(text=f"🔹 {index + 1} / {total} 🔹", callback_data="keep_calm"),
            InlineKeyboardButton(text="Вперед ➡️", callback_data=f"page_{category_key}_{next_index}"),
        ]
    )
    inline_keyboard.append([InlineKeyboardButton(text="🎲 Случайное место", callback_data=f"rnd_{category_key}")])
    if category_key == "nearfood":
        inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="nearfood_back")])
    else:
        inline_keyboard.append([InlineKeyboardButton(text="🔙 Вернуться к фильтрам", callback_data=f"back_to_cat_{category_key}")])

    return text, InlineKeyboardMarkup(inline_keyboard=inline_keyboard), photo_url

def create_location_carousel(places, index: int, category_key: str):
    if not places or index < 0 or index >= len(places):
        return "Локация не найдена", None, None
    item = places[index]
    total = len(places)
    name = pick(item, "Название", default="Без названия")
    raw_photo = clean_url(pick(item, "Ссылка на фото"))
    photo_url = raw_photo if is_direct_image_url(raw_photo) else ""
    description = pick(item, "Описание")
    orientir = pick(item, "Ориентир", default="Не указан")
    coords = pick(item, "Координаты")

    head = f"📍 <b>{esc(name)}</b>\n\n🗺 <b>Ориентир:</b> {esc(orientir)}\n\n"
    desc_prefix = "💬 <b>Описание:</b>\n"
    if photo_url:
        text = fit_caption(head, description, desc_prefix)
    else:
        text = head + (desc_prefix + esc(description) if description else "")

    inline_keyboard = []
    if coords:
        inline_keyboard.append([InlineKeyboardButton(text="🗺 Открыть карту", url=yandex_maps_url(coords))])
        inline_keyboard.append([InlineKeyboardButton(text="🍔 Съестное рядом", callback_data=f"foodnear_loc_{category_key}_{index}")])

    share_text = f"📍 Крутая локация в Севастополе: {name}\n\n🗺 Ориентир: {orientir}\n\nСкинула Кира из Sevastopol AI: https://t.me/SevastopolAiBot"
    share_link = yandex_maps_url(coords) if coords else "https://t.me"
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(share_link)}&text={urllib.parse.quote(share_text)}"
    inline_keyboard.append([InlineKeyboardButton(text="⭐ Сохранить / Скинуть другу", url=share_url)])

    prev_index = (index - 1) % total
    next_index = (index + 1) % total
    inline_keyboard.append(
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"loc_page_{category_key}_{prev_index}"),
            InlineKeyboardButton(text=f"🔹 {index + 1} / {total} 🔹", callback_data="keep_calm"),
            InlineKeyboardButton(text="Вперед ➡️", callback_data=f"loc_page_{category_key}_{next_index}"),
        ]
    )
    inline_keyboard.append([InlineKeyboardButton(text="🎲 Случайная локация", callback_data=f"rnd_loc_{category_key}")])
    inline_keyboard.append([InlineKeyboardButton(text="🔙 К категориям локаций", callback_data="loc_menu")])

    return text, InlineKeyboardMarkup(inline_keyboard=inline_keyboard), photo_url

def create_route_carousel(places, index: int, category_key: str):
    if not places or index < 0 or index >= len(places):
        return "Маршрут не найден", None, None
    item = places[index]
    total = len(places)
    name = pick(item, "Название", default="Без названия")
    raw_photo = clean_url(pick(item, "Ссылка на фото"))
    photo_url = raw_photo if is_direct_image_url(raw_photo) else ""
    description = pick(item, "Описание")
    duration = pick(item, "Длина/Время", default="Не указано")
    difficulty = pick(item, "Сложность", default="Не указана")
    map_url = clean_url(pick(item, "Ссылка на карту"))
    coords = pick(item, "Координаты")

    head = f"🗺 <b>{esc(name)}</b>\n\n⏱ <b>Длина/Время:</b> {esc(duration)}\n📊 <b>Сложность:</b> {esc(difficulty)}\n\n"
    desc_prefix = "📝 <b>Маршрут:</b>\n"
    if photo_url:
        text = fit_caption(head, description, desc_prefix)
    else:
        text = head + (desc_prefix + esc(description) if description else "")

    inline_keyboard = []
    if map_url:
        inline_keyboard.append([InlineKeyboardButton(text="🗺 Открыть карту маршрута", url=map_url)])
    if coords:
        inline_keyboard.append([InlineKeyboardButton(text="🍔 Съестное рядом", callback_data=f"foodnear_rt_{category_key}_{index}")])

    share_text = f"🗺 Интересный маршрут в Севастополе: {name}\n\n⏱ Длина/Время: {duration}\n📊 Сложность: {difficulty}\n\nСкинула Кира из Sevastopol AI: https://t.me/SevastopolAiBot"
    share_link = map_url or "https://t.me"
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(share_link)}&text={urllib.parse.quote(share_text)}"
    inline_keyboard.append([InlineKeyboardButton(text="⭐ Сохранить / Скинуть другу", url=share_url)])

    prev_index = (index - 1) % total
    next_index = (index + 1) % total
    inline_keyboard.append(
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"route_page_{category_key}_{prev_index}"),
            InlineKeyboardButton(text=f"🔹 {index + 1} / {total} 🔹", callback_data="keep_calm"),
            InlineKeyboardButton(text="Вперед ➡️", callback_data=f"route_page_{category_key}_{next_index}"),
        ]
    )
    inline_keyboard.append([InlineKeyboardButton(text="🎲 Случайный маршрут", callback_data=f"rnd_rt_{category_key}")])
    inline_keyboard.append([InlineKeyboardButton(text="🔙 К категориям маршрутов", callback_data="routes_menu")])

    return text, InlineKeyboardMarkup(inline_keyboard=inline_keyboard), photo_url

# ────────────────────── меню ──────────────────────

def get_main_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🍽 Где поесть", callback_data="food_menu"), InlineKeyboardButton(text="📍 Локации", callback_data="loc_menu")],
            [InlineKeyboardButton(text="📅 События", callback_data="events_menu"), InlineKeyboardButton(text="🗺 Маршруты", callback_data="routes_menu")],
            [InlineKeyboardButton(text="📰 Новости города", url=NEWS_CHANNEL_URL)],
            [InlineKeyboardButton(text="✍️ Предложить место", url=SUGGEST_FORM_URL)],
        ]
    )

async def show_food_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="☕ Кофе", callback_data="cat_coffee"), InlineKeyboardButton(text="🍽 Рестораны", callback_data="cat_rest")],
            [InlineKeyboardButton(text="🍕 Кафе", callback_data="cat_cafe"), InlineKeyboardButton(text="🥐 Пекарни", callback_data="cat_bakery")],
            [InlineKeyboardButton(text="🍰 Кондитерские", callback_data="cat_sweets"), InlineKeyboardButton(text="📦 Доставки", callback_data="cat_delivery")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]
    )
    await edit_or_reply_text(call, "Шо именно мы ищем? Выбирай категорию: 👇", kb)

async def show_locations_menu(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏖 Пляжи", callback_data="locselect_Пляжи"), InlineKeyboardButton(text="🔭 Смотровые", callback_data="locselect_Смотровые")],
            [InlineKeyboardButton(text="🌅 Закаты", callback_data="locselect_Закаты"), InlineKeyboardButton(text="💎 Hidden Gems", callback_data="locselect_Hidden Gems")],
            [InlineKeyboardButton(text="🚶 Прогулки", callback_data="locselect_Прогулки"), InlineKeyboardButton(text="🏛 Достопримечательности", callback_data="locselect_Достопримечательности")],
            [InlineKeyboardButton(text="🖼 Музеи", callback_data="locselect_Музеи")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="main_menu")],
        ]
    )
    await edit_or_reply_text(call, "Выбери интересующую категорию локаций: 👇", kb)
    await call.answer()

async def show_routes_menu(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🥾 Пешие", callback_data="rtselect_Пешие"), InlineKeyboardButton(text="🚲 Вело", callback_data="rtselect_Велосипед")],
            [InlineKeyboardButton(text="🚗 Авто", callback_data="rtselect_Авто"), InlineKeyboardButton(text="🌊 Вода", callback_data="rtselect_Вода")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="main_menu")],
        ]
    )
    await edit_or_reply_text(call, "Выбери формат твоего трипа: 👇", kb)
    await call.answer()

async def show_food_filter_menu(call: types.CallbackQuery, state: FSMContext, category: str):
    messages_map = {
        "coffee": "Отлично, ищем лучший кофе в городе! ☕ Как тебе удобнее выбрать?",
        "rest": "Хочется изысканной кухни и классной атмосферы? 🍽 Выбирай вариант:",
        "cafe": "Ищешь уютное место посидеть и перекусить? 🍕 Как смотрим?",
        "bakery": "За свежей выпечкой и хрустящими круассанами сюда! 🥐 С чего начнем поиски?",
        "sweets": "Время побаловать себя сладеньким! 🍰 Где ищем кондитерскую?",
        "delivery": "Чилл дома, а еда сама едет к тебе? 📦 Выбирай формат:",
    }
    # сбрасываем прошлый фильтр, чтобы карусель не путалась
    await state.update_data(filtered_places=None, current_category=None)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📍 Рядом со мной", callback_data=f"filter_near_{category}")],
            [InlineKeyboardButton(text="🗺 НА РАЙОНЕ", callback_data=f"filter_dist_{category}")],
            [InlineKeyboardButton(text="📋 Все списком", callback_data=f"filter_all_{category}")],
        ]
    )
    sheet_cat = CAT_MAP.get(category, "Кофе")
    cat_places = get_places_from_sheet(sheet_cat)
    has_subs = any(str(p.get("Подкатегория", "")).strip() for p in cat_places)
    if has_subs:
        kb.inline_keyboard.append([InlineKeyboardButton(text="🏷 По подкатегории", callback_data=f"filter_sub_{category}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="food_menu")])
    await edit_or_reply_text(call, messages_map.get(category, "Выбирай вариант поиска: 👇"), kb)

def parse_event_date(raw):
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, (datetime, pd.Timestamp)):
        return raw.date()
    s = str(raw).strip()
    if s.lower() in ("none", "nan", "nat", ""):
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    for width, fmt in ((10, "%Y-%m-%d"), (10, "%d.%m.%Y")):
        try:
            return datetime.strptime(s[:width], fmt).date()
        except ValueError:
            continue
    return None

def _day_label(d):
    today = datetime.now().date()
    if d == today:
        return f"Сегодня, {d.strftime('%d.%m')}"
    if d == today + timedelta(days=1):
        return f"Завтра, {d.strftime('%d.%m')}"
    return f"{d.strftime('%A').capitalize()}, {d.strftime('%d.%m')}"

def build_events_message(events):
    header = "📅 <b>Ближайшие события Севастополя:</b>\n"
    markers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    limit = TEXT_LIMIT - 300   # запас: описание и названия бывают длинными
    parts = [header]
    used = len(header)
    rows = []
    included = 0
    for i, (event_date, event) in enumerate(events):
        name = pick(event, "Название", default="Без названия")
        place = pick(event, "Место", default="Локация не указана")
        desc = pick(event, "Описание")
        if len(desc) > 220:
            desc = desc[:219].rstrip() + "…"
        marker = markers[i] if i < len(markers) else "•"
        block = f"{marker} 📅 <b>{esc(_day_label(event_date))}</b>\n📍 <b>{esc(place)}</b>\n🎭 <b>{esc(name)}</b>"
        if desc:
            block += f"\n{esc(desc)}"
        if used + len(block) + 2 > limit:
            break
        parts.append(block)
        used += len(block) + 2
        included += 1
        buy_url = clean_url(pick(event, "Купить"))
        if buy_url:
            label = name if len(name) <= 25 else name[:24].rstrip() + "…"
            rows.append([InlineKeyboardButton(text=f"🎟 {label}", url=buy_url)])
    text = "\n\n".join(parts)
    if included < len(events):
        text += f"\n\n<i>Показаны первые {included} из {len(events)} — остальные тоже скоро 😉</i>"
    rows.append([InlineKeyboardButton(text="⬅️ В главное меню", callback_data="main_menu")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)

async def show_events_menu(call: types.CallbackQuery):
    events_list = get_places_from_sheet("События")
    current_date = datetime.now().date()
    upcoming = []
    for r in events_list:
        d = parse_event_date(r.get("Дата"))
        if d and d >= current_date:
            upcoming.append((d, r))
    upcoming.sort(key=lambda x: x[0])
    upcoming = upcoming[:10]
    if not upcoming:
        back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В главное меню", callback_data="main_menu")]])
        await edit_or_reply_text(call, "На ближайшие дни событий не найдено. Самое время устроить чилл! 🌅", back_kb)
        return
    text, markup = build_events_message(upcoming)
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer(text, reply_markup=markup, parse_mode="HTML")
    await call.answer()

# ────────────────────── локации / маршруты ──────────────────────

async def show_location_category(call: types.CallbackQuery, state: FSMContext, category: str):
    all_locations = get_places_from_sheet("Локации")
    found = [r for r in all_locations if category.lower() in str(r.get("Категория", "")).lower()]
    if not found:
        await call.answer(f"Локации из категории «{category}» пока наполняются! 🌀", show_alert=True)
        return
    await state.update_data(loc_places=found)
    text, markup, photo_url = create_location_carousel(found, 0, category)
    await send_card(call, text, markup, photo_url)

async def show_route_category(call: types.CallbackQuery, state: FSMContext, category: str):
    all_routes = get_places_from_sheet("Маршруты")
    found = [r for r in all_routes if category.lower() in str(r.get("Категория", "")).lower()]
    if not found:
        await call.answer(f"Маршруты типа «{category}» сейчас прокладываются! 🧭", show_alert=True)
        return
    await state.update_data(rt_places=found)
    text, markup, photo_url = create_route_carousel(found, 0, category)
    await send_card(call, text, markup, photo_url)

async def _send_carousel_page(call, text, markup, photo_url):
    msg = call.message
    try:
        if photo_url and msg.photo:
            await msg.edit_media(media=InputMediaPhoto(media=photo_url, caption=text, parse_mode="HTML"), reply_markup=markup)
            return
    except Exception as e:
        logger.warning("edit_media failed: %s", e)
    try:
        if photo_url:
            await msg.delete()
            await msg.answer_photo(photo=photo_url, caption=text, reply_markup=markup, parse_mode="HTML")
        elif msg.photo:
            await msg.delete()
            await msg.answer(text=text, reply_markup=markup, parse_mode="HTML")
        else:
            await msg.edit_text(text=text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.warning("Carousel update failed: %s", e)
        try:
            await msg.answer(text=strip_html(text)[:1000], reply_markup=markup)
        except Exception:
            pass

async def show_location_page(call: types.CallbackQuery, state: FSMContext, category: str, index: int):
    state_data = await state.get_data()
    places = state_data.get("loc_places") or [r for r in get_places_from_sheet("Локации") if category.lower() in str(r.get("Категория", "")).lower()]
    text, markup, photo_url = create_location_carousel(places, index, category)
    await _send_carousel_page(call, text, markup, photo_url)

async def show_route_page(call: types.CallbackQuery, state: FSMContext, category: str, index: int):
    state_data = await state.get_data()
    places = state_data.get("rt_places") or [r for r in get_places_from_sheet("Маршруты") if category.lower() in str(r.get("Категория", "")).lower()]
    text, markup, photo_url = create_route_carousel(places, index, category)
    await _send_carousel_page(call, text, markup, photo_url)

# ────────────────────── еда: фильтры ──────────────────────

def check_callback_data(data: str) -> str:
    """Telegram хранит callback_data в 64 байта: слишком длинный — режем и логируем."""
    raw = data.encode("utf-8")
    if len(raw) <= 64:
        return data
    logger.warning("callback_data длиннее 64 байт (%d): %r", len(raw), data)
    return raw[:64].decode("utf-8", errors="ignore")

async def show_districts_menu(call: types.CallbackQuery, category: str):
    sheet_cat = CAT_MAP.get(category, "Кофе")
    places = get_places_from_sheet(sheet_cat)
    if not places:
        await call.answer("Ничего не найдено 😔", show_alert=True)
        return
    districts = sorted({str(p.get("Район", "")).strip() for p in places if str(p.get("Район", "")).strip()})
    if not districts:
        await call.answer("В таблице не заполнены районы!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for district in districts:
        builder.button(text=district, callback_data=check_callback_data(f"subdist_{category}_{district}"))
    builder.adjust(2)
    builder.button(text="⬅️ Назад", callback_data=f"cat_{category}")
    builder.adjust(2, 1)
    await edit_or_reply_text(call, "Выбери интересующий район города: 👇", builder.as_markup())

async def show_district_places(call: types.CallbackQuery, state: FSMContext, category: str, district_name: str):
    sheet_cat = CAT_MAP.get(category, "Кофе")
    places = get_places_from_sheet(sheet_cat)
    filtered = [p for p in places if str(p.get("Район", "")).strip() == district_name]
    if not filtered:
        await call.answer("В этом районе нет заведений!", show_alert=True)
        return
    await state.update_data(filtered_places=filtered, current_category=category)
    text, markup, photo_url = create_carousel_card(filtered, 0, category)
    await send_card(call, text, markup, photo_url)

async def show_subcategories_menu(call: types.CallbackQuery, category: str):
    sheet_cat = CAT_MAP.get(category, "Кофе")
    places = get_places_from_sheet(sheet_cat)
    subs = sorted({str(p.get("Подкатегория", "")).strip() for p in places if str(p.get("Подкатегория", "")).strip()})
    if not subs:
        await call.answer("В этой категории пока нет подкатегорий 😔", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for sub in subs:
        builder.button(text=sub, callback_data=check_callback_data(f"subselect_{category}_{sub}"))
    builder.adjust(2)
    builder.button(text="⬅️ Назад", callback_data=f"cat_{category}")
    builder.adjust(2, 1)
    await edit_or_reply_text(call, "Выбери подкатегорию: 👇", builder.as_markup())

async def show_subcategory_places(call: types.CallbackQuery, state: FSMContext, category: str, sub: str):
    sheet_cat = CAT_MAP.get(category, "Кофе")
    places = get_places_from_sheet(sheet_cat)
    filtered = [p for p in places if str(p.get("Подкатегория", "")).strip() == sub]
    if not filtered:
        await call.answer("В этой подкатегории пока пусто 😔", show_alert=True)
        return
    await state.update_data(filtered_places=filtered, current_category=category)
    text, markup, photo_url = create_carousel_card(filtered, 0, category)
    await send_card(call, text, markup, photo_url)

async def send_card(call, text, markup, photo_url):
    try:
        if photo_url:
            await call.message.answer_photo(photo=photo_url, caption=text, reply_markup=markup, parse_mode="HTML")
        else:
            await call.message.answer(text=text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.warning("send_card photo failed (%s) — текстом", e)
        try:
            await call.message.answer(text=strip_html(text)[:1000], reply_markup=markup)
        except Exception:
            pass
    try:
        await call.message.delete()
    except Exception:
        pass

async def show_all_places(call: types.CallbackQuery, state: FSMContext, category: str):
    sheet_cat = CAT_MAP.get(category, "Кофе")
    places = get_places_from_sheet(sheet_cat)
    if not places:
        await call.answer("Ничего не найдено 😔", show_alert=True)
        return
    await state.update_data(filtered_places=places, current_category=category)
    text, markup, photo_url = create_carousel_card(places, 0, category)
    await send_card(call, text, markup, photo_url)

async def show_food_page(call: types.CallbackQuery, state: FSMContext, category: str, index: int):
    state_data = await state.get_data()
    if category == "nearfood":
        places = state_data.get("filtered_places")
    elif state_data.get("current_category") == category:
        places = state_data.get("filtered_places")
    else:
        places = get_places_from_sheet(CAT_MAP.get(category, "Кофе"))
    if not places:
        await call.answer("Список пуст, выбери категорию заново 😔", show_alert=True)
        return
    text, markup, photo_url = create_carousel_card(places, index, category)
    await _send_carousel_page(call, text, markup, photo_url)

async def show_nearby_food(call: types.CallbackQuery, state: FSMContext, place_type: str, category: str, index: int):
    state_data = await state.get_data()
    if place_type == "loc":
        places = state_data.get("loc_places") or [r for r in get_places_from_sheet("Локации") if category.lower() in str(r.get("Категория", "")).lower()]
    else:
        places = state_data.get("rt_places") or [r for r in get_places_from_sheet("Маршруты") if category.lower() in str(r.get("Категория", "")).lower()]

    if not places or index >= len(places):
        await call.answer("Место не найдено 😔", show_alert=True)
        return

    coords_str = pick(places[index], "Координаты")
    if not coords_str or "," not in coords_str:
        await call.answer("У этого места нет координат для поиска еды 😔", show_alert=True)
        return
    try:
        lat_str, lon_str = coords_str.split(",", 1)
        target_lat, target_lon = float(lat_str.strip()), float(lon_str.strip())
    except ValueError:
        await call.answer("Ошибка в координатах локации.", show_alert=True)
        return

    all_food = []
    for sheet_cat in CAT_MAP.values():
        all_food.extend(get_places_from_sheet(sheet_cat))

    places_with_distance = []
    for p in all_food:
        f_coords = pick(p, "Координаты")
        if not f_coords or "," not in f_coords:
            continue
        try:
            f_lat, f_lon = f_coords.split(",", 1)
            dist = calculate_distance(target_lat, target_lon, float(f_lat.strip()), float(f_lon.strip()))
        except ValueError:
            continue
        p_copy = dict(p)
        p_copy["distance"] = dist
        places_with_distance.append(p_copy)

    if not places_with_distance:
        await call.answer("Рядом ничего вкусного не найдено 😔", show_alert=True)
        return

    places_with_distance.sort(key=lambda x: x.get("distance", 999999))
    nearest = places_with_distance[:10]

    await state.update_data(
        filtered_places=nearest,
        current_category="nearfood",
        nearfood_source=("routes_menu" if place_type == "rt" else "loc_menu"),
        nearfood_type=place_type,
        nearfood_category=category,
        nearfood_index=index,
    )
    text, markup, photo_url = create_carousel_card(nearest, 0, "nearfood")
    await send_card(call, text, markup, photo_url)

async def _random_carousel_food(call: types.CallbackQuery, state: FSMContext, category: str):
    state_data = await state.get_data()
    if category == "nearfood":
        places = state_data.get("filtered_places")
    elif state_data.get("current_category") == category:
        places = state_data.get("filtered_places")
    else:
        places = get_places_from_sheet(CAT_MAP.get(category, "Кофе"))
    if not places:
        await call.answer("Список пуст, выбери категорию заново 😔", show_alert=True)
        return
    index = random.randint(0, len(places) - 1)
    text, markup, photo_url = create_carousel_card(places, index, category)
    await _send_carousel_page(call, text, markup, photo_url)

async def _random_carousel_location(call: types.CallbackQuery, state: FSMContext, category: str):
    state_data = await state.get_data()
    places = state_data.get("loc_places") or [r for r in get_places_from_sheet("Локации") if category.lower() in str(r.get("Категория", "")).lower()]
    if not places:
        await call.answer(f"В категории «{category}» пока пусто 😔", show_alert=True)
        return
    index = random.randint(0, len(places) - 1)
    text, markup, photo_url = create_location_carousel(places, index, category)
    await _send_carousel_page(call, text, markup, photo_url)

async def _random_carousel_route(call: types.CallbackQuery, state: FSMContext, category: str):
    state_data = await state.get_data()
    places = state_data.get("rt_places") or [r for r in get_places_from_sheet("Маршруты") if category.lower() in str(r.get("Категория", "")).lower()]
    if not places:
        await call.answer(f"Маршрутов типа «{category}» пока нет 😔", show_alert=True)
        return
    index = random.randint(0, len(places) - 1)
    text, markup, photo_url = create_route_carousel(places, index, category)
    await _send_carousel_page(call, text, markup, photo_url)

async def send_message_card(message: types.Message, text, markup, photo_url, reply_keyboard=None):
    """Карточка обычным сообщением (не колбэком) + главная клавиатура под ней."""
    try:
        if photo_url:
            await message.answer_photo(
                photo=photo_url, caption=text, reply_markup=markup, parse_mode="HTML"
            )
        else:
            await message.answer(text=text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logger.warning("send_message_card failed (%s)", e)
        try:
            await message.answer(text=strip_html(text)[:1000], reply_markup=markup)
        except Exception:
            return
    if reply_keyboard is not None:
        try:
            await message.answer("Меню:", reply_markup=reply_keyboard)
        except Exception:
            pass

# ────────────────────── предложения ──────────────────────

SUGGEST_WEB_PREFIX = "✍️ ПРЕДЛОЖЕНИЕ:"

# ────────────────────── колбэки ──────────────────────

@dp.callback_query()
async def callback_handler(call: types.CallbackQuery, state: FSMContext):
    try:
        await _route_callback(call, state)
    except Exception as e:
        logger.exception("Ошибка в колбэке %s: %s", call.data, e)
        try:
            await call.answer("Упс, что-то пошло не так. Попробуй ещё раз 🙏", show_alert=True)
        except Exception:
            pass
    finally:
        try:
            await call.answer()
        except Exception:
            pass

async def _route_callback(call: types.CallbackQuery, state: FSMContext):
    data = call.data

    if data == "main_menu":
        log_action(call.from_user.id, call.from_user.username, "BTN_MAIN_MENU")
        award_activity_xp(call.from_user, "BTN_MAIN_MENU")
        await state.clear()
        await edit_or_reply_text(call, "Выбирай категорию:", get_main_inline_kb())

    elif data == "food_menu":
        log_action(call.from_user.id, call.from_user.username, "BTN_FOOD")
        award_activity_xp(call.from_user, "BTN_FOOD")
        await show_food_menu(call, state)

    elif data == "loc_menu":
        log_action(call.from_user.id, call.from_user.username, "BTN_LOCATIONS")
        award_activity_xp(call.from_user, "BTN_LOCATIONS")
        await show_locations_menu(call)

    elif data == "routes_menu":
        log_action(call.from_user.id, call.from_user.username, "BTN_ROUTES")
        award_activity_xp(call.from_user, "BTN_ROUTES")
        await show_routes_menu(call)

    elif data == "events_menu":
        log_action(call.from_user.id, call.from_user.username, "BTN_EVENTS")
        award_activity_xp(call.from_user, "BTN_EVENTS")
        await show_events_menu(call)

    elif data == "keep_calm":
        pass

    elif data == "nearfood_back":
        state_data = await state.get_data()
        back_cat = state_data.get("nearfood_category")
        back_idx = state_data.get("nearfood_index")
        back_type = state_data.get("nearfood_type")
        if back_cat is not None and back_idx is not None:
            if back_type == "rt":
                await show_route_page(call, state, back_cat, back_idx)
            else:
                await show_location_page(call, state, back_cat, back_idx)
        else:
            src = state_data.get("nearfood_source", "loc_menu")
            if src == "routes_menu":
                await show_routes_menu(call)
            else:
                await show_locations_menu(call)

    elif data.startswith("rnd_"):
        body = data[len("rnd_") :]
        if body.startswith("loc_"):
            await _random_carousel_location(call, state, body[len("loc_") :])
        elif body.startswith("rt_"):
            await _random_carousel_route(call, state, body[len("rt_") :])
        else:
            await _random_carousel_food(call, state, body)

    elif data == "suggest_place":
        log_action(call.from_user.id, call.from_user.username, "SUGGEST_PLACE")
        try:
            await call.message.answer(
                "Форма предложений теперь живёт на странице 👇",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✍️ Открыть форму", url=SUGGEST_FORM_URL)]]),
            )
        except Exception:
            pass

    elif data == "suggest_cancel":
        try:
            await state.clear()
            await call.message.answer("Отменили ✌️ Форма предложений: " + SUGGEST_FORM_URL)
        except Exception:
            pass

    elif data.startswith("cat_") or data.startswith("back_to_cat_"):
        await show_food_filter_menu(call, state, data.split("_")[-1])

    elif data.startswith("filter_dist_"):
        await show_districts_menu(call, data.split("_", 2)[2])

    elif data.startswith("filter_sub_"):
        await show_subcategories_menu(call, data.split("_", 2)[2])

    elif data.startswith("subselect_"):
        parts = data.split("_", 2)
        await show_subcategory_places(call, state, parts[1], parts[2])

    elif data.startswith("subdist_"):
        parts = data.split("_", 2)
        await show_district_places(call, state, parts[1], parts[2])

    elif data.startswith("filter_near_"):
        category = data.split("_", 2)[2]
        await state.update_data(location_target_category=category)
        location_keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        disclaimer_text = (
            "Чтобы я нашёл заведения в шаговой доступности, нажми кнопку «📍 Отправить геопозицию» "
            "в самом низу экрана 👇\n\n"
            "⚠️ <b>Внимание:</b> если у тебя включен VPN или шалят глушилки, координаты могут знатно "
            "заглючить, а расстояния — стать космическими. Если цифры покажутся странными, не паникуй "
            "и просто используй кнопку «🗺 НА РАЙОНЕ»!"
        )
        await call.message.answer(text=disclaimer_text, reply_markup=location_keyboard, parse_mode="HTML")

    elif data.startswith("filter_all_"):
        await show_all_places(call, state, data.split("_", 2)[2])

    elif data.startswith("foodnear_"):
        place_type, category, index = parse_foodnear(data)
        award_activity_xp(call.from_user, "NEARBY_FOOD")
        await show_nearby_food(call, state, place_type, category, index)

    elif data.startswith("page_"):
        parts = data.split("_")
        await show_food_page(call, state, parts[1], int(parts[-1]))

    elif data.startswith("locselect_"):
        await show_location_category(call, state, data.split("_", 1)[1])

    elif data.startswith("loc_page_"):
        category, index = parse_cat_index(data)
        await show_location_page(call, state, category, index)

    elif data.startswith("rtselect_"):
        await show_route_category(call, state, data.split("_", 1)[1])

    elif data.startswith("route_page_"):
        category, index = parse_cat_index(data)
        await show_route_page(call, state, category, index)

# ────────────────────── сообщения ──────────────────────

@dp.message(F.text == "🏠 Главное меню")
async def process_main_menu_btn(message: types.Message, state: FSMContext):
    log_action(message.from_user.id, message.from_user.username, "MAIN_MENU")
    await state.clear()
    await message.answer("Вы вернулись в главное меню:", reply_markup=get_main_inline_kb())

@dp.message(F.text == "💬 Связь")
async def process_contact_btn(message: types.Message):
    log_action(message.from_user.id, message.from_user.username, "CONTACT")
    await message.answer("Есть вопросы, предложения или нашли ошибку?\nНапишите нам напрямую: @PavelYuRichRWA", parse_mode="HTML")

@dp.message(F.text == "👥 Пригласить друга")
async def invite_friend(message: types.Message):
    create_passport_if_not_exists(message.from_user)
    link = get_ref_link(message.from_user.id)
    passport = PASSPORTS[message.from_user.id]
    await message.answer(
        f"🔗 <b>Твоя реферальная ссылка:</b>\n\n<code>{esc(link)}</code>\n\n"
        f"Друг регистрируется по ней — ты получаешь <b>+25 XP</b>\n"
        f"Друг активен 7 дней — ещё <b>+40 XP</b>\n\n"
        f"Сейчас у тебя: ⚡ {passport['xp']} XP",
        parse_mode="HTML",
    )

@dp.message(F.text == "🛂 City Passport")
async def show_passport(message: types.Message):
    create_passport_if_not_exists(message.from_user)
    passport = PASSPORTS[message.from_user.id]
    level = calculate_level(passport["xp"])
    await message.answer(
        f"🛂 <b>CITY PASSPORT</b>\n\n"
        f"👤 {esc(passport['name'])}\n"
        f"🆔 {esc(passport['passport_id'])}\n\n"
        f"⭐ Level: {level} — {get_rank(passport['xp'])}\n"
        f"⚡ XP: {passport['xp']}\n"
        f"{get_progress_bar(passport['xp'])}\n"
        f"До следующего уровня: {xp_to_next(passport['xp'])} XP\n"
        f"📆 Сегодня за активность: +{xp_today(message.from_user.id)} XP",
        parse_mode="HTML",
    )

@dp.message(F.text == "/admin")
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    unique_users = len({row.get("user_id") for row in ANALYTICS_ROWS if row.get("user_id")})
    actions: dict[str, int] = {}
    for row in ANALYTICS_ROWS:
        a = str(row.get("action", "UNKNOWN"))
        actions[a] = actions.get(a, 0) + 1
    stats_text = (
        f"📊 Статистика\n\n"
        f"👥 Пользователей (действия): {unique_users}\n"
        f"🛂 Паспортов создано: {len(PASSPORTS)}\n"
        f"⚡ Действий: {len(ANALYTICS_ROWS)}\n"
    )
    if LAST_CACHE_UPDATE:
        stats_text += f"🔄 Кэш обновлён: {LAST_CACHE_UPDATE.strftime('%d.%m %H:%M')}\n"
    stats_text += "\n"
    if actions:
        stats_text += "🔥 Популярность:\n\n"
        for action, count in sorted(actions.items(), key=lambda x: x[1], reverse=True):
            stats_text += f"{action}: {count}\n"
    await message.answer(stats_text)

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    args = message.text.split() if message.text else []
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            await process_referral(message.from_user.id, referrer_id)
        except ValueError:
            pass
    create_passport_if_not_exists(message.from_user)
    log_action(message.from_user.id, message.from_user.username or "", "START")
    try:
        await check_referral_bonuses()
    except Exception as e:
        logger.warning("check_referral_bonuses: %s", e)

    welcome_text = (
        "Привет! Я — твой гид по Севастополю. \n"
        "Помогу найти лучшее место для еды, покажу интересные локации "
        "и расскажу, что происходит в городе. \n\n"
        "Выбирай, что тебя интересует:"
    )
    await message.answer("Панель управления загружена 👇", reply_markup=main_reply_keyboard)
    await message.answer(welcome_text, reply_markup=get_main_inline_kb())

@dp.message(F.location)
async def handle_user_location(message: types.Message, state: FSMContext):
    user_lat = message.location.latitude
    user_lon = message.location.longitude
    state_data = await state.get_data()
    category = state_data.get("location_target_category", "coffee")
    sheet_cat = CAT_MAP.get(category, "Кофе")
    places = get_places_from_sheet(sheet_cat)
    if not places:
        await message.answer("Ошибка получения данных 😔", reply_markup=main_reply_keyboard)
        return
    places_with_distance = []
    for place in places:
        coords_str = pick(place, "Координаты")
        if not coords_str or "," not in coords_str:
            continue
        try:
            lat_str, lon_str = coords_str.split(",", 1)
            distance = calculate_distance(user_lat, user_lon, float(lat_str.strip()), float(lon_str.strip()))
        except ValueError:
            continue
        p_copy = dict(place)
        p_copy["distance"] = distance
        places_with_distance.append(p_copy)

    if not places_with_distance:
        await message.answer("Увы, не удалось рассчитать расстояние.", reply_markup=main_reply_keyboard)
        return

    places_with_distance.sort(key=lambda x: x.get("distance", 999999))
    award_activity_xp(message.from_user, "GEO_FIND")
    await message.answer("Секунду, ищу ближайшие...", reply_markup=ReplyKeyboardRemove())
    await state.update_data(filtered_places=places_with_distance, current_category=category)
    text, markup, photo_url = create_carousel_card(places_with_distance, 0, category)
    # главная клавиатура возвращается вместе с карточкой —
    # иначе после «Рядом со мной» кнопки меню пропадали бы навсегда
    await send_message_card(message, text, markup, photo_url, reply_keyboard=main_reply_keyboard)

@dp.message()
async def fallback_message(message: types.Message, state: FSMContext):
    text = (message.text or "").strip()
    if text.startswith(SUGGEST_WEB_PREFIX):
        user = message.from_user
        create_passport_if_not_exists(user)
        await state.clear()
        award_activity_xp(user, "SUGGEST_PLACE")
        log_action(user.id, user.username or "", "SUGGEST_WEB_SUBMIT")
        try:
            await message.copy_to(chat_id=ADMIN_ID)
        except Exception as e:
            logger.warning("Не удалось переслать веб-предложение: %s", e)
        await message.answer("Спасибо! 🙌 Передала владельцу бота — проверим и добавим место в базу.")
        return
    await message.answer("Я понимаю только кнопки 🙂 Нажми «🏠 Главное меню» ниже — и покажу город.", reply_markup=get_main_inline_kb())

# ────────────────────── запуск ──────────────────────

NO_TOKEN_HELP = """
❌ Токен бота не задан!

1) Создай рядом со скриптом файл .env со строкой:
       TG_TOKEN=123456789:AAABBBCCC
   (пример — в .env.example)
2) Или переменная окружения:
       export TG_TOKEN=123456789:AAABBBCCC
3) Или в Google Colab:
       import os
       os.environ["TG_TOKEN"] = "123456789:AAABBBCCC"

Токен: @BotFather → /mybots → API Token.
"""

async def main():
    load_state()
    if not TG_TOKEN or "ЗАМЕНИ" in TG_TOKEN:
        print(NO_TOKEN_HELP, flush=True)
        sys.exit(2)
    global bot
    bot = Bot(token=TG_TOKEN)
    logger.info("Первое обновление кэша таблиц...")
    try:
        await asyncio.wait_for(refresh_cache_once(), timeout=120)
    except Exception as e:
        logger.warning("Не удалось загрузить таблицу при старте: %s", e)
        logger.info("Бот стартует, кэш обновится в фоне")

    global cache_task
    cache_task = asyncio.create_task(update_sheets_cache())
    logger.info("Удаляю вебхуки и запускаю бота...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print("\n" + "!"*70, flush=True)
        print("❌ БОТ НЕ ЗАПУСТИЛСЯ: Telegram API не принял подключение.", flush=True)
        print(f"   Причина: {e}", flush=True)
        print("   Чаще всего: токен отозван/неверен (401) — перевыпусти у @BotFather,", flush=True)
        print("   либо нет доступа к api.telegram.org, либо бот уже запущен", flush=True)
        print("   в другом месте с этим же токеном.", flush=True)
        print("!"*70 + "\n", flush=True)
        logger.error("Не удалось подключиться к Telegram API: %s", e)
        await bot.session.close()
        sys.exit(1)
    logger.info("🚀 Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        save_state()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
