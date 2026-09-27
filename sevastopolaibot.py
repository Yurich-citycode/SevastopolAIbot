# -*- coding: utf-8 -*-
"""Sevastopol AI Bot — телеграм-гид по Севастополю. Данные из Google Sheets, кэш в памяти."""

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
from pathlib import Path

import pandas as pd
import requests
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart
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
from dotenv import load_dotenv

# ────────────────────── конфигурация ──────────────────────

BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_SPREADSHEET_ID = "1RaHoS_8Ov-kNKSZJK015ceC6H3fsWnW-D-8Yee4ckQI"
DEFAULT_NEWS_CHANNEL_URL = "https://t.me/Sevastopol_AI"
DEFAULT_SUGGEST_FORM_URL = "https://yurich-citycode.github.io/SevastopolAIbot/suggest.html"


def load_env() -> None:
    for candidate in (os.getenv("ENV_FILE"), BASE_DIR / ".env", Path.cwd() / ".env"):
        if candidate:
            load_dotenv(candidate)


def env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def env_int(name: str, default: int | None = None) -> int | None:
    raw = env_str(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r не число — беру %s", name, raw, default)
        return default


load_env()

TG_TOKEN = env_str("TG_TOKEN") or env_str("BOT_TOKEN")
SPREADSHEET_ID = env_str("SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID)
ADMIN_ID = env_int("ADMIN_ID")
NEWS_CHANNEL_URL = env_str("NEWS_CHANNEL_URL", DEFAULT_NEWS_CHANNEL_URL)
if not NEWS_CHANNEL_URL.startswith(("http://", "https://")):
    NEWS_CHANNEL_URL = DEFAULT_NEWS_CHANNEL_URL
SUGGEST_FORM_URL = env_str("SUGGEST_FORM_URL", DEFAULT_SUGGEST_FORM_URL)
REFRESH_SECONDS = env_int("REFRESH_SECONDS", 600)
STATE_FILE = env_str("STATE_FILE", "bot_state.json")

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
    try:
        sheets = {name.strip(): name for name in excel_file.sheet_names}

        async with CACHE_LOCK:
            food_key = next((n for n in ("Где поесть?", "Где поесть") if n in sheets), next(iter(sheets), None))
            if food_key:
                df = await loop.run_in_executor(None, lambda s=sheets[food_key]: pd.read_excel(excel_file, sheet_name=s).fillna(""))
                rows = valid_rows(df.to_dict(orient="records"))
                TABLE_CACHE["Где поесть"] = rows
                logger.info("Кэш '%s': %d строк", food_key, len(rows))

            for key in ("Локации", "Маршруты", "События"):
                if key in sheets:
                    df = await loop.run_in_executor(None, lambda s=sheets[key]: pd.read_excel(excel_file, sheet_name=s).fillna(""))
                    rows = valid_rows(df.to_dict(orient="records"), require_date=(key == "События"))
                    TABLE_CACHE[key] = rows
                    logger.info("Кэш '%s': %d строк", key, len(rows))
                else:
                    logger.warning("Кэш: вкладка '%s' не найдена", key)

            LAST_CACHE_UPDATE = datetime.now()
        logger.info("✅ Кэш обновлён")
    finally:
        await loop.run_in_executor(None, excel_file.close)


async def update_sheets_cache():
    while True:
        await asyncio.sleep(REFRESH_SECONDS)
        try:
            await refresh_cache_once()
        except Exception as e:
            logger.error("Ошибка обновления кэша: %s", e)


def get_places_from_sheet(target_name: str) -> list[dict]:
    if target_name in FOOD_CATEGORIES:
        return [
            r for r in TABLE_CACHE.get("Где поесть", []) if str(r.get("Категория", "")).strip() == target_name
        ]
    return list(TABLE_CACHE.get(target_name, []))


# ────────────────────── состояние ──────────────────────

def save_state():
    try:
        if len(ANALYTICS_ROWS) > 2000:
            del ANALYTICS_ROWS[:-2000]
        payload = {
            "passports": {str(k): v for k, v in PASSPORTS.items()},
            "referrals": {str(k): v for k, v in REFERRALS.items()},
            "analytics": ANALYTICS_ROWS,
        }
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
        if os.name == "posix":
            os.chmod(STATE_FILE, 0o600)
    except Exception as e:
        logger.warning("Не удалось сохранить состояние: %s", e)


def migrate_passport(p: dict) -> dict:
    """Гарантирует полную схему паспорта: старые паспорта дополняются дефолтами."""
    try:
        xp = int(p.get("xp") or 0)
    except (TypeError, ValueError):
        xp = 0
    p["xp"] = max(0, xp)
    p.setdefault("name", "Гость")
    p.setdefault("username", "")
    p.setdefault("passport_id", "CC-000000")
    p.setdefault("daily_xp", {})  # {YYYY-MM-DD: {action: amount}} — кнопки, 1 раз в день
    p.setdefault("status", "GUEST")  # GUEST | MEMBER | PARTNER
    p.setdefault("member_source", None)  # None | paid | xp_grant | partner | mixed
    p.setdefault("member_until", None)  # isoformat или None
    p.setdefault("complimentary_granted", False)
    p.setdefault("complimentary_claimed", False)
    p.setdefault("complimentary_granted_at", None)
    p.setdefault("complimentary_claimed_at", None)
    p.setdefault("club_applied_at", None)
    p.setdefault("partner", False)
    p.setdefault("partner_nodes", [])  # [{node_id, connected_at, last_alive_award}]
    p.setdefault("checkins", [])  # [{event_id, ts}]
    p.setdefault("accepted_places", 0)
    p.setdefault("paid_member_referrals", 0)
    p.setdefault("xp_log", [])  # короткие записи, режем до 50
    p.setdefault("xp_revoked", [])  # [{ts, amount, reason}]
    p.setdefault("verified_once", [])  # одноразовые verified-действия
    p.setdefault("verified_daily", {})  # {YYYY-MM-DD: {action: count}} — свои лимиты verified
    p.setdefault("verified_last", {})  # {action: iso_ts} — кулдауны (месяц/год)
    p.setdefault("xp_reserve", 0)  # резерв под косметическое сжигание, в v1 не тратим
    p.setdefault("created_at", datetime.now().isoformat())
    return p


def _normalize_passport(p) -> dict | None:
    if not isinstance(p, dict):
        return None
    return migrate_passport(p)


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


def warn_insecure_files():
    if os.name != "posix":
        return
    candidates = [BASE_DIR / ".env", Path.cwd() / ".env", Path(STATE_FILE)]
    env_file = os.getenv("ENV_FILE")
    if env_file:
        candidates.append(Path(env_file))
    for path in dict.fromkeys(candidates):
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            continue
        if mode & 0o077:
            logger.warning("%s: права %03o — рекомендую chmod 600", path, mode)


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

XP_LEVELS = (100, 300, 800, 2000, 4000, 7000)

XP_RANKS = (
    (100, "Гость города"),
    (300, "Житель"),
    (800, "Исследователь"),
    (2000, "Проводник"),
    (4000, "Амбассадор"),
    (7000, "Легенда города"),
)


def calculate_level(xp: int) -> int:
    """Числовой уровень 0..6, выровнен с сеткой рангов (а не формула √)."""
    level = 0
    for threshold in XP_LEVELS:
        if xp >= threshold:
            level += 1
    return level


def get_rank(xp: int) -> str:
    for threshold, rank in XP_RANKS:
        if xp < threshold:
            return rank
    return "City Code"


def get_progress_bar(xp: int) -> str:
    previous = 0
    for threshold in XP_LEVELS:
        if xp < threshold:
            progress = max(0, min(10, int((xp - previous) / (threshold - previous) * 10)))
            return "▓" * progress + "░" * (10 - progress)
        previous = threshold
    return "▓" * 10


def xp_to_next(xp: int) -> int:
    for threshold in XP_LEVELS:
        if xp < threshold:
            return threshold - xp
    return 0


# ────────────────────── City Code: грант и членство ──────────────────────
# Членство ≠ ранг. Ранг считается из XP и не продаётся.
# Оплата клуба не требует 7000 XP. 7000 XP открывает грант: 180 дней без оплаты.

CITYCODE_GRANT_XP = 7000
CITYCODE_GRANT_DAYS = 180

CITYCODE_GRANT_TEXT = (
    "🔑 <b>Ранг City Code.</b> Ты год вёл город в боте.\n"
    "Можно войти в City Code без оплаты на 6 месяцев.\n"
    "Это не скидка и не токен. Это ключ за работу с городом."
)


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _log_xp(passport: dict, action: str, amount: int, actor: str = "system", meta=None):
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), "action": action, "amount": int(amount), "actor": actor}
    if meta:
        entry["meta"] = meta
    log = passport.setdefault("xp_log", [])
    log.append(entry)
    if len(log) > 50:
        del log[:-50]


def maybe_unlock_citycode_grant(user_id: int) -> bool:
    """Вызывать после любого начисления. Первый переход через 7000 XP открывает грант.

    Повторно грант не выдаётся, даже если XP потом упал и снова вырос."""
    passport = PASSPORTS.get(user_id)
    if not passport:
        return False
    migrate_passport(passport)
    if passport["complimentary_granted"]:
        return False
    if passport["xp"] < CITYCODE_GRANT_XP:
        return False
    passport["complimentary_granted"] = True
    passport["complimentary_granted_at"] = datetime.now().isoformat()
    _log_xp(passport, "CITYCODE_GRANT_UNLOCKED", 0)
    save_state()
    logger.info("Ранг City Code: %s достиг %d XP — открыт грант на %d дней", user_id, CITYCODE_GRANT_XP, CITYCODE_GRANT_DAYS)
    _notify_citycode_grant(user_id)
    return True


def _notify_citycode_grant(user_id: int):
    """Мягкое уведомление о гранте: членство молча не включаем, нужна кнопка."""
    if bot is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔑 Активировать 6 месяцев City Code", callback_data="claim_citycode")]]
    )

    async def _send():
        try:
            await bot.send_message(user_id, CITYCODE_GRANT_TEXT, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logger.warning("Не удалось уведомить о гранте %s: %s", user_id, e)

    loop.create_task(_send())


def claim_citycode_grant(user) -> tuple[bool, str]:
    """Активация гранта пользователем. Возвращает (ok, message)."""
    user_id = user.id if hasattr(user, "id") else int(user)
    passport = PASSPORTS.get(user_id)
    if not passport:
        return False, "Паспорт не найден. Нажми /start — и он появится."
    migrate_passport(passport)
    if not passport["complimentary_granted"]:
        return False, f"Грант ещё не открыт. Ранг City Code — это {CITYCODE_GRANT_XP} XP."
    if passport["complimentary_claimed"]:
        return False, "Грант уже активирован. Второй раз он не выдаётся."
    now = datetime.now()
    until = _parse_dt(passport.get("member_until"))
    if until and until > now:
        # Уже оплаченный MEMBER: оплату не сбрасываем, добавляем 180 дней к текущему сроку
        new_until = until + timedelta(days=CITYCODE_GRANT_DAYS)
        if passport.get("member_source") and passport["member_source"] != "xp_grant":
            passport["member_source"] = "mixed"
        else:
            passport["member_source"] = "xp_grant"
    else:
        new_until = now + timedelta(days=CITYCODE_GRANT_DAYS)
        passport["member_source"] = "xp_grant"
    passport["member_until"] = new_until.isoformat()
    if passport.get("status") != "PARTNER":
        passport["status"] = "MEMBER"
    passport["complimentary_claimed"] = True
    passport["complimentary_claimed_at"] = now.isoformat()
    _log_xp(passport, "CITYCODE_GRANT_CLAIMED", 0, actor="user")
    save_state()
    logger.info("Грант City Code активирован: %s, членство до %s", user_id, new_until.date())
    return True, (
        f"🔑 City Code открыт. Членство до {new_until.strftime('%Y-%m-%d')}.\n"
        "Это ключ за работу с городом, не покупка."
    )


def is_member_active(user_id: int) -> bool:
    passport = PASSPORTS.get(user_id)
    if not passport:
        return False
    until = _parse_dt(passport.get("member_until"))
    return bool(until and until > datetime.now())


def expire_memberships():
    """Срок вышел и нет partner → статус обратно в GUEST. Ранг (XP) не трогаем."""
    now = datetime.now()
    changed = False
    for uid, passport in PASSPORTS.items():
        if passport.get("status") != "MEMBER":
            continue
        if passport.get("partner"):
            continue
        until = _parse_dt(passport.get("member_until"))
        if until and until > now:
            continue
        passport["status"] = "GUEST"
        changed = True
        logger.info("Членство истекло: %s — статус снова GUEST, ранг не тронут", uid)
    if changed:
        save_state()


def set_member(user_id: int, days: int, source: str = "paid") -> bool:
    """Ручное включение/продление членства (оплата, партнёрство). Ранг не трогаем."""
    passport = PASSPORTS.get(user_id)
    if not passport:
        return False
    migrate_passport(passport)
    now = datetime.now()
    until = _parse_dt(passport.get("member_until"))
    base = until if until and until > now else now
    passport["member_until"] = (base + timedelta(days=int(days))).isoformat()
    if source == "partner":
        passport["partner"] = True
        passport["status"] = "PARTNER"
    elif passport.get("status") != "PARTNER":
        passport["status"] = "MEMBER"
    current = passport.get("member_source")
    passport["member_source"] = source if current in (None, source) else "mixed"
    save_state()
    logger.info("Членство: %s +%s дней (source=%s) до %s", user_id, days, source, passport["member_until"])
    return True


def revoke_xp(user_id: int, amount: int, reason: str) -> bool:
    """Антифарм: админ снимает XP. Пишем в passport['xp_revoked']."""
    passport = PASSPORTS.get(user_id)
    if not passport:
        return False
    migrate_passport(passport)
    amount = max(0, int(amount))
    passport["xp"] = max(0, passport["xp"] - amount)
    passport["xp_revoked"].append({"ts": datetime.now().isoformat(), "amount": amount, "reason": reason})
    _log_xp(passport, "XP_REVOKED", -amount, actor="admin", meta={"reason": reason})
    save_state()
    logger.info("Снято %d XP у %s: %s", amount, user_id, reason)
    return True


def create_passport_if_not_exists(user):
    if user.id in PASSPORTS:
        migrate_passport(PASSPORTS[user.id])
        return
    passport = migrate_passport(
        {
            "name": user.full_name,
            "username": user.username or "",
            "xp": 10,
            "passport_id": f"CC-{str(user.id)[-6:]}",
        }
    )
    _log_xp(passport, "PASSPORT_CREATED", 10)
    PASSPORTS[user.id] = passport
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
        _log_xp(migrate_passport(PASSPORTS[referrer_id]), "REFERRAL_JOIN", REFERRAL_XP)
        maybe_unlock_citycode_grant(referrer_id)
        logger.info("+%d XP рефералу %d", REFERRAL_XP, referrer_id)
    save_state()


# Кнопки меню бонусом за «живость» реферала не считаются
REFERRAL_MENU_ACTIONS = {"BTN_MAIN_MENU", "MAIN_MENU"}


def referral_activity_ok(new_id: int, ref_date: datetime) -> bool:
    """Антифарм: бонус +40 только если у реферала за первые 7 дней есть
    активность минимум в 3 разных календарных дня и не только кнопка меню."""
    window_end = ref_date + timedelta(days=REFERRAL_BONUS_DAYS)
    days: set[str] = set()
    has_real_action = False
    for row in ANALYTICS_ROWS:
        if row.get("user_id") != new_id:
            continue
        try:
            ts = datetime.strptime(str(row.get("date", "")), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if not (ref_date <= ts <= window_end):
            continue
        days.add(ts.strftime("%Y-%m-%d"))
        if str(row.get("action", "")) not in REFERRAL_MENU_ACTIONS:
            has_real_action = True
    return len(days) >= 3 and has_real_action


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
        if not referral_activity_ok(new_id, ref_date):
            logger.info("Реферал %d не прошёл антифарм: бонус +%d не выдан", new_id, REFERRAL_BONUS_XP)
            continue
        ref_id = info.get("referrer")
        if ref_id in PASSPORTS:
            PASSPORTS[ref_id]["xp"] += REFERRAL_BONUS_XP
            _log_xp(migrate_passport(PASSPORTS[ref_id]), "REFERRAL_ALIVE_7D", REFERRAL_BONUS_XP)
            info["bonus_given"] = True
            maybe_unlock_citycode_grant(ref_id)
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
    maybe_unlock_citycode_grant(user.id)
    save_state()
    logger.info("+%d XP %s (%s) → %d", amount, user.full_name, action, passport["xp"])
    return amount


def xp_today(user_id: int) -> int:
    passport = PASSPORTS.get(user_id)
    if not passport:
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(passport.get("daily_xp", {}).get(today, {}).values())


# ────────────────────── verified XP: подтверждённые действия ──────────────────────
# Эти действия НЕ сидят в дневном лимите кнопок, но имеют свои лимиты.
# Крупные начисления — только за подтверждённые (модерация/админ) действия.
# XP не конвертируется в рубли, долю, ЦФА или скидку партнёра.

XP_VERIFIED_REWARDS = {
    # Слой города / UGC (сырой саджест SUGGEST_PLACE=5 живёт в XP_ACTIVITY_REWARDS, 1/день)
    "PLACE_ACCEPTED": 40,  # за место, после модерации
    "PLACE_FIX_ACCEPTED": 15,  # правка фото/координат, max 3/день
    "ROUTE_ACCEPTED": 70,  # за принятый маршрут
    "REVIEW_ACCEPTED": 10,  # отзыв с фактом, max 2/день
    # Слой City Code
    "CLUB_APPLY": 20,  # 1 раз, заявка отправлена
    "CLUB_PAID_MONTH": 80,  # за оплаченный цикл
    "CLUB_PAID_YEAR": 500,  # 1/год
    "EVENT_CHECKIN": 60,  # 1/событие, только чекин хостом
    "MEMBER_REFERRAL_PAID": 120,  # привёл человека, который оплатил клуб
    "PARTNER_NODE_CONNECTED": 200,  # 1 раз на точку, админ подтвердил
    "PARTNER_NODE_30D": 80,  # раз в 30 дней, если узел жив
    # Слой курса
    "BOOK_PURCHASED": 60,  # 1 раз
    # Слой ЦФА — только админ/ручной вызов, суммы в паспорте не светим
    "CFA_CALL": 30,
    "CFA_REVIEW_PAID": 200,
    "CFA_ISSUED": 800,
    "CFA_COUPON_PAID": 100,
}

VERIFIED_DAILY_LIMITS = {"PLACE_FIX_ACCEPTED": 3, "REVIEW_ACCEPTED": 2}
VERIFIED_ONCE_ACTIONS = {"CLUB_APPLY", "BOOK_PURCHASED"}
VERIFIED_COOLDOWN_DAYS = {"CLUB_PAID_MONTH": 28, "CLUB_PAID_YEAR": 365}
CFA_ACTIONS = {"CFA_CALL", "CFA_REVIEW_PAID", "CFA_ISSUED", "CFA_COUPON_PAID"}


def _verified_cooldown_ok(passport: dict, action: str, days: int) -> bool:
    last = passport.setdefault("verified_last", {}).get(action)
    if last:
        parsed = _parse_dt(last)
        if parsed and (datetime.now() - parsed).days < days:
            return False
    passport["verified_last"][action] = datetime.now().isoformat()
    return True


def award_verified_xp(user, action: str, *, actor: str = "system", meta=None) -> int:
    """Начисление за подтверждённые действия (модерация, оплата, чекин, узлы).

    `user` — объект с .id (создаём паспорт при необходимости) или голый user_id
    (паспорт должен уже существовать). Возвращает начисленную сумму (0 = отказ)."""
    amount = XP_VERIFIED_REWARDS.get(action)
    if amount is None:
        logger.warning("Неизвестное verified-действие: %s", action)
        return 0
    meta = meta or {}
    if action in CFA_ACTIONS and actor != "admin":
        logger.warning("ЦФА-действие %s начисляет только админ", action)
        return 0
    if hasattr(user, "id"):
        create_passport_if_not_exists(user)
        user_id = user.id
    else:
        user_id = int(user)
    passport = PASSPORTS.get(user_id)
    if not passport:
        logger.warning("Паспорта %s нет — XP за %s не начислен", user_id, action)
        return 0
    migrate_passport(passport)
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    # одноразовые действия
    if action in VERIFIED_ONCE_ACTIONS and action in passport["verified_once"]:
        logger.info("Действие %s у %s уже было — повторно не начисляем", action, user_id)
        return 0
    # свои дневные лимиты (не общий лимит кнопок)
    daily_limit = VERIFIED_DAILY_LIMITS.get(action)
    vdaily = passport["verified_daily"]
    for old_day in [d for d in list(vdaily.keys()) if d < today]:
        vdaily.pop(old_day, None)
    if daily_limit is not None and vdaily.get(today, {}).get(action, 0) >= daily_limit:
        logger.info("Лимит %s/день по %s у %s исчерпан", daily_limit, action, user_id)
        return 0
    # кулдауны: оплаченный цикл / год
    cooldown = VERIFIED_COOLDOWN_DAYS.get(action)
    if cooldown is not None and not _verified_cooldown_ok(passport, action, cooldown):
        logger.info("Кулдаун по %s у %s ещё не прошёл", action, user_id)
        return 0
    # чекин: одно событие — один раз, только чекин хостом
    if action == "EVENT_CHECKIN":
        event_id = str(meta.get("event_id") or "").strip()
        if not event_id:
            logger.info("EVENT_CHECKIN без event_id — 0")
            return 0
        if any(c.get("event_id") == event_id for c in passport["checkins"]):
            return 0
        passport["checkins"].append({"event_id": event_id, "ts": now.isoformat()})
    # партнёрский узел: 1 раз на точку
    if action == "PARTNER_NODE_CONNECTED":
        node_id = str(meta.get("node_id") or "").strip()
        if not node_id:
            logger.info("PARTNER_NODE_CONNECTED без node_id — 0")
            return 0
        if any(n.get("node_id") == node_id for n in passport["partner_nodes"]):
            return 0
        passport["partner_nodes"].append({"node_id": node_id, "connected_at": now.isoformat(), "last_alive_award": None})
        passport["partner"] = True
        passport["status"] = "PARTNER"
    # живой узел: раз в 30 дней на точку
    if action == "PARTNER_NODE_30D":
        node_id = str(meta.get("node_id") or "").strip()
        node = next((n for n in passport["partner_nodes"] if n.get("node_id") == node_id), None)
        if node is None:
            logger.info("PARTNER_NODE_30D: узел %s не подключён — 0", node_id)
            return 0
        # отсчёт с последней награды, а если её не было — с подключения узла
        last = _parse_dt(node.get("last_alive_award")) or _parse_dt(node.get("connected_at"))
        if last and (now - last).days < 30:
            return 0
        node["last_alive_award"] = now.isoformat()

    if action == "CLUB_APPLY":
        passport["club_applied_at"] = now.isoformat()
    if action == "PLACE_ACCEPTED":
        passport["accepted_places"] = int(passport.get("accepted_places") or 0) + 1
    if action == "MEMBER_REFERRAL_PAID":
        passport["paid_member_referrals"] = int(passport.get("paid_member_referrals") or 0) + 1

    if action in VERIFIED_ONCE_ACTIONS:
        passport["verified_once"].append(action)
    if daily_limit is not None:
        day = vdaily.setdefault(today, {})
        day[action] = day.get(action, 0) + 1

    passport["xp"] += amount
    _log_xp(passport, action, amount, actor=actor, meta=meta or None)
    maybe_unlock_citycode_grant(user_id)
    save_state()
    logger.info("+%d XP (verified %s, actor=%s) → %d у %s", amount, action, actor, passport["xp"], user_id)
    return amount


def handle_book_purchased(user_id: int) -> int:
    """Хук слоя курса. Вызовов из хаба пока нет — оставлен как точка интеграции."""
    return award_verified_xp(user_id, "BOOK_PURCHASED", actor="system")


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
    return f"https://yandex.ru/maps/?text={urllib.parse.quote(coords.replace(' ', ''))}"


def _truncate_for_caption(text: str, limit: int = 1000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


WORK_TIME_KEYS = ("Время работы", "Bремя работы")
VK_KEYS = ("Вконтакте", "Bконтакте")

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096


def fit_caption(head: str, description: str, desc_prefix: str) -> str:
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
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
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
    limit = TEXT_LIMIT - 300
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


def is_admin(user_id) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


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

    elif data == "claim_citycode":
        ok, msg_text = claim_citycode_grant(call.from_user)
        try:
            await call.message.answer(msg_text, parse_mode="HTML")
        except Exception:
            pass
        log_action(call.from_user.id, call.from_user.username, "CITYCODE_GRANT_CLAIM" if ok else "CITYCODE_GRANT_DENIED")

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
        body = data[len("rnd_"):]
        if body.startswith("loc_"):
            await _random_carousel_location(call, state, body[len("loc_"):])
        elif body.startswith("rt_"):
            await _random_carousel_route(call, state, body[len("rt_"):])
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
        f"Друг регистрируется по ней — ты получаешь <b>+{REFERRAL_XP} XP</b>\n"
        f"Друг активен {REFERRAL_BONUS_DAYS} дней — ещё <b>+{REFERRAL_BONUS_XP} XP</b>\n\n"
        f"Сейчас у тебя: ⚡ {passport['xp']} XP",
        parse_mode="HTML",
    )


def build_passport_view(user_id: int):
    """Текст и клавиатура паспорта. Ранг в UI совпадает с сеткой get_rank."""
    passport = migrate_passport(PASSPORTS[user_id])
    xp = passport["xp"]
    level = calculate_level(xp)
    rank = get_rank(xp)
    remaining = xp_to_next(xp)
    progress_line = f"{get_progress_bar(xp)} · до следующего порога: {remaining} XP" if remaining else f"{get_progress_bar(xp)} · максимальный ранг"
    lines = [
        f"🛂 <b>CITY PASSPORT</b>  <code>{esc(passport['passport_id'])}</code>",
        "",
        f"👤 {esc(passport['name'])} · {esc(rank)}",
        f"⭐ Level: {level}",
        f"⚡ XP: {xp}",
        progress_line,
        f"📆 Сегодня за активность: +{xp_today(user_id)} XP",
        "",
        f"🎫 Статус: {esc(passport.get('status', 'GUEST'))}",
    ]
    until = _parse_dt(passport.get("member_until"))
    if passport.get("status") in ("MEMBER", "PARTNER") and until:
        lines.append(f"⏳ Членство до {until.strftime('%Y-%m-%d')}")
    keyboard_rows = []
    if passport.get("complimentary_granted") and not passport.get("complimentary_claimed"):
        lines += ["", CITYCODE_GRANT_TEXT]
        keyboard_rows.append([InlineKeyboardButton(text="🔑 Активировать 6 месяцев City Code", callback_data="claim_citycode")])
    elif xp >= 800 or is_member_active(user_id):
        # Проводник и выше: ключ City Code — заявка в клуб без очереди (членство не автоматом)
        lines += ["", "🔑 Ключ City Code: твоя заявка в клуб идёт без очереди."]
    if xp >= 100:
        lines += ["", f"🔗 Реф-ссылка: <code>{esc(get_ref_link(user_id))}</code>"]
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows) if keyboard_rows else None
    return "\n".join(lines), markup


@dp.message(F.text == "🛂 City Passport")
async def show_passport(message: types.Message):
    create_passport_if_not_exists(message.from_user)
    expire_memberships()
    text, markup = build_passport_view(message.from_user.id)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


@dp.message(F.text == "/admin")
async def admin_stats(message: types.Message):
    if not is_admin(message.from_user.id):
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


# ────────────────────── админ-команды экономики ──────────────────────

def _cmd_args(message: types.Message) -> list[str]:
    return (message.text or "").split()[1:]


def _arg_int(args: list[str], index: int):
    try:
        return int(args[index])
    except (IndexError, ValueError):
        return None


@dp.message(Command("grant_place"))
async def cmd_grant_place(message: types.Message):
    """/grant_place user_id — принятое место после модерации (+40 XP)."""
    if not is_admin(message.from_user.id):
        return
    args = _cmd_args(message)
    uid = _arg_int(args, 0)
    if uid is None:
        await message.answer("Формат: /grant_place user_id")
        return
    amount = award_verified_xp(uid, "PLACE_ACCEPTED", actor="admin")
    if amount:
        await message.answer(f"✅ Место принято: +{amount} XP пользователю {uid}")
    else:
        await message.answer(f"⚠️ Не начислено. Есть ли паспорт у {uid}?")


@dp.message(Command("checkin"))
async def cmd_checkin(message: types.Message):
    """/checkin user_id event_id — чекин хостом на событии (+60 XP, 1/событие)."""
    if not is_admin(message.from_user.id):
        return
    args = _cmd_args(message)
    uid = _arg_int(args, 0)
    event_id = args[1] if len(args) > 1 else ""
    if uid is None or not event_id:
        await message.answer("Формат: /checkin user_id event_id")
        return
    amount = award_verified_xp(uid, "EVENT_CHECKIN", actor="admin", meta={"event_id": event_id})
    if amount:
        await message.answer(f"✅ Чекин {event_id}: +{amount} XP пользователю {uid}")
    else:
        await message.answer("⚠️ Не начислено: чекин уже был или паспорта нет.")


@dp.message(Command("set_member"))
async def cmd_set_member(message: types.Message):
    """/set_member user_id days source — членство руками (paid/partner/...)."""
    if not is_admin(message.from_user.id):
        return
    args = _cmd_args(message)
    uid = _arg_int(args, 0)
    days = _arg_int(args, 1)
    source = args[2] if len(args) > 2 else "paid"
    if uid is None or days is None:
        await message.answer("Формат: /set_member user_id days source")
        return
    if set_member(uid, days, source):
        p = PASSPORTS[uid]
        await message.answer(f"✅ Членство {uid}: {p['status']} до {p['member_until'][:10]} (source={p['member_source']})")
    else:
        await message.answer(f"⚠️ Паспорт {uid} не найден.")


@dp.message(Command("revoke_xp"))
async def cmd_revoke_xp(message: types.Message):
    """/revoke_xp user_id amount reason — антифарм, снятие XP."""
    if not is_admin(message.from_user.id):
        return
    args = _cmd_args(message)
    uid = _arg_int(args, 0)
    amount = _arg_int(args, 1)
    reason = " ".join(args[2:]) or "без причины"
    if uid is None or amount is None:
        await message.answer("Формат: /revoke_xp user_id amount reason")
        return
    if revoke_xp(uid, amount, reason):
        await message.answer(f"✅ Снято {amount} XP у {uid} ({reason}). Осталось: {PASSPORTS[uid]['xp']} XP")
    else:
        await message.answer(f"⚠️ Паспорт {uid} не найден.")


@dp.message(Command("activate_node"))
async def cmd_activate_node(message: types.Message):
    """/activate_node user_id node_id — узел подключён (+200) или жив 30 дней (+80)."""
    if not is_admin(message.from_user.id):
        return
    args = _cmd_args(message)
    uid = _arg_int(args, 0)
    node_id = args[1] if len(args) > 1 else ""
    if uid is None or not node_id:
        await message.answer("Формат: /activate_node user_id node_id")
        return
    passport = PASSPORTS.get(uid)
    already = bool(passport and any(n.get("node_id") == node_id for n in migrate_passport(passport)["partner_nodes"]))
    action = "PARTNER_NODE_30D" if already else "PARTNER_NODE_CONNECTED"
    amount = award_verified_xp(uid, action, actor="admin", meta={"node_id": node_id})
    if amount:
        await message.answer(f"✅ Узел {node_id}: +{amount} XP ({action}) пользователю {uid}")
    else:
        await message.answer("⚠️ Не начислено: рано (30 дней не прошло) или паспорта нет.")


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
    try:
        expire_memberships()
    except Exception as e:
        logger.warning("expire_memberships: %s", e)

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
        if ADMIN_ID is None:
            logger.warning("ADMIN_ID не задан — веб-предложение не переслано владельцу")
        else:
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

1) Файл .env рядом со скриптом (шаблон — .env.example):
       TG_TOKEN=123456789:AAABBBCCC
2) Переменная окружения:
       export TG_TOKEN=123456789:AAABBBCCC
3) Docker:
       docker run -e TG_TOKEN=123456789:AAABBBCCC ...
4) systemd:
       EnvironmentFile=/etc/sevastopol-ai-bot.env
5) Google Colab:
       os.environ["TG_TOKEN"] = "123456789:AAABBBCCC"

Токен выдаёт @BotFather → /mybots → API Token.
Хранение, ротация и секреты — в SECURITY.md.
"""


async def main():
    load_state()
    warn_insecure_files()
    if not TG_TOKEN or "ЗАМЕНИ" in TG_TOKEN:
        print(NO_TOKEN_HELP, flush=True)
        sys.exit(2)
    if ADMIN_ID is None:
        logger.warning("ADMIN_ID не задан: /admin и пересылка предложений с формы отключены")
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
        print("\n" + "!" * 70, flush=True)
        print("❌ БОТ НЕ ЗАПУСТИЛСЯ: Telegram API не принял подключение.", flush=True)
        print(f"   Причина: {e}", flush=True)
        print("   Чаще всего: токен отозван/неверен (401) — перевыпусти у @BotFather,", flush=True)
        print("   либо нет доступа к api.telegram.org, либо бот уже запущен", flush=True)
        print("   в другом месте с этим же токеном.", flush=True)
        print("!" * 70 + "\n", flush=True)
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
