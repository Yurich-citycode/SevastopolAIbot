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

import asyncio
import html
import logging
import os
import time
from typing import Any, Callable

import requests
from aiogram import F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

logger = logging.getLogger(__name__)

TIMEOUT = 20.0

# где искать сервис, если адрес не задан руками.
# Порядок важен: бот может жить в Docker, тогда «localhost» — это он сам,
# а сервис на хосте виден как host.docker.internal; а если сервис поднят
# в той же docker-сети — по имени сервиса.
CANDIDATES = (
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://host.docker.internal:8080",
    "http://alive-maps-service:8080",
)

_resolved: str | None = None
_resolved_at: float = 0.0


# настройки читаю при каждом вызове: основной файл загружает .env уже после
# импортов, и закешированные значения были бы пустыми
def _url() -> str | None:
    """Адрес сервиса: из .env, иначе — первый отвечающий из списка."""
    global _resolved, _resolved_at

    explicit = (os.getenv("ALIVE_MAP_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit

    if _resolved and time.time() - _resolved_at < 60:
        return _resolved

    for base in CANDIDATES:
        try:
            resp = requests.get(f"{base}/health", timeout=1.5)
        except requests.RequestException:
            continue
        if resp.status_code < 400:
            _resolved, _resolved_at = base, time.time()
            logger.info("живая карта: нашёл сервис на %s", base)
            return base

    _resolved, _resolved_at = None, time.time()
    return None


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
    return _enabled() and bool(_service())


def public_base() -> str:
    """Адрес для кнопок: сначала публичный, иначе локальный."""
    return _public() or _service() or CANDIDATES[0]


def _service() -> str | None:
    return _url()


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

def status() -> dict | None:
    """Что сейчас с сервисом: зоны, мои места, готов ли роутер."""
    base = _service()
    if not base:
        return None
    try:
        resp = requests.get(f"{base}/api/config", timeout=4.0)
        if resp.status_code >= 400:
            return None
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def compare(start_lat: float, start_lon: float, end_lat: float, end_lon: float,
            strength: float = 1.0) -> dict | None:
    """Оба маршрута сразу. None — сервис недоступен или отказал."""
    if not _enabled():
        return None
    base = _service()
    if not base:
        logger.warning("живая карта: сервис не найден (%s)", ", ".join(CANDIDATES))
        return None
    try:
        resp = requests.post(
            f"{base}/api/compare",
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
    if not _enabled():
        return None
    base = _service()
    if not base:
        return None
    try:
        resp = requests.get(
            f"{base}/api/compare.png",
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

def _esc(value: Any) -> str:
    """Экранирование для HTML-разметки Telegram.

    Названия приходят из базы и из текста человека. Если в названии есть & или <,
    Telegram отвечает ошибкой «can't parse entities» — сообщение не доходит вообще.
    """
    return html.escape(str(value or ""), quote=False)


def _clip_html(text: str, limit: int = 1000) -> str:
    """Обрезает подпись под лимит Telegram, не ломая разметку.

    Режем по строкам, а не по символам: обрывок вроде «<b>живой» без закрытия
    тега тоже даёт ошибку разметки.
    """
    if len(text) <= limit:
        return text
    out: list[str] = []
    size = 0
    for line in text.split("\n"):
        if size + len(line) + 1 > limit:
            break
        out.append(line)
        size += len(line) + 1
    clipped = "\n".join(out).rstrip()
    open_tags = clipped.count("<b>") - clipped.count("</b>")
    clipped += "</b>" * max(0, open_tags)
    return clipped or text[:limit].rsplit("<", 1)[0]


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

    most = data.get("most_alive") or {}
    scores = data.get("score") or {}

    fast_score = (fast.get("score") or {}).get("score")
    alive_score = (alive.get("score") or {}).get("score")
    most_score = (most.get("score") or {}).get("score")

    def _points(value) -> str:
        return f" · {value}/100" if isinstance(value, int) else ""

    lines = [
        f"🚶 До «{_esc(place_name)}»",
        "",
        f"⚡ <b>быстрый</b>: {_fmt_minutes(fast.get('time_s'))} · {_fmt_km(fast.get('distance_m'))}{_points(fast_score)}",
        f"🌿 <b>живой</b>: {_fmt_minutes(alive.get('time_s'))} · {_fmt_km(alive.get('distance_m'))}{diff_text}{_points(alive_score)}",
    ]

    # третий вариант показываем, только если он правда другой и заметно живее
    if not (most.get("geojson") == alive.get("geojson")) and isinstance(most_score, int) \
            and isinstance(alive_score, int) and most_score >= alive_score + 5:
        most_diff = round(((data.get("delta_most") or {}).get("time_s") or 0) / 60)
        plus = f" (+{most_diff} мин)" if most_diff > 0 else ""
        lines.append(
            f"✨ <b>самый живой</b>: {_fmt_minutes(most.get('time_s'))} · "
            f"{_fmt_km(most.get('distance_m'))}{plus}{_points(most_score)}"
        )

    percent = scores.get("percent") or 0
    breakdown = (alive.get("score") or {}).get("breakdown") or []
    top = [f"{_esc(item['title']).lower()} {item['percent']}%" for item in breakdown
           if item.get("percent", 0) >= 10][:3]
    if top:
        lead = f"живее быстрого на {percent}% · " if percent > 0 else "по живости: "
        lines += ["", lead + ", ".join(top)]

    bonuses = alive.get("bonuses") or []
    if bonuses:
        names = []
        for item in bonuses[:4]:
            name = item.get("name")
            label = BONUS_LABEL.get(str(item.get("kind")), "место")
            names.append(f"{_esc(name)} ({label})" if name else label)
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


PANEL_HEAD = (
    "🗺 <b>Живая карта</b>\n\n"
    "Считаю два пеших маршрута: <b>быстрый</b> — как обычный навигатор, "
    "и <b>живой</b> — через парки, набережные и мимо мест из моей базы.\n\n"
)


def panel_text() -> str:
    """Текст панели + состояние сервиса: видно, что работает, а что нет."""
    cfg = status()
    if cfg is None:
        return (PANEL_HEAD +
                "Сейчас сервис карты не отвечает. Если он на этой машине — запусти "
                "<code>start.bat</code> в папке <code>alive-maps-service</code>.")

    zones = (cfg.get("zones") or {}).get("count") or 0
    own = (cfg.get("own") or {}).get("count") or 0
    gh_ok = bool((cfg.get("graphhopper") or {}).get("ok"))
    tiles_ok = bool(cfg.get("tiles_ok"))

    if gh_ok:
        line = f"зон: {zones} · моих мест: {own} · роутер готов"
    else:
        line = (f"зон: {zones} · моих мест: {own} · роутер пока импортирует граф "
                "(первые 1–3 минуты после запуска)")
    if not tiles_ok:
        line += " · тайлы не отвечают"
    return PANEL_HEAD + line


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
        await message.answer(panel_text(), reply_markup=_panel_keyboard())

    @dp.callback_query(F.data == "alive:panel")
    async def cb_panel(call: types.CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await call.answer()
        # panel_text ходит в сервис: при выключенной карте это до 6 секунд
        # ожидания подряд — в потоке, чтобы не держать остальных.
        text = await asyncio.to_thread(panel_text)
        await call.message.answer(text, reply_markup=_panel_keyboard())

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
        # requests — синхронный и может думать до 20 секунд. В отдельном потоке:
        # иначе на это время замирает весь бот у всех остальных людей.
        try:
            result = await asyncio.to_thread(compare, start_lat, start_lon, coords["lat"], coords["lon"])
        except Exception as exc:  # noqa: BLE001 — сервис не должен ронять бота
            logger.warning("живая карта: ошибка запроса (%s)", exc)
            result = None
        try:
            await waiting.delete()
        except Exception:  # noqa: BLE001 — сообщение могло уже уехать
            pass

        if result is None:
            await message.answer(
                "Живая карта сейчас недоступна: не нашёл сервис.\n"
                "Если он на этой машине — запусти start.bat в папке alive-maps-service "
                "и повтори."
            )
            await state.clear()
            return
        if result.get("error"):
            await message.answer(f"Не получилось: {result['error']}")
            await state.clear()
            return

        text = format_compare(place_name, result)
        try:
            png = await asyncio.to_thread(
                compare_png, start_lat, start_lon, coords["lat"], coords["lon"], title=str(place_name)[:80]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("живая карта: картинка не собралась (%s)", exc)
            png = None
        await state.clear()

        kb = _route_keyboard(dest)
        if png:
            await message.answer_photo(
                BufferedInputFile(png, filename="route.png"),
                caption=_clip_html(text),
                parse_mode="HTML",
                reply_markup=kb,
            )
        else:
            await message.answer(text, parse_mode="HTML", reply_markup=kb)

    logger.info("живая карта включена: %s", _service() or "сервис пока не найден")
