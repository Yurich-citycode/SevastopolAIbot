"""Живая карта в боте: маршруты «быстрый» и «живой» из своего сервиса.

Сервис живёт рядом (папка alive-maps-service, docker compose) и отвечает на
localhost:8080. Здесь только тонкий мост: бот спрашивает у сервиса пару
маршрутов, получает картинку и текст и отправляет человеку.

Что даёт боту:
  * /map — кнопка на карту (в браузере или сразу мини-аппом в Telegram);
  * /route <название места> — маршрут от геолокации пользователя до места
    из моей базы, с картинкой и объяснением, через что он прошёл.

Если сервис лежит — бот об этом честно говорит и продолжает работать дальше.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

import requests
from aiogram import F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

logger = logging.getLogger(__name__)

TIMEOUT = 20.0


# настройки читаю при каждом вызове: основной файл загружает .env уже после
# импортов, и закешированные значения были бы пустыми
def _url() -> str:
    return (os.getenv("ALIVE_MAP_URL") or "http://localhost:8080").rstrip("/")


def _public() -> str:
    return (os.getenv("ALIVE_MAP_PUBLIC") or "").rstrip("/")


def _enabled() -> bool:
    return os.getenv("ALIVE_MAP_ON", "1").strip().lower() not in ("0", "false", "no", "")

# листы моей базы, где ищу место для маршрута
SEARCH_SHEETS = ("Где поесть", "Локации")

# подписи для типов точек в объяснении
BONUS_LABEL = {
    "park": "парк",
    "waterfront": "набережная",
    "historic": "историческое место",
    "cafe": "кафе",
    "lively": "людное место",
}


class RouteState(StatesGroup):
    waiting_place = State()   # ждём название места
    waiting_geo = State()     # ждём геолокацию


# заполняется в register()
_get_places: Callable[[str], list[dict]] | None = None
_pick: Callable[..., str] | None = None


def is_on() -> bool:
    return _enabled() and bool(_url())


def public_base() -> str:
    """Адрес для кнопок: сначала публичный, иначе локальный."""
    return _public() or _url()


def _parse_coords(value: Any) -> tuple[float, float] | None:
    """«44.610761, 33.542573» → (lat, lon)."""
    text = str(value or "").replace(";", ",").strip()
    if "," not in text:
        return None
    left, right = text.split(",", 1)
    try:
        lat, lon = float(left.strip().replace(",", ".")), float(right.strip().replace(",", "."))
    except ValueError:
        return None
    if not (43 < lat < 46 and 30 < lon < 40):
        return None
    return lat, lon


# ---------------- запросы к сервису ----------------

def compare(start_lat: float, start_lon: float, end_lat: float, end_lon: float,
            strength: float = 1.0) -> dict | None:
    """Оба маршрута сразу. None — сервис недоступен или отказал."""
    if not is_on():
        return None
    try:
        resp = requests.post(
            f"{_url()}/api/compare",
            json={
                "start": [start_lon, start_lat],
                "end": [end_lon, end_lat],
                "strength": strength,
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("живая карта: сервис недоступен (%s)", exc)
        return None

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail") or resp.text[:200]
        except ValueError:
            detail = resp.text[:200]
        logger.warning("живая карта: %s — %s", resp.status_code, detail)
        return {"error": str(detail)}
    try:
        return resp.json()
    except ValueError:
        return None


def compare_png(start_lat: float, start_lon: float, end_lat: float, end_lon: float,
                title: str = "") -> bytes | None:
    """Картинка с двумя маршрутами."""
    if not is_on():
        return None
    try:
        resp = requests.get(
            f"{_url()}/api/compare.png",
            params={
                "from": f"{start_lat:.6f},{start_lon:.6f}",
                "to": f"{end_lat:.6f},{end_lon:.6f}",
                "title": title,
            },
            timeout=TIMEOUT + 10,
        )
    except requests.RequestException as exc:
        logger.warning("живая карта: картинка не пришла (%s)", exc)
        return None
    if resp.status_code != 200 or not resp.content.startswith(b"\x89PNG"):
        return None
    return resp.content


def map_link(start_lat: float | None = None, start_lon: float | None = None,
             end_lat: float | None = None, end_lon: float | None = None) -> str:
    """Ссылка на карту, сразу с точками (её понимает index.html)."""
    base = public_base()
    if None in (start_lat, start_lon, end_lat, end_lon):
        return base
    return (f"{base}/?from={start_lat:.6f},{start_lon:.6f}"
            f"&to={end_lat:.6f},{end_lon:.6f}")


# ---------------- текст и клавиатуры ----------------

def _fmt_minutes(seconds: float) -> str:
    return f"{round((seconds or 0) / 60)} мин"


def _fmt_km(meters: float) -> str:
    return f"{(meters or 0) / 1000:.1f} км"


def format_compare(place_name: str, data: dict) -> str:
    """Текст ответа: два маршрута, разница и через что прошёл живой."""
    fast = data.get("fast") or {}
    alive = data.get("alive") or {}
    delta = data.get("delta") or {}

    diff = round((delta.get("time_s") or 0) / 60)
    diff_text = f" (+{diff} мин)" if diff > 0 else " (столько же)"

    lines = [
        f"🚶 До «{place_name}»",
        "",
        f"⚡ <b>быстрый</b>: {_fmt_minutes(fast.get('time_s'))} · {_fmt_km(fast.get('distance_m'))}",
        f"🌿 <b>живой</b>: {_fmt_minutes(alive.get('time_s'))} · {_fmt_km(alive.get('distance_m'))}{diff_text}",
    ]

    bonuses = alive.get("bonuses") or []
    if bonuses:
        names = []
        for item in bonuses[:4]:
            name = item.get("name")
            label = BONUS_LABEL.get(str(item.get("kind")), "место")
            names.append(f"{name} ({label})" if name else label)
        lines += ["", "через: " + ", ".join(names)]

    if (delta.get("same_route")):
        lines += ["", "маршруты совпали — тут живой обходить нечего"]

    if alive.get("degraded"):
        lines.append("")
        lines.append("зоны сейчас не применились, маршрут посчитан по обычным улицам")

    return "\n".join(lines)


def _panel_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    url = public_base()
    if url.startswith("https://"):
        rows.append([InlineKeyboardButton(text="🗺 Открыть карту", web_app=WebAppInfo(url=url))])
    rows.append([InlineKeyboardButton(text="🌐 Открыть в браузере", url=url)])
    rows.append([InlineKeyboardButton(text="🚶 Маршрут от меня", callback_data="alive:ask")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _route_keyboard(place: dict) -> InlineKeyboardMarkup:
    rows = []
    coords = place.get("coords") or {}
    if _public():
        rows.append([InlineKeyboardButton(
            text="🗺 Открыть на карте",
            url=map_link(coords.get("lat"), coords.get("lon"),
                         coords.get("lat"), coords.get("lon")),
        )])
    rows.append([InlineKeyboardButton(text="🌿 Другое место", callback_data="alive:ask")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


PANEL_TEXT = (
    "🗺 <b>Живая карта</b>\n\n"
    "Считаю два пеших маршрута: <b>быстрый</b> — как обычный навигатор, "
    "и <b>живой</b> — через парки, набережные и мимо мест из моей базы.\n\n"
    "Данные и роутер свои, ключи не нужны."
)


# ---------------- поиск места в базе ----------------

def find_places(query: str, limit: int = 5) -> list[dict]:
    """Ищет место по названию во всей базе. Нужны функции из основного файла."""
    if not _get_places or not _pick:
        return []
    needle = (query or "").strip().lower().replace("ё", "е")
    if len(needle) < 2:
        return []

    found: list[dict] = []
    seen: set[str] = set()
    for sheet in SEARCH_SHEETS:
        try:
            rows = _get_places(sheet) or []
        except Exception as exc:  # noqa: BLE001 — база может быть недоступна
            logger.warning("живая карта: лист %s не прочитался (%s)", sheet, exc)
            continue
        for row in rows:
            name = str(_pick(row, "Название") or "").strip()
            if not name or name.lower() in seen:
                continue
            category = str(_pick(row, "Категория") or "").strip()
            haystack = (name + " " + category).lower().replace("ё", "е")
            if needle not in haystack:
                continue
            coords = _parse_coords(_pick(row, "Координаты"))
            if not coords:
                continue
            seen.add(name.lower())
            found.append({
                "name": name,
                "sheet": sheet,
                "category": str(_pick(row, "Категория") or ""),
                "coords": {"lat": coords[0], "lon": coords[1]},
            })
            if len(found) >= limit:
                return found
    return found


# ---------------- регистрация ----------------

def register(dp, get_places: Callable[[str], list[dict]],
             pick: Callable[..., str]) -> None:
    """Вешает обработчики на диспетчер бота.

    Регистрирую напрямую на dp и до «ловящих всё» обработчиков основного файла,
    иначе мои команды перехватит общий fallback.
    """
    global _get_places, _pick

    if not _enabled():
        return
    _get_places = get_places
    _pick = pick

    @dp.message(Command("map", "карта", "живая_карта"))
    async def cmd_map(message: types.Message, state: FSMContext) -> None:
        await state.clear()
        if not is_on():
            await message.answer("Живая карта сейчас выключена.")
            return
        await message.answer(PANEL_TEXT, reply_markup=_panel_keyboard())

    @dp.callback_query(F.data == "alive:panel")
    async def cb_panel(call: types.CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await call.answer()
        await call.message.answer(PANEL_TEXT, reply_markup=_panel_keyboard())

    @dp.callback_query(F.data == "alive:ask")
    async def cb_ask(call: types.CallbackQuery, state: FSMContext) -> None:
        await state.set_state(RouteState.waiting_place)
        await call.answer()
        await call.message.answer(
            "Куда идём? Напиши название места — например «Фиолент», «Артбухта», «Кофе в Окнах»."
        )

    @dp.message(Command("route", "маршрут"))
    async def cmd_route(message: types.Message, state: FSMContext) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await state.set_state(RouteState.waiting_place)
            await message.answer("Куда? Напиши название места из базы.")
            return
        await ask_geo(message, state, parts[1].strip())

    @dp.message(StateFilter(RouteState.waiting_place), F.text)
    async def got_place(message: types.Message, state: FSMContext) -> None:
        query = (message.text or "").strip()
        if query.startswith("/"):
            await state.clear()
            return
        matches = find_places(query)
        if not matches:
            await message.answer(
                f"Не нашёл «{query}» в базе. Попробуй иначе: «пляж», «музей», «кофе»."
            )
            return
        if len(matches) == 1:
            await ask_geo(message, state, matches[0]["name"], matches[0])
            return

        await state.update_data(candidates=matches)
        rows = [
            [InlineKeyboardButton(
                text=f"{item['name']} · {item['category']}"[:60],
                callback_data=f"alive:pick:{idx}",
            )]
            for idx, item in enumerate(matches)
        ]
        await message.answer("Нашёл несколько, выбери:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    @dp.callback_query(F.data.startswith("alive:pick:"))
    async def cb_pick(call: types.CallbackQuery, state: FSMContext) -> None:
        try:
            idx = int((call.data or "").split(":")[-1])
        except ValueError:
            await call.answer("Не понял выбор", show_alert=True)
            return
        data = await state.get_data()
        candidates = data.get("candidates") or []
        if idx >= len(candidates):
            await call.answer("Список устарел, начни заново: /route", show_alert=True)
            return
        await call.answer()
        await ask_geo(call.message, state, candidates[idx]["name"], candidates[idx])

    async def ask_geo(message: types.Message, state: FSMContext, name: str,
                      place: dict | None = None) -> None:
        if place is None:
            matches = find_places(name, limit=1)
            if not matches:
                await message.answer(f"Не нашёл «{name}» в базе.")
                return
            place = matches[0]
            name = place["name"]

        # если место вне карты — сервис всё равно ответит понятной ошибкой
        await state.set_state(RouteState.waiting_geo)
        await state.update_data(dest=place)
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📍 Отправить геолокацию", callback_data="alive:geohelp"),
        ]])
        await message.answer(
            f"До «{name}». Скинь геолокацию 📎 → «Геопозиция» — посчитаю оба маршрута.",
            reply_markup=kb,
        )

    @dp.callback_query(F.data == "alive:geohelp")
    async def cb_geohelp(call: types.CallbackQuery) -> None:
        await call.answer("Скрепка → Геопозиция", show_alert=True)

    @dp.message(StateFilter(RouteState.waiting_geo), F.location)
    async def got_geo(message: types.Message, state: FSMContext) -> None:
        """Геолокация в режиме маршрута. В обычном режиме её обрабатывает бот."""
        data = await state.get_data()
        dest = data.get("dest") or {}
        coords = dest.get("coords") or {}
        if not coords:
            await state.clear()
            await message.answer("Потерял место, начни заново: /route")
            return

        start_lat = message.location.latitude
        start_lon = message.location.longitude
        place_name = dest.get("name") or "места"

        waiting = await message.answer("Считаю два маршрута…")
        result = compare(start_lat, start_lon, coords["lat"], coords["lon"])
        try:
            await waiting.delete()
        except Exception:  # noqa: BLE001 — сообщение могло уже уехать
            pass

        if result is None:
            await message.answer("Живая карта сейчас недоступна. Попробуй позже.")
            await state.clear()
            return
        if result.get("error"):
            await message.answer(f"Не получилось: {result['error']}")
            await state.clear()
            return

        text = format_compare(place_name, result)
        png = compare_png(start_lat, start_lon, coords["lat"], coords["lon"],
                          title=f"{place_name}")
        await state.clear()

        kb = _route_keyboard(dest)
        if png:
            await message.answer_photo(
                BufferedInputFile(png, filename="route.png"),
                caption=text[:1000],
                parse_mode="HTML",
                reply_markup=kb,
            )
        else:
            await message.answer(text, parse_mode="HTML", reply_markup=kb)

    logger.info("живая карта подключена: сервис %s", _url())
