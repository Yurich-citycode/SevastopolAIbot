# -*- coding: utf-8 -*-
"""
Sevastopol AI Bot — телеграм-гид по Севастополю.

Данные бот берёт из Google Sheets (SPREADSHEET_ID) и держит в памяти,
обновляя кэш в фоне каждые REFRESH_SECONDS секунд.

Настройки (токен и пр.) задаются через переменные окружения или файл .env
рядом со скриптом — см. README.md и .env.example.

Запуск:
    pip install -r requirements.txt
    python sevastopolaibot.py
"""

import asyncio
import html
import io
import json
import logging
import math
import os
import urllib.parse
from datetime import datetime

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

# ══════════════════════════════ КОНФИГУРАЦИЯ ══════════════════════════════

def _load_env(path: str = ".env") -> None:
    """Крошечный загрузчик .env (без сторонних зависимостей)."""
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except Exception as e:
        print(f"⚠️ Не удалось прочитать {path}: {e}")


_load_env()

# ⚠️ Токен НЕ хранится в коде: задай его в .env или в переменной окружения TG_TOKEN.
# Получить/перевыпустить токен: @BotFather → /mybots → API Token → Revoke/Generate.
TG_TOKEN = os.getenv("TG_TOKEN", "").strip()

# ID Google-таблицы, из которой бот тянет данные (File → Share → Publish to web
# или просто ссылка вида docs.google.com/spreadsheets/d/<ID>/edit).
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1RaHoS_8Ov-kNKSZJK015ceC6H3fsWnW-D-8Yee4ckQI").strip()

# Telegram ID владельца — кому доступна команда /admin
ADMIN_ID = int(os.getenv("ADMIN_ID", "6106999216"))

# Как часто перечитывать таблицу (секунды)
REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "600"))

# Файл для хранения XP-паспортов, рефералов и статистики между перезапусками
STATE_FILE = os.getenv("STATE_FILE", "bot_state.json")

logging.basicConfig(level=logging.INFO)

# ══════════════════════════════ КЭШ ТАБЛИЦЫ ══════════════════════════════

TABLE_CACHE = {
    "Где поесть": [],
    "Локации": [],
    "Маршруты": [],
    "События": [],
}
ANALYTICS_ROWS = []
LAST_CACHE_UPDATE = None

FOOD_CATEGORIES = ["Кофе", "Рестораны", "Кафе", "Пекарни", "Кондитерские", "Доставки"]

CAT_MAP = {
    "coffee": "Кофе",
    "rest": "Рестораны",
    "cafe": "Кафе",
    "bakery": "Пекарни",
    "sweets": "Кондитерские",
    "delivery": "Доставки",
}


def pick(row, *keys, default=""):
    """Берёт первое непустое значение из row по списку ключей-синонимов.

    Нужно потому, что в таблице колонки называются то «Время работы»,
    то «Bремя работы» (с латинской B) — поддерживаем оба варианта.
    """
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


def _download_xlsx(url: str) -> bytes:
    """Синхронная загрузка xlsx (выполняется в executor, чтобы не блокировать event loop)."""
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    content = resp.content
    # Настоящий xlsx — это zip, он начинается с "PK"
    if not content.startswith(b"PK"):
        raise ValueError(
            "Google вернул не XLSX. Проверь, что доступ к таблице открыт по ссылке "
            "(Файл → Настройки доступа → «Все, у кого есть ссылка» → Читатель)."
        )
    return content


async def refresh_cache_once():
    """Одно обновление кэша: скачиваем xlsx ОДИН раз и читаем из памяти все листы."""
    global LAST_CACHE_UPDATE
    loop = asyncio.get_running_loop()
    url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=xlsx"

    print("🔄 [КЭШ] Начинаю обновление данных из Google Sheets...")

    content = await loop.run_in_executor(None, _download_xlsx, url)
    excel_file = await loop.run_in_executor(None, pd.ExcelFile, io.BytesIO(content))
    sheet_names = [n.strip() for n in excel_file.sheet_names]
    cleaned_sheets = {n: n for n in sheet_names}

    # 1. Вкладка «Где поесть» (в Google-таблице может называться «Где поесть?»)
    food_name = next(
        (n for n in ("Где поесть?", "Где поесть") if n in cleaned_sheets),
        sheet_names[0] if sheet_names else None,
    )
    if food_name:
        df_food = await loop.run_in_executor(
            None, lambda s=food_name: pd.read_excel(excel_file, sheet_name=s).fillna("")
        )
        TABLE_CACHE["Где поесть"] = df_food.to_dict(orient="records")
        print(f"👍 [КЭШ] Вкладка '{food_name}' загружена. Строк: {len(TABLE_CACHE['Где поесть'])}")

    # 2. Остальные вкладки
    for key in ("Локации", "Маршруты", "События"):
        if key in cleaned_sheets:
            df = await loop.run_in_executor(
                None, lambda s=key: pd.read_excel(excel_file, sheet_name=s).fillna("")
            )
            TABLE_CACHE[key] = df.to_dict(orient="records")
            print(f"👍 [КЭШ] Вкладка '{key}' загружена. Строк: {len(TABLE_CACHE[key])}")
        else:
            print(f"⚠️ [КЭШ] Вкладка '{key}' не найдена в Google-таблице.")

    LAST_CACHE_UPDATE = datetime.now()
    print("✅ [КЭШ] Все данные обновлены в памяти!")


async def update_sheets_cache():
    """Фоновая задача: периодически обновляет кэш, не блокируя бота."""
    while True:
        await asyncio.sleep(REFRESH_SECONDS)
        try:
            await refresh_cache_once()
        except Exception as e:
            print(f"❌ [КЭШ] Ошибка обновления: {e}")


def get_places_from_sheet(target_name: str):
    """Мгновенная выдача из кэша в памяти."""
    if target_name in FOOD_CATEGORIES:
        filtered = [
            row
            for row in TABLE_CACHE.get("Где поесть", [])
            if str(row.get("Категория", "")).strip() == target_name
        ]
        print(f"⚡ [ПАМЯТЬ] Категория '{target_name}': {len(filtered)} мест")
        return filtered
    data = TABLE_CACHE.get(target_name, [])
    print(f"⚡ [ПАМЯТЬ] Лист '{target_name}': {len(data)} строк")
    return data


# ══════════════════════════════ СОХРАНЕНИЕ СОСТОЯНИЯ ══════════════════════

def save_state():
    """Сохраняет паспорта, рефералов и статистику в JSON-файл."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "passports": {str(k): v for k, v in PASSPORTS.items()},
                    "referrals": {str(k): v for k, v in REFERRALS.items()},
                    "analytics": ANALYTICS_ROWS[-2000:],  # держим файл компактным
                },
                f,
                ensure_ascii=False,
            )
    except Exception as e:
        print(f"⚠️ Не удалось сохранить состояние: {e}")


def load_state():
    """Восстанавливает состояние после перезапуска."""
    global ANALYTICS_ROWS
    try:
        if not os.path.exists(STATE_FILE):
            return
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        PASSPORTS.update({int(k): v for k, v in data.get("passports", {}).items()})
        REFERRALS.update({int(k): v for k, v in data.get("referrals", {}).items()})
        ANALYTICS_ROWS = data.get("analytics", [])
        print(f"📂 Восстановлено состояние: {len(PASSPORTS)} паспортов, {len(ANALYTICS_ROWS)} действий")
    except Exception as e:
        print(f"⚠️ Не удалось загрузить состояние: {e}")


# ══════════════════════════════ АНАЛИТИКА ═════════════════════════════════

def log_action(user_id, username, action):
    try:
        ANALYTICS_ROWS.append(
            {
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user_id": user_id,
                "username": username or "",
                "action": action,
            }
        )
        print(f"📊 LOG | {user_id} | {username} | {action}")
        save_state()
    except Exception as e:
        print(f"Analytics error: {e}")


# ══════════════════════════════ ПАСПОРТ / XP ═════════════════════════════

PASSPORTS = {}
REFERRALS = {}  # кто кого пригласил

def calculate_level(xp):
    return int((xp / 100) ** 0.5)


def get_rank(xp):
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


def get_progress_bar(xp):
    levels = [0, 100, 300, 800, 2000, 4000, 7000]
    for i in range(len(levels) - 1):
        if xp < levels[i + 1]:
            progress = int((xp - levels[i]) / (levels[i + 1] - levels[i]) * 10)
            return "▓" * max(0, min(10, progress)) + "░" * (10 - max(0, min(10, progress)))
    return "▓" * 10


def xp_to_next(xp):
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
    print(f"🛂 Паспорт создан: {user.full_name} (+10 XP за первый запуск)")


def get_ref_link(user_id):
    return f"https://t.me/SevastopolAIBot?start=ref_{user_id}"


async def process_referral(new_user_id, referrer_id):
    if referrer_id == new_user_id or new_user_id in REFERRALS:
        return
    REFERRALS[new_user_id] = referrer_id
    if referrer_id in PASSPORTS:
        PASSPORTS[referrer_id]["xp"] += 25
        print(f"⚡ +25 XP рефералу {referrer_id}")
    save_state()


# ══════════════════════════════ ВСПОМОГАТЕЛЬНОЕ ══════════════════════════

# Экземпляр бота создаётся в main() после проверки токена,
# иначе aiogram падает ещё на этапе импорта, не дав показать подсказку.
bot = None
dp = Dispatcher()

print("Настройки есть!")

# Реплай-клавиатура управления
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
    """Экранирует данные из таблицы для parse_mode=HTML."""
    return html.escape(str(value), quote=False)


def clean_url(value) -> str:
    """Возвращает валидный http(s)-URL или пустую строку."""
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return ""
    if not s.startswith(("http://", "https://")):
        if "." in s.split("/")[0]:
            s = "https://" + s
        else:
            return ""
    return s


def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


async def edit_or_reply_text(call: types.CallbackQuery, text: str, reply_markup):
    """Правит текстовое сообщение; если это фото — удаляет и отвечает текстом."""
    try:
        if call.message.photo:
            await call.message.delete()
            await call.message.answer(text=text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await call.message.edit_text(text=text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        # «message is not modified» и подобное — не критично
        pass


def yandex_maps_url(coords: str) -> str:
    return f"https://yandex.ru/maps/?text={coords.replace(' ', '')}"


# ══════════════════════════════ КАРУСЕЛИ ═════════════════════════════════

# 1. Карусель для ЕДЫ
def create_carousel_card(places, index: int, category_key: str):
    if not places or index < 0 or index >= len(places):
        return "Заведение не найдено", None, None

    item = places[index]
    total = len(places)

    name = pick(item, "Название", default="Без названия")
    photo_url = clean_url(pick(item, "Ссылка на фото"))
    description = pick(item, "Описание")
    address = pick(item, "Адрес", default="Адрес не указан")
    district = pick(item, "Район")
    coords = pick(item, "Координаты")
    phone = pick(item, "Телефон")
    work_time = pick(item, "Bремя работы", "Время работы")

    distance_block = ""
    if "distance" in item:
        dist = item["distance"]
        if dist < 1000:
            distance_block = f"\n📍 <b>Расстояние до вас:</b> ~{int(dist)} м"
        else:
            distance_block = f"\n📍 <b>Расстояние до вас:</b> ~{dist / 1000:.1f} км"

    address_text = f"{address} ({district})" if district else address
    if coords:
        address_block = (
            f"📍 <b>Адрес:</b> {esc(address_text)} — "
            f"<a href='{yandex_maps_url(coords)}'>🗺 Показать на карте</a>{distance_block}"
        )
    else:
        address_block = f"📍 <b>Адрес:</b> {esc(address_text)}{distance_block}"

    text = f"<b>{esc(name)}</b>\n\n{address_block}\n\n"
    if work_time:
        text += f"🕒 <b>Время работы:</b> {esc(work_time)}\n\n"
    if phone:
        text += f"📞 <b>Телефон:</b> {esc(phone)}\n\n"
    if description:
        text += f"💬 <b>О заведении:</b>\n{esc(description)}"

    inline_keyboard = []
    site_url = clean_url(pick(item, "Сайт"))
    if site_url:
        inline_keyboard.append([InlineKeyboardButton(text="🌐 Еще и сайт есть", url=site_url)])

    social_row = []
    for label, value in (
        ("👥 ВКонтакте", clean_url(pick(item, "Bконтакте", "Вконтакте"))),
        ("📱 Telegram", clean_url(pick(item, "Telegram"))),
        ("📸 Instagram", clean_url(pick(item, "Instagram"))),
    ):
        if value:
            social_row.append(InlineKeyboardButton(text=label, url=value))
    if social_row:
        inline_keyboard.append(social_row)

    # Кнопка шеринга
    share_text = f"🔥 Нашёл классное место в Севастополе: «{name}»\n\n📍 Адрес: {address_text}"
    if work_time:
        share_text += f"\n🕒 Время работы: {work_time}"
    if phone:
        share_text += f"\n📞 Телефон: {phone}"
    share_text += "\n\nСкинула Кира из Sevastopol AI: https://t.me/SevastopolAiBot"
    share_link = yandex_maps_url(coords) if coords else "https://t.me"
    share_url = (
        f"https://t.me/share/url?url={urllib.parse.quote(share_link)}"
        f"&text={urllib.parse.quote(share_text)}"
    )
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
    if category_key == "nearfood":
        inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="nearfood_back")])
    else:
        inline_keyboard.append(
            [InlineKeyboardButton(text="🔙 Вернуться к фильтрам", callback_data=f"back_to_cat_{category_key}")]
        )

    return text, InlineKeyboardMarkup(inline_keyboard=inline_keyboard), photo_url


# 2. Карусель для ЛОКАЦИЙ
def create_location_carousel(places, index: int, category_key: str):
    if not places or index < 0 or index >= len(places):
        return "Локация не найдена", None, None

    item = places[index]
    total = len(places)

    name = pick(item, "Название", default="Без названия")
    description = pick(item, "Описание")
    orientir = pick(item, "Ориентир", default="Не указан")
    coords = pick(item, "Координаты")

    text = f"📍 <b>{esc(name)}</b>\n\n🗺 <b>Ориентир:</b> {esc(orientir)}\n\n"
    if description:
        text += f"💬 <b>Описание:</b>\n{esc(description)}"

    inline_keyboard = []
    if coords:
        inline_keyboard.append(
            [InlineKeyboardButton(text="🗺 Открыть карту", url=yandex_maps_url(coords))]
        )
        inline_keyboard.append(
            [InlineKeyboardButton(text="🍔 Съестное рядом", callback_data=f"foodnear_loc_{category_key}_{index}")]
        )

    share_text = f"📍 Крутая локация в Севастополе: {name}\n\n🗺 Ориентир: {orientir}"
    share_text += "\n\nСкинула Кира из Sevastopol AI: https://t.me/SevastopolAiBot"
    share_link = yandex_maps_url(coords) if coords else "https://t.me"
    share_url = (
        f"https://t.me/share/url?url={urllib.parse.quote(share_link)}"
        f"&text={urllib.parse.quote(share_text)}"
    )
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
    inline_keyboard.append([InlineKeyboardButton(text="🔙 К категориям локаций", callback_data="loc_menu")])

    return text, InlineKeyboardMarkup(inline_keyboard=inline_keyboard), clean_url(pick(item, "Ссылка на фото"))


# 3. Карусель для МАРШРУТОВ
def create_route_carousel(places, index: int, category_key: str):
    if not places or index < 0 or index >= len(places):
        return "Маршрут не найден", None, None

    item = places[index]
    total = len(places)

    name = pick(item, "Название", default="Без названия")
    description = pick(item, "Описание")
    duration = pick(item, "Длина/Время", default="Не указано")
    difficulty = pick(item, "Сложность", default="Не указана")
    map_url = clean_url(pick(item, "Ссылка на карту"))
    coords = pick(item, "Координаты")

    text = (
        f"🗺 <b>{esc(name)}</b>\n\n"
        f"⏱ <b>Длина/Время:</b> {esc(duration)}\n"
        f"📊 <b>Сложность:</b> {esc(difficulty)}\n\n"
    )
    if description:
        text += f"📝 <b>Маршрут:</b>\n{esc(description)}"

    inline_keyboard = []
    if map_url:
        inline_keyboard.append([InlineKeyboardButton(text="🗺 Открыть карту маршрута", url=map_url)])
    if coords:
        inline_keyboard.append(
            [InlineKeyboardButton(text="🍔 Съестное рядом", callback_data=f"foodnear_rt_{category_key}_{index}")]
        )

    share_text = f"🗺 Интересный маршрут в Севастополе: {name}\n\n⏱ Длина/Время: {duration}\n📊 Сложность: {difficulty}"
    share_text += "\n\nСкинула Кира из Sevastopol AI: https://t.me/SevastopolAiBot"
    share_link = map_url or "https://t.me"
    share_url = (
        f"https://t.me/share/url?url={urllib.parse.quote(share_link)}"
        f"&text={urllib.parse.quote(share_text)}"
    )
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
    inline_keyboard.append([InlineKeyboardButton(text="🔙 К категориям маршрутов", callback_data="routes_menu")])

    return text, InlineKeyboardMarkup(inline_keyboard=inline_keyboard), clean_url(pick(item, "Ссылка на фото"))


# ══════════════════════════════ МЕНЮ ═════════════════════════════════════

def get_main_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🍽 Где поесть", callback_data="food_menu"),
                InlineKeyboardButton(text="📍 Локации", callback_data="loc_menu"),
            ],
            [
                InlineKeyboardButton(text="📅 События", callback_data="events_menu"),
                InlineKeyboardButton(text="🗺 Маршруты", callback_data="routes_menu"),
            ],
        ]
    )


async def show_food_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="☕ Кофе", callback_data="cat_coffee"),
                InlineKeyboardButton(text="🍽 Рестораны", callback_data="cat_rest"),
            ],
            [
                InlineKeyboardButton(text="🍕 Кафе", callback_data="cat_cafe"),
                InlineKeyboardButton(text="🥐 Пекарни", callback_data="cat_bakery"),
            ],
            [
                InlineKeyboardButton(text="🍰 Кондитерские", callback_data="cat_sweets"),
                InlineKeyboardButton(text="📦 Доставки", callback_data="cat_delivery"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu")],
        ]
    )
    await edit_or_reply_text(call, "Шо именно мы ищем? Выбирай категорию: 👇", kb)


async def show_locations_menu(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏖 Пляжи", callback_data="locselect_Пляжи"),
                InlineKeyboardButton(text="🔭 Смотровые", callback_data="locselect_Смотровые"),
            ],
            [
                InlineKeyboardButton(text="🌅 Закаты", callback_data="locselect_Закаты"),
                InlineKeyboardButton(text="💎 Hidden Gems", callback_data="locselect_Hidden Gems"),
            ],
            [
                InlineKeyboardButton(text="🚶 Прогулки", callback_data="locselect_Прогулки"),
                InlineKeyboardButton(text="🏛 Достопримечательности", callback_data="locselect_Достопримечательности"),
            ],
            [InlineKeyboardButton(text="🖼 Музеи", callback_data="locselect_Музеи")],
            [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="main_menu")],
        ]
    )
    await edit_or_reply_text(call, "Выбери интересующую категорию локаций: 👇", kb)
    await call.answer()


async def show_routes_menu(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🥾 Пешие", callback_data="rtselect_Пешие"),
                InlineKeyboardButton(text="🚲 Вело", callback_data="rtselect_Велосипед"),
            ],
            [
                InlineKeyboardButton(text="🚗 Авто", callback_data="rtselect_Авто"),
                InlineKeyboardButton(text="🌊 Вода", callback_data="rtselect_Вода"),
            ],
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
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="food_menu")],
        ]
    )
    await edit_or_reply_text(call, messages_map.get(category, "Выбирай вариант поиска: 👇"), kb)


def parse_event_date(raw):
    """Разбирает дату события из таблицы в любом разумном формате."""
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


async def show_events_menu(call: types.CallbackQuery):
    events_list = get_places_from_sheet("События")
    current_date = datetime.now().date()
    upcoming_events = []

    for r in events_list:
        event_date = parse_event_date(r.get("Дата"))
        if event_date and event_date >= current_date:
            upcoming_events.append((event_date, r))

    upcoming_events.sort(key=lambda x: x[0])
    upcoming_events = upcoming_events[:10]  # не заваливаем пользователя сообщениями

    if not upcoming_events:
        back_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="main_menu")]
            ]
        )
        await edit_or_reply_text(
            call, "На ближайшие дни событий не найдено. Самое время устроить чилл! 🌅", back_kb
        )
        return

    await call.message.delete()
    await call.message.answer("📅 <b>Ближайшие актуальные события Севастополя:</b>", parse_mode="HTML")

    for event_date, event in upcoming_events:
        formatted_date = event_date.strftime("%d.%m.%Y")
        text = (
            f"📅 <b>{formatted_date}</b> | 📍 <b>{esc(pick(event, 'Место', default='Локация не указана'))}</b>\n"
            f"🎭 <b>{esc(pick(event, 'Название', default='Без названия'))}</b>\n\n"
            f"{esc(pick(event, 'Описание'))}"
        )
        markup = None
        buy_url = clean_url(pick(event, "Купить"))
        if buy_url:
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🎟 Билеты / Подробнее", url=buy_url)]
                ]
            )
        photo = clean_url(pick(event, "Ссылка на афишу"))
        if photo:
            try:
                await call.message.answer_photo(photo=photo, caption=text, reply_markup=markup, parse_mode="HTML")
            except Exception:
                await call.message.answer(text=text, reply_markup=markup, parse_mode="HTML")
        else:
            await call.message.answer(text=text, reply_markup=markup, parse_mode="HTML")

    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ В главное меню", callback_data="main_menu")]]
    )
    await call.message.answer("---\n<i>Больше событий пока нет.</i>", reply_markup=back_kb, parse_mode="HTML")
    await call.answer()


# ══════════════════════════════ ЛОКАЦИИ И МАРШРУТЫ ═══════════════════════

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
    """Общая логика показа/перелистывания карточки."""
    try:
        if photo_url and call.message.photo:
            await call.message.edit_media(
                media=InputMediaPhoto(media=photo_url, caption=text, parse_mode="HTML"),
                reply_markup=markup,
            )
        else:
            await call.message.delete()
            if photo_url:
                await call.message.answer_photo(
                    photo=photo_url, caption=text, reply_markup=markup, parse_mode="HTML"
                )
            else:
                await call.message.answer(text=text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        logging.warning("Carousel update failed: %s", e)


async def show_location_page(call: types.CallbackQuery, state: FSMContext, category: str, index: int):
    state_data = await state.get_data()
    places = state_data.get("loc_places")
    if not places:
        places = [
            r
            for r in get_places_from_sheet("Локации")
            if category.lower() in str(r.get("Категория", "")).lower()
        ]
    text, markup, photo_url = create_location_carousel(places, index, category)
    await _send_carousel_page(call, text, markup, photo_url)


async def show_route_page(call: types.CallbackQuery, state: FSMContext, category: str, index: int):
    state_data = await state.get_data()
    places = state_data.get("rt_places")
    if not places:
        places = [
            r
            for r in get_places_from_sheet("Маршруты")
            if category.lower() in str(r.get("Категория", "")).lower()
        ]
    text, markup, photo_url = create_route_carousel(places, index, category)
    await _send_carousel_page(call, text, markup, photo_url)


# ══════════════════════════════ ЕДА: ФИЛЬТРЫ ═════════════════════════════

async def show_districts_menu(call: types.CallbackQuery, category: str):
    sheet_cat = CAT_MAP.get(category, "Кофе")
    places = get_places_from_sheet(sheet_cat)
    if not places:
        await call.answer("Ничего не найдено 😔", show_alert=True)
        return

    districts = {str(p.get("Район", "")).strip() for p in places if str(p.get("Район", "")).strip()}
    if not districts:
        await call.answer("В таблице не заполнены районы!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for district in sorted(districts):
        builder.button(text=district, callback_data=f"subdist_{category}_{district}")
    builder.adjust(2)
    builder.button(text="⬅️ Назад", callback_data=f"cat_{category}")
    builder.adjust(2, 1)

    await edit_or_reply_text(call, "Выбери интересующий район города: 👇", builder.as_markup())
    await call.answer()


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


async def send_card(call, text, markup, photo_url):
    await call.message.delete()
    if photo_url:
        await call.message.answer_photo(photo=photo_url, caption=text, reply_markup=markup, parse_mode="HTML")
    else:
        await call.message.answer(text=text, reply_markup=markup, parse_mode="HTML")


async def show_all_places(call: types.CallbackQuery, state: FSMContext, category: str):
    sheet_cat = CAT_MAP.get(category, "Кофе")
    places = get_places_from_sheet(sheet_cat)
    if not places:
        await call.answer("Ничего не найдено 😔", show_alert=True)
        return
    # запоминаем список в состоянии, чтобы листание не подхватило старый фильтр
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
        places = state_data.get("loc_places") or [
            r
            for r in get_places_from_sheet("Локации")
            if category.lower() in str(r.get("Категория", "")).lower()
        ]
    else:
        places = state_data.get("rt_places") or [
            r
            for r in get_places_from_sheet("Маршруты")
            if category.lower() in str(r.get("Категория", "")).lower()
        ]

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
    )
    text, markup, photo_url = create_carousel_card(nearest, 0, "nearfood")
    await send_card(call, text, markup, photo_url)


async def send_message_card(message: types.Message, text, markup, photo_url):
    if photo_url:
        await message.answer_photo(photo=photo_url, caption=text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.answer(text=text, reply_markup=markup, parse_mode="HTML")


# ══════════════════════════════ ОБРАБОТЧИК КОЛБЭКОВ ═════════════════════

@dp.callback_query()
async def callback_handler(call: types.CallbackQuery, state: FSMContext):
    try:
        await _route_callback(call, state)
    except Exception as e:
        logging.exception("Ошибка в обработчике колбэка %s: %s", call.data, e)
        try:
            await call.answer("Упс, что-то пошло не так. Попробуй ещё раз 🙏", show_alert=True)
        except Exception:
            pass
    finally:
        # всегда отвечаем на колбэк, чтобы у пользователя не висел спиннер
        try:
            await call.answer()
        except Exception:
            pass


async def _route_callback(call: types.CallbackQuery, state: FSMContext):
    data = call.data

    if data == "main_menu":
        log_action(call.from_user.id, call.from_user.username, "BTN_MAIN_MENU")
        await state.clear()
        await edit_or_reply_text(call, "Выбирай категорию:", get_main_inline_kb())

    elif data == "food_menu":
        log_action(call.from_user.id, call.from_user.username, "BTN_FOOD")
        await show_food_menu(call, state)

    elif data == "loc_menu":
        log_action(call.from_user.id, call.from_user.username, "BTN_LOCATIONS")
        await show_locations_menu(call)

    elif data == "routes_menu":
        log_action(call.from_user.id, call.from_user.username, "BTN_ROUTES")
        await show_routes_menu(call)

    elif data == "events_menu":
        log_action(call.from_user.id, call.from_user.username, "BTN_EVENTS")
        await show_events_menu(call)

    elif data == "keep_calm":
        pass  # просто гасим колбэк

    elif data == "nearfood_back":
        src = (await state.get_data()).get("nearfood_source", "loc_menu")
        if src == "routes_menu":
            await show_routes_menu(call)
        else:
            await show_locations_menu(call)

    # ЕДА
    elif data.startswith("cat_") or data.startswith("back_to_cat_"):
        await show_food_filter_menu(call, state, data.split("_")[-1])

    elif data.startswith("filter_dist_"):
        await show_districts_menu(call, data.split("_")[2])

    elif data.startswith("subdist_"):
        parts = data.split("_")
        await show_district_places(call, state, parts[1], parts[2])

    elif data.startswith("filter_near_"):
        category = data.split("_")[2]
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
        await show_all_places(call, state, data.split("_")[2])

    elif data.startswith("foodnear_"):
        parts = data.split("_")
        await show_nearby_food(call, state, parts[1], parts[2], int(parts[3]))

    elif data.startswith("page_"):
        parts = data.split("_")
        await show_food_page(call, state, parts[1], int(parts[2]))

    # ЛОКАЦИИ
    elif data.startswith("locselect_"):
        await show_location_category(call, state, data.split("_")[1])

    elif data.startswith("loc_page_"):
        parts = data.split("_")
        await show_location_page(call, state, parts[2], int(parts[3]))

    # МАРШРУТЫ
    elif data.startswith("rtselect_"):
        await show_route_category(call, state, data.split("_")[1])

    elif data.startswith("route_page_"):
        parts = data.split("_")
        await show_route_page(call, state, parts[2], int(parts[3]))


# ══════════════════════════════ ОБРАБОТЧИКИ СООБЩЕНИЙ ════════════════════

@dp.message(F.text == "🏠 Главное меню")
async def process_main_menu_btn(message: types.Message, state: FSMContext):
    log_action(message.from_user.id, message.from_user.username, "MAIN_MENU")
    await state.clear()
    await message.answer("Вы вернулись в главное меню:", reply_markup=get_main_inline_kb())


@dp.message(F.text == "💬 Связь")
async def process_contact_btn(message: types.Message):
    log_action(message.from_user.id, message.from_user.username, "CONTACT")
    await message.answer(
        "Есть вопросы, предложения или нашли ошибку?\n"
        "Напишите нам напрямую: @PavelYuRichRWA",
        parse_mode="HTML",
    )


@dp.message(F.text == "👥 Пригласить друга")
async def invite_friend(message: types.Message):
    create_passport_if_not_exists(message.from_user)
    link = get_ref_link(message.from_user.id)
    passport = PASSPORTS[message.from_user.id]
    await message.answer(
        f"🔗 <b>Твоя реферальная ссылка:</b>\n\n"
        f"<code>{esc(link)}</code>\n\n"
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
        f"До следующего уровня: {xp_to_next(passport['xp'])} XP",
        parse_mode="HTML",
    )


@dp.message(F.text == "/admin")
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    unique_users = len({row["user_id"] for row in ANALYTICS_ROWS})
    actions = {}
    for row in ANALYTICS_ROWS:
        a = row["action"]
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
    # Реферальная ссылка /start ref_<id>
    args = message.text.split() if message.text else []
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].replace("ref_", ""))
            await process_referral(message.from_user.id, referrer_id)
        except ValueError:
            pass

    create_passport_if_not_exists(message.from_user)
    log_action(message.from_user.id, message.from_user.username or "", "START")

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
        await message.answer("Ошибка получения данных 😔", reply_markup=ReplyKeyboardRemove())
        return

    places_with_distance = []
    for place in places:
        coords_str = pick(place, "Координаты")
        if not coords_str or "," not in coords_str:
            continue
        try:
            lat_str, lon_str = coords_str.split(",", 1)
            distance = calculate_distance(
                user_lat, user_lon, float(lat_str.strip()), float(lon_str.strip())
            )
        except ValueError:
            continue
        p_copy = dict(place)
        p_copy["distance"] = distance
        places_with_distance.append(p_copy)

    if not places_with_distance:
        await message.answer("Увы, не удалось рассчитать расстояние.", reply_markup=ReplyKeyboardRemove())
        return

    places_with_distance.sort(key=lambda x: x.get("distance", 999999))

    await message.answer("Секунду, ищу ближайшие...", reply_markup=ReplyKeyboardRemove())
    await state.update_data(filtered_places=places_with_distance, current_category=category)

    text, markup, photo_url = create_carousel_card(places_with_distance, 0, category)
    await send_message_card(message, text, markup, photo_url)


# ══════════════════════════════ ЗАПУСК ═══════════════════════════════════

NO_TOKEN_HELP = """
❌ Токен бота не задан!

Как задать (любой из способов):
1) Создай рядом со скриптом файл .env со строкой:
       TG_TOKEN=123456789:AAABBBCCC
   (пример — в файле .env.example)
2) Или переменная окружения:
       Windows:  set TG_TOKEN=123456789:AAABBBCCC
       Mac/Linux: export TG_TOKEN=123456789:AAABBBCCC
3) Или в Google Colab перед запуском:
       import os
       os.environ["TG_TOKEN"] = "123456789:AAABBBCCC"

Токен берётся/перевыпускается у @BotFather → /mybots → API Token.
"""


async def main():
    load_state()

    if not TG_TOKEN or "ЗАМЕНИ" in TG_TOKEN:
        print(NO_TOKEN_HELP)
        return

    global bot
    bot = Bot(token=TG_TOKEN)

    print("Вызываю первое обновление кэша таблиц...")
    try:
        await asyncio.wait_for(refresh_cache_once(), timeout=120)
    except Exception as e:
        print(f"⚠️ Не удалось загрузить таблицу при старте: {e}")
        print("   Бот всё равно стартует; кэш обновится в фоне через несколько минут.")

    # Фоновая задача обновления кэша
    asyncio.create_task(update_sheets_cache())

    print("Удаляю старые вебхуки и запускаю бота...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"❌ Не удалось подключиться к Telegram API: {e}")
        print("   Проверь токен (возможно, его перевыпустили) и доступ к api.telegram.org.")
        await bot.session.close()
        return

    print("🚀 Бот успешно запущен! Кэширование активно.")
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
