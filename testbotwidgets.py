#!/usr/bin/env python3
"""Тест-бот виджетов — дубль бота, где весь интерфейс живёт в сообщении.

Идея
----
В Bot API 10.4 (9 ноября 2026) появились HTML-виджеты: бот вставляет в сообщение
небольшую разметку, она рисуется в песочнице Telegram, а наружу умеет ровно
одно — спросить бота через TelegramWidget.request(...). Бот отвечает, виджет
перерисовывается **в этом же сообщении**. Ни новых сообщений, ни мини-аппа.

Здесь так собраны все разделы: еда, локации, события, маршруты, паспорт.
Один HTML на все экраны: при загрузке виджет спрашивает «boot», дальше —
каждое нажатие это новый запрос и новая картинка в том же пузыре.

Главный бот (sevastopolaibot.py) не тронут: это отдельный файл со своим токеном.

Запуск
------
    TESTBOT.bat                      (Windows: спросит токен и запустит)
    python testbotwidgets.py         (токен из TG_TOKEN или widgets/token.txt)

    python testbotwidgets.py --check          проверить размеры всех экранов
    python testbotwidgets.py --preview DIR    собрать предпросмотр в браузере
    python testbotwidgets.py --beta           сразу через api.telegram.org/beta

Виджеты Telegram пока раздаёт не всем ботам: обычный бот получает
INPUT_MEDIA_WIDGET_NOT_ALLOWED. Код сам пробует бету и, если не пустили,
показывает те же экраны обычными сообщениями с кнопками.

Лимиты Telegram, под которые подогнан код:
  * HTML до 32 КБ, после сжатия zlib уровнем 9 — до 4 КБ;
  * запрос из виджета 1–64 байта, ответ бота до 1024 байт;
  * ответ за 15 секунд, не больше 5 запросов за 5 секунд с человека;
  * сейчас только личные чаты.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import zlib
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from typing import Any

import requests

BASE = Path(__file__).resolve().parent
WIDGET_HTML = BASE / "widgets" / "testbot_widget.html"
XLSX = BASE / "Sevastopol AI База.xlsx"
PASSPORT_FILE = BASE / "widgets" / ".passport.json"
TOKEN_FILE = BASE / "widgets" / "token.txt"
MAP_URL = (os.getenv("ALIVE_MAP_URL") or "http://localhost:8080").rstrip("/")

API_ROOT = "https://api.telegram.org"
API = API_ROOT + "/bot{token}/{method}"
API_BETA = API_ROOT + "/beta/bot{token}/{method}"
BETA = (os.getenv("TG_API_BETA") or "").strip().lower() in ("1", "true", "yes") or "--beta" in sys.argv
TIMEOUT = 25

MAX_ANSWER = 1024          # байт: столько Telegram отдаёт виджету за один ответ
PAGE = 5                   # строк в списке

ICONS = {
    "food": "🍽", "coffee": "☕", "rest": "🍷", "cafe": "🥐", "bakery": "🥖",
    "sweets": "🍰", "delivery": "🛵", "places": "📍", "events": "🎭",
    "routes": "🥾", "pass": "🛂", "sunset": "🌅", "beach": "🏖", "history": "🏛",
    "view": "👀", "park": "🌳", "default": "•",
}

FOOD_CATS = (
    ("coffee", "Кофе", "☕"),
    ("rest", "Рестораны", "🍷"),
    ("cafe", "Кафе", "🥐"),
    ("bakery", "Пекарни", "🥖"),
    ("sweets", "Кондитерские", "🍰"),
    ("delivery", "Доставки", "🛵"),
)


# ────────────────────────────── Telegram API ──────────────────────────────

def call(method: str, token: str, beta: bool = False, **params) -> Any:
    """Один вызов Bot API с повторами: сеть до Telegram бывает капризной.

    На таймаут и обрыв пробуем ещё дважды — за это время связь обычно
    восстанавливается. Ответ «ok: false» (например, неверный токен) не
    повторяем: там повтор ничего не изменит.
    """
    url = (API_BETA if (beta or BETA) else API).format(token=token, method=method)
    problem = ""

    for attempt in range(3):
        try:
            resp = requests.post(url, json=params, timeout=TIMEOUT)
        except requests.Timeout:
            problem = (f"{method}: Telegram не ответил за {int(TIMEOUT)} секунд "
                       f"(попытка {attempt + 1} из 3)")
            time.sleep(1.5 * (attempt + 1))
            continue
        except requests.RequestException as exc:
            # в тексте ошибки requests печатает полный адрес, а там токен — вырезаем
            problem = f"{method}: нет связи ({str(exc).replace(token, '***')})"
            time.sleep(1.0)
            continue

        try:
            payload = resp.json()
        except ValueError:
            raise RuntimeError(f"{method}: ответ не JSON (HTTP {resp.status_code})")
        if not payload.get("ok"):
            raise RuntimeError(f"{method}: {payload.get('description')}")
        return payload.get("result")

    raise RuntimeError(problem + "\nЕсли это Colab — перезапусти ячейку. "
                                 "Если повторяется, проще запустить на компьютере: TESTBOT.bat")


def send_message(token: str, chat_id: int, text: str) -> None:
    call("sendMessage", token, chat_id=chat_id, text=text, disable_web_page_preview=True)


class WidgetsClosed(RuntimeError):
    """Виджеты этому боту не разрешены — нужен запасной вариант интерфейса."""


def send_widget(token: str, chat_id: int, state: dict, caption: str = "") -> int:
    """Отправляет виджет. Внутрь HTML данные не вшиваем: виджет сам спросит «boot»."""
    html = WIDGET_HTML.read_text(encoding="utf-8")
    packed = len(zlib.compress(html.encode("utf-8"), 9))
    if packed > 4096:
        raise ValueError(f"виджет не влезает: {packed} байт после сжатия (лимит 4096)")

    payload = dict(
        chat_id=chat_id,
        html=html,
        caption=caption or "Тяни за строки — всё внутри этого сообщения",
        allow_queries=True,
        height=420,
        chat_data=json.dumps({"k": "menu"}, ensure_ascii=False, separators=(",", ":")),
    )

    try:
        message = call("sendWidget", token, **payload)
    except RuntimeError as exc:
        text = str(exc)
        if "WIDGET_NOT_ALLOWED" not in text:
            raise
        # виджеты пока раздают не всем ботам: пробуем бету
        try:
            message = call("sendWidget", token, beta=True, **payload)
        except RuntimeError as second:
            raise WidgetsClosed(str(second)) from second

    return int((message or {}).get("message_id") or 0)


# ────────────────────────────── данные из таблицы ──────────────────────────────

def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _clean(value: Any) -> str:
    """Убирает эмодзи-маркеры и лишние пробелы из описаний."""
    text = _text(value)
    text = re.sub(r"^[\s✔️✅🔹•\-—]+", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class Catalog:
    """Всё, что бот знает о городе: еда, локации, события, маршруты."""

    def __init__(self) -> None:
        self.food: list[dict] = []
        self.places: list[dict] = []
        self.events: list[dict] = []
        self.routes: list[dict] = []
        self.menu: dict[str, str] = {}
        self.error: str | None = None
        self.load()

    def load(self) -> None:
        if not XLSX.exists():
            self.error = f"нет файла {XLSX.name}"
            return
        try:
            import pandas as pd

            book = pd.ExcelFile(XLSX)
            sheets = {name.strip(): name for name in book.sheet_names}
        except Exception as exc:  # noqa: BLE001 — без таблицы бот всё равно поднимется
            self.error = f"таблица не читается: {exc}"
            return

        def rows(sheet_name: str) -> list[dict]:
            if sheet_name not in sheets:
                return []
            frame = pd.read_excel(book, sheet_name=sheets[sheet_name]).astype(object)
            frame = frame.where(lambda d: d.notna(), "")
            return frame.to_dict(orient="records")

        for index, row in enumerate(rows("Где поесть")):
            name = _text(row.get("Название"))
            if not name:
                continue
            self.food.append({
                "id": f"f{index}",
                "name": name,
                "category": _text(row.get("Категория")),
                "subcategory": _text(row.get("Подкатегория")),
                "desc": _clean(row.get("Описание")),
                "address": _text(row.get("Адрес")),
                "district": _text(row.get("Район")),
                "coords": _text(row.get("Координаты")),
            })

        for index, row in enumerate(rows("Локации")):
            name = _text(row.get("Название"))
            if not name:
                continue
            self.places.append({
                "id": f"p{index}",
                "name": name,
                "category": _text(row.get("Категория")),
                "desc": _clean(row.get("Описание")),
                "landmark": _text(row.get("Ориентир")),
                "coords": _text(row.get("Координаты")),
            })

        for index, row in enumerate(rows("Лист9")):
            name = _text(row.get("Название"))
            if not name:
                continue
            self.events.append({
                "id": f"e{index}",
                "name": re.sub(r"[*_]", "", name),
                "date": _text(row.get("Дата")),
                "place": _text(row.get("Место")),
                "price": _text(row.get("Цена")),
                "link": _text(row.get("Ссылка на пост")),
            })

        for index, row in enumerate(rows("Маршруты")):
            name = _text(row.get("Название"))
            if not name:
                continue
            self.routes.append({
                "id": f"r{index}",
                "name": name,
                "category": _text(row.get("Категория")),
                "length": _text(row.get("Длина/Время")),
                "difficulty": _text(row.get("Сложность")),
                "desc": _clean(row.get("Описание")),
                "map": _text(row.get("Ссылка на карту")),
            })

        for row in rows("Меню Справочник"):
            name = _text(row.get("Название заведения"))
            text = _clean(row.get("Меню/Цены/Особенности"))
            if name and text:
                self.menu[name] = text

    # --- поиск ---

    def by_id(self, item_id: str) -> dict | None:
        pool = {"f": self.food, "p": self.places, "e": self.events, "r": self.routes}
        bucket = pool.get(item_id[:1])
        if not bucket:
            return None
        return next((item for item in bucket if item["id"] == item_id), None)

    def food_by_category(self, key: str) -> list[dict]:
        title = next((title for k, title, _ in FOOD_CATS if k == key), "")
        if not title:
            return []
        return [item for item in self.food if item["category"].lower().startswith(title.lower())]

    def search(self, query: str) -> list[dict]:
        needle = query.strip().lower().replace("ё", "е")
        if len(needle) < 2:
            return []
        found: list[dict] = []
        for bucket, icon in ((self.food, "🍽"), (self.places, "📍"), (self.routes, "🥾")):
            for item in bucket:
                if needle in item["name"].lower().replace("ё", "е"):
                    found.append({**item, "icon": icon, "kind": bucket is self.food and "еда" or "место"})
        return found[:10]


CATALOG = Catalog()


# ────────────────────────────── паспорт ──────────────────────────────

def load_passports() -> dict:
    try:
        return json.loads(PASSPORT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def passport_of(user_id: int) -> dict:
    data = load_passports()
    card = data.get(str(user_id)) or {"xp": 0, "opened": 0, "routes": 0, "created": datetime.now().isoformat()}
    return card


def add_xp(user_id: int, amount: int = 5, field: str = "opened") -> dict:
    data = load_passports()
    key = str(user_id)
    card = data.get(key) or {"xp": 0, "opened": 0, "routes": 0, "created": datetime.now().isoformat()}
    card["xp"] = int(card.get("xp", 0)) + amount
    card[field] = int(card.get(field, 0)) + 1
    data[key] = card
    try:
        PASSPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        PASSPORT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return card


RANKS = ((0, "Гость"), (100, "Прогульщик"), (300, "Местный"), (700, "Гид"), (1500, "Хранитель"))


def rank_of(xp: int) -> tuple[str, int, int | None]:
    """Звание, его номер и порог следующего (None — уже максимум)."""
    level = 0
    for index, (threshold, _) in enumerate(RANKS):
        if xp >= threshold:
            level = index
    title = RANKS[level][1]
    nxt = RANKS[level + 1][0] if level + 1 < len(RANKS) else None
    return title, level, nxt


def progress(xp: int) -> tuple[str, int]:
    """Звание и заполненность полоски до следующего, в процентах."""
    title, level, nxt = rank_of(xp)
    if nxt is None:
        return title, 100
    floor = RANKS[level][0]
    pct = int(100 * (xp - floor) / max(1, nxt - floor))
    return title, max(3, min(100, pct))


# ────────────────────────────── экраны ──────────────────────────────

def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def screen_menu(catalog: Catalog) -> dict:
    return {
        "k": "menu",
        "t": "Куда пойдём?",
        "s": "Всё внутри одного сообщения",
        "i": [
            ["c:food", "🍽", "Где поесть", f"{len(catalog.food)} мест"],
            ["c:places", "📍", "Локации", f"{len(catalog.places)} мест"],
            ["c:events", "🎭", "События", f"{len(catalog.events)} в ленте"],
            ["c:routes", "🥾", "Маршруты", f"{len(catalog.routes)} идей"],
            ["pp", "🛂", "Паспорт", "XP и ранг"],
            ["c:map", "🗺", "Живая карта", "маршрут по городу"],
        ],
        "n": "Нажатие меняет этот экран, новых сообщений не будет.",
    }


def screen_food(catalog: Catalog) -> dict:
    return {
        "k": "menu",
        "up": "Где поесть",
        "t": "Что ищем?",
        "i": [[f"l:food:{key}", icon, title, f"{len(catalog.food_by_category(key))} мест"]
              for key, title, icon in FOOD_CATS],
        "b": [["m", "‹ меню"]],
        "n": "Цифры — сколько мест в базе по этому разделу.",
    }


def screen_list(catalog: Catalog, kind: str, key: str = "", page: int = 0) -> dict:
    if kind == "food":
        title = next((t for k, t, _ in FOOD_CATS if k == key), "Где поесть")
        items = catalog.food_by_category(key)
        prefix, up = "f", "Где поесть"
    elif kind == "places":
        title, items, prefix, up = "Локации", catalog.places, "p", "Севастополь"
    elif kind == "events":
        title, items, prefix, up = "События", catalog.events, "e", "Афиша"
    else:
        title, items, prefix, up = "Маршруты", catalog.routes, "r", "Пешком"

    total = len(items)
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    chunk = items[page * PAGE:(page + 1) * PAGE]

    rows = []
    for item in chunk:
        subtitle = ""
        if prefix == "f":
            subtitle = " · ".join(x for x in (item["category"], item["district"] or item["address"]) if x)
            icon = ICONS.get(item["category"].lower(), "🍽") if item["category"].lower() in ICONS else "🍽"
        elif prefix == "p":
            subtitle = " · ".join(x for x in (item["category"], item["landmark"]) if x)
            icon = "📍"
        elif prefix == "e":
            subtitle = " · ".join(x for x in (item["date"], item["place"]) if x)
            icon = "🎭"
        else:
            subtitle = " · ".join(x for x in (item["length"], item["difficulty"]) if x)
            icon = "🥾"
        rows.append([f"o:{item['id']}", icon, _clip(item["name"], 42), _clip(subtitle, 44)])

    screen = {
        "k": "list",
        "up": up,
        "t": title,
        "s": f"{total} мест" if total else "пока пусто",
        "i": rows,
        "pg": f"{page * PAGE + 1}–{min(total, (page + 1) * PAGE)} из {total}" if total else "",
    }
    if page > 0:
        screen["prev"] = f"l:{kind}:{key}:{page - 1}"
    if page + 1 < pages:
        screen["next"] = f"l:{kind}:{key}:{page + 1}"
    if up != "Где поесть" and kind == "food":
        screen["b"] = [["c:food", "‹ назад"]]
    return screen


def screen_card(catalog: Catalog, item_id: str, back: str) -> dict:
    item = catalog.by_id(item_id)
    if not item:
        return {"k": "card", "t": "Не нашёл", "s": "Возможно, запись удалили", "b": [[back, "‹ назад"]]}

    screen: dict = {"k": "card", "t": _clip(item["name"], 60), "b": [[back, "‹ назад"]]}

    if item_id.startswith("f"):
        chips = [x for x in (item["category"], item["subcategory"], item["district"]) if x]
        screen["ch"] = chips
        screen["s"] = item["address"] or item["district"] or "адрес не указан"
        menu = catalog.menu.get(item["name"])
        screen["d"] = _clip(item["desc"] or menu or "описания пока нет", 380)
        meta = []
        if menu and item["desc"]:
            meta.append(["Меню", _clip(menu, 90)])
        if item["address"]:
            meta.append(["Адрес", _clip(item["address"], 60)])
    elif item_id.startswith("p"):
        screen["ch"] = [x for x in (item["category"],) if x]
        screen["s"] = item["landmark"] or "ориентир не указан"
        screen["d"] = _clip(item["desc"] or "описания пока нет", 380)
        meta = [["Ориентир", _clip(item["landmark"], 60)]] if item["landmark"] else []
    elif item_id.startswith("e"):
        screen["ch"] = [x for x in (item["date"], item["price"]) if x]
        screen["s"] = item["place"] or "место уточняется"
        screen["d"] = _clip(item.get("desc") or "", 220) or None
        meta = [["Дата", item["date"]]] if item["date"] else []
        if item["link"]:
            meta.append(["Афиша", _clip(item["link"], 70)])
    else:
        screen["ch"] = [x for x in (item["category"], item["difficulty"]) if x]
        screen["s"] = item["length"] or "длина не указана"
        screen["d"] = _clip(item["desc"] or "", 380)
        meta = [["Сложность", item["difficulty"]]] if item["difficulty"] else []

    if meta:
        screen["m"] = meta
    screen["n"] = "Нажми «назад» — вернёшься к списку в этом же сообщении."
    return screen


def screen_passport(user_id: int, name: str) -> dict:
    card = passport_of(user_id)
    xp = int(card.get("xp", 0))
    rank, pct = progress(xp)
    return {
        "k": "pass",
        "t": f"{rank} · {xp} XP",
        "s": name,
        "pct": pct,
        "st": [
            [str(card.get("opened", 0)), "открыто"],
            [str(card.get("routes", 0)), "маршрутов"],
            [str(xp), "XP"],
        ],
        "b": [["m", "‹ меню"]],
        "n": "XP капает за просмотр мест и маршрутов. Это проба, не боевая статистика.",
    }


ROUTE_PRESETS = (
    ("Фиолент", "44.512959,33.479362"),
    ("Артбухта", "44.610914,33.518241"),
    ("Херсонес", "44.610671,33.492889"),
)


def screen_route_map(index: int = 0, start: str = "44.613400,33.522500") -> dict:
    """Живая карта: три варианта маршрута из локального сервиса."""
    title, target = ROUTE_PRESETS[max(0, min(index, len(ROUTE_PRESETS) - 1))]
    try:
        lat, lon = (float(x) for x in start.split(","))
        end_lat, end_lon = (float(x) for x in target.split(","))
        resp = requests.post(
            f"{MAP_URL}/api/compare",
            json={"start": [lon, lat], "end": [end_lon, end_lat]},
            timeout=20,
        )
        data = resp.json() if resp.status_code < 400 else {}
    except (requests.RequestException, ValueError, StopIteration):
        data = {}

    if not data.get("fast"):
        return {
            "k": "card",
            "up": "Живая карта",
            "t": title,
            "s": "сервис карты не отвечает",
            "d": "Запусти start.bat в папке alive-maps-service — и здесь появятся три варианта маршрута.",
            "b": [["m", "‹ меню"], ["c:map", "повторить"]],
        }

    rows = []
    for key, icon in (("fast", "⚡"), ("alive", "🌿"), ("most_alive", "✨")):
        route = data.get(key) or {}
        rows.append({
            "i": icon,
            "t": {"fast": "быстрый", "alive": "живой", "most_alive": "самый живой"}[key],
            "min": round(float(route.get("time_s") or 0) / 60),
            "km": round(float(route.get("distance_m") or 0) / 1000, 1),
            "sc": int(((route.get("score") or {}).get("score")) or 0),
        })
    return {"k": "route", "t": f"до «{title}»", "s": "три варианта, нажми любой",
            "r": rows, "sel": 1, "b": [["m", "‹ меню"]]}


# ────────────────────────────── состояние экранов ──────────────────────────────

# (chat_id, message_id) → {"steps": [...], "user": id, "name": str}
SCREENS: dict[tuple[int, int], dict] = {}


def build(action: str, state: dict) -> dict:
    """Действие из виджета → экран."""
    parts = action.split(":")
    head = parts[0]

    if head == "boot" or head == "m":
        state["steps"] = []
        return screen_menu(CATALOG)

    if head == "c":
        key = parts[1] if len(parts) > 1 else ""
        state["steps"] = [action]
        if key == "food":
            return screen_food(CATALOG)
        if key == "places":
            return screen_list(CATALOG, "places")
        if key == "events":
            return screen_list(CATALOG, "events")
        if key == "routes":
            return screen_list(CATALOG, "routes")
        if key == "map":
            return screen_route_map(0)
        return screen_menu(CATALOG)

    if head == "l":
        kind = parts[1] if len(parts) > 1 else "places"
        key = parts[2] if len(parts) > 2 else ""
        page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        state["steps"] = [action]
        return screen_list(CATALOG, kind, key, page)

    if head == "o":
        item_id = parts[1] if len(parts) > 1 else ""
        back = state["steps"][-1] if state.get("steps") else "m"
        if item_id.startswith("f"):
            add_xp(state["user"], 5, "opened")
        elif item_id.startswith("r"):
            add_xp(state["user"], 15, "routes")
        return screen_card(CATALOG, item_id, back)

    if head == "pp":
        state["steps"] = [action]
        return screen_passport(state["user"], state.get("name") or "гость")

    if head == "rp":
        index = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        return screen_route_map(index)

    return screen_menu(CATALOG)


def fit(screen: dict) -> str:
    """Пакует экран в лимит 1024 байта, аккуратно урезая текст."""
    raw = json.dumps(screen, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) <= MAX_ANSWER:
        return raw

    slim = dict(screen)
    slim.pop("n", None)
    for row in slim.get("i") or []:
        for index in range(2, len(row)):
            if isinstance(row[index], str) and len(row[index]) > 24:
                row[index] = row[index][:23] + "…"
    if slim.get("d"):
        slim["d"] = slim["d"][:160] + "…"
    raw = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) <= MAX_ANSWER:
        return raw

    slim["i"] = (slim.get("i") or [])[:4]
    raw = json.dumps(slim, ensure_ascii=False, separators=(",", ":"))
    return raw if len(raw.encode("utf-8")) <= MAX_ANSWER else json.dumps({"k": "menu", "t": "Начнём заново", "i": []}, ensure_ascii=False)


# ─────────────────────── запасной вид: обычные сообщения с кнопками ───────────────────────

def _e(value: Any) -> str:
    """Экранирование для HTML: в названиях бывают & и <, из-за них Telegram ругается."""
    return html_escape(str(value or ""), quote=False)


def screen_text(screen: dict) -> str:
    """Тот же экран, но текстом — если виджеты боту недоступны."""
    kind = screen.get("k")
    lines: list[str] = []

    if kind == "menu":
        lines.append(f"<b>{_e(screen.get('t'))}</b>")
        if screen.get("s"):
            lines.append(_e(screen["s"]))
        for row in screen.get("i") or []:
            lines.append(f"{row[1]} <b>{_e(row[2])}</b> — {_e(row[3])}")
    elif kind == "list":
        lines.append(f"<b>{_e(screen.get('t'))}</b>" + (f" · {_e(screen.get('s'))}" if screen.get("s") else ""))
        for row in screen.get("i") or []:
            lines.append(f"{row[1]} {_e(row[2])}" + (f"\n    <i>{_e(row[3])}</i>" if row[3] else ""))
        if screen.get("pg"):
            lines.append(f"\n<i>{_e(screen['pg'])}</i>")
    elif kind == "card":
        lines.append(f"<b>{_e(screen.get('t'))}</b>")
        if screen.get("s"):
            lines.append(_e(screen["s"]))
        if screen.get("ch"):
            lines.append(" · ".join(_e(chip) for chip in screen["ch"]))
        if screen.get("d"):
            lines.append("")
            lines.append(_e(screen["d"]))
        for pair in screen.get("m") or []:
            lines.append(f"<b>{_e(pair[0])}:</b> {_e(pair[1])}")
    elif kind == "pass":
        lines.append(f"<b>{_e(screen.get('t'))}</b>")
        lines.append(_e(screen.get("s")))
        bar = "▰" * max(1, round((screen.get("pct") or 0) / 10)) + "▱" * max(0, 10 - round((screen.get("pct") or 0) / 10))
        lines.append(bar)
        for item in screen.get("st") or []:
            lines.append(f"{_e(item[0])} — {_e(item[1])}")
    elif kind == "route":
        lines.append(f"<b>{_e(screen.get('t'))}</b>")
        if screen.get("s"):
            lines.append(_e(screen["s"]))
        for item in screen.get("r") or []:
            lines.append(f"{item['i']} <b>{_e(item['t'])}</b> — {item['min']} мин · "
                         f"{str(item['km']).replace('.', ',')} км · {item['sc']}/100")

    if screen.get("n"):
        lines.append("")
        lines.append(f"<i>{_e(screen['n'])}</i>")
    return "\n".join(lines)[:3900]


def screen_buttons(screen: dict) -> dict:
    """Кнопки под текстом — те же действия, что в виджете."""
    rows: list[list[dict]] = []
    kind = screen.get("k")
    items = screen.get("i") or []

    if kind == "menu":
        for start in range(0, len(items), 2):
            rows.append([{"text": f"{item[1]} {item[2]}", "callback_data": "cb:" + item[0]}
                         for item in items[start:start + 2]])
    elif kind == "list":
        for item in items:
            rows.append([{"text": f"{item[1]} {item[2]}"[:60], "callback_data": "cb:" + item[0]}])
        pager = []
        if screen.get("prev"):
            pager.append({"text": "‹", "callback_data": "cb:" + screen["prev"]})
        if screen.get("next"):
            pager.append({"text": "›", "callback_data": "cb:" + screen["next"]})
        if pager:
            rows.append(pager)
    elif kind == "route":
        for index, item in enumerate(items):
            rows.append([{"text": f"{item['i']} {item['t']} · {item['min']} мин · {item['sc']}/100",
                          "callback_data": f"cb:rp:{index}"}])

    for button in screen.get("b") or []:
        rows.append([{"text": button[1], "callback_data": "cb:" + button[0]}])
    if not rows:
        rows.append([{"text": "‹ меню", "callback_data": "cb:m"}])
    return {"inline_keyboard": rows}


def show_fallback(token: str, chat_id: int, state: dict, screen: dict | None = None) -> int:
    """Отправляет экран обычным сообщением с кнопками и запоминает состояние."""
    reply = call("sendMessage", token, chat_id=chat_id,
                 text=screen_text(screen or build("m", state)),
                 parse_mode="HTML",
                 reply_markup=screen_buttons(screen or build("m", state)),
                 disable_web_page_preview=True)
    message_id = int((reply or {}).get("message_id") or 0)
    if message_id:
        SCREENS[(chat_id, message_id)] = state
    return message_id


def on_callback(token: str, callback: dict) -> None:
    """Нажатие обычной кнопки — когда виджеты недоступны."""
    data = str(callback.get("data") or "")
    chat_id = int((callback.get("message") or {}).get("chat", {}).get("id") or 0)
    message_id = int((callback.get("message") or {}).get("message_id") or 0)
    user = callback.get("from") or {}

    try:
        call("answerCallbackQuery", token, callback_query_id=callback["id"])
    except RuntimeError:
        pass

    if not data.startswith("cb:"):
        return

    state = SCREENS.get((chat_id, message_id)) or {
        "steps": [], "user": int(user.get("id") or 0), "name": _text(user.get("first_name")) or "гость"
    }
    SCREENS[(chat_id, message_id)] = state

    screen = build(data[3:], state)
    try:
        call("editMessageText", token, chat_id=chat_id, message_id=message_id,
             text=screen_text(screen), parse_mode="HTML",
             reply_markup=screen_buttons(screen), disable_web_page_preview=True)
    except RuntimeError as exc:
        if "not modified" not in str(exc).lower():
            print("не обновил сообщение:", exc)


# ────────────────────────────── обработчики ──────────────────────────────

def on_widget_query(token: str, query: dict) -> None:
    chat = query.get("chat") or {}
    chat_id = int(chat.get("id") or 0)
    message_id = int(query.get("message_id") or 0)
    user = query.get("from") or {}
    data = str(query.get("data") or "boot")

    state = SCREENS.get((chat_id, message_id))
    if not state:
        state = {"steps": [], "user": int(user.get("id") or 0), "name": _text(user.get("first_name")) or "гость"}
        SCREENS[(chat_id, message_id)] = state
    state["user"] = int(user.get("id") or state.get("user") or 0)

    try:
        screen = build(data, state)
        answer = fit(screen)
    except Exception as exc:  # noqa: BLE001 — виджет не должен зависать
        print("экран не собрался:", exc)
        answer = json.dumps({"k": "card", "t": "Что-то сломалось", "s": str(exc)[:60],
                             "b": [["m", "‹ меню"]]}, ensure_ascii=False)

    try:
        call("answerWidgetQuery", token, widget_query_id=query["id"], data=answer)
    except RuntimeError as exc:
        print("не ответил на запрос:", exc)

    try:
        call("editMessageWidgetData", token, chat_id=chat_id, message_id=message_id,
             chat_data=json.dumps({"k": data.split(":")[0]}, ensure_ascii=False, separators=(",", ":")))
    except RuntimeError:
        pass


def on_message(token: str, message: dict) -> None:
    chat_id = int((message.get("chat") or {}).get("id") or 0)
    user = message.get("from") or {}
    text = _text(message.get("text"))
    name = _text(user.get("first_name")) or "гость"

    if text.startswith("/start") or text in ("/help", "/меню", "/menu", "меню"):
        state = {"steps": [], "user": int(user.get("id") or 0), "name": name}
        try:
            message_id = send_widget(token, chat_id, state)
            SCREENS[(chat_id, message_id)] = state
        except WidgetsClosed as exc:
            print(f"виджеты этому боту недоступны ({exc}) — показываю обычными кнопками")
            show_fallback(token, chat_id, state)
        except (RuntimeError, ValueError) as exc:
            print(f"виджет не отправился ({exc}) — показываю обычными кнопками")
            show_fallback(token, chat_id, state)
        return

    if text.startswith("/паспорт") or text.startswith("/passport"):
        card = passport_of(int(user.get("id") or 0))
        xp = int(card.get("xp", 0))
        rank, _, nxt = rank_of(xp)
        left = "максимум" if nxt is None else f"{max(0, nxt - xp)} XP"
        send_message(token, chat_id,
                     f"Паспорт: {rank} · {xp} XP\n"
                     f"открыто мест: {card.get('opened', 0)} · маршрутов: {card.get('routes', 0)}\n"
                     f"до следующего звания: {left}")
        return

    found = CATALOG.search(text)
    if found:
        lines = [f"{item['icon']} {item['name']} — {item['kind']}" for item in found[:6]]
        send_message(token, chat_id, "Нашёл:\n" + "\n".join(lines) +
                     "\n\nОткрыть карточку: /start и нажми нужный раздел.")
        return

    send_message(token, chat_id, "Я тест-бот виджетов.\n/start — карточка со всеми разделами.\n"
                                 "Можно и текстом: напиши «кофе», «закат», «тропа».")


def poll(token: str) -> int:
    me = call("getMe", token)
    print(f"тест-бот виджетов: @{me.get('username')}")
    print(f"данные: еда {len(CATALOG.food)} · локации {len(CATALOG.places)} · "
          f"события {len(CATALOG.events)} · маршруты {len(CATALOG.routes)}")
    if CATALOG.error:
        print("таблица:", CATALOG.error)

    offset = 0
    while True:
        try:
            updates = call("getUpdates", token, offset=offset, timeout=30,
                           allowed_updates=["message", "widget_query", "callback_query"])
        except RuntimeError as exc:
            print("опрос не удался:", exc)
            time.sleep(3)
            continue
        for update in updates or []:
            offset = max(offset, int(update.get("update_id") or 0) + 1)
            try:
                if update.get("widget_query"):
                    on_widget_query(token, update["widget_query"])
                elif update.get("callback_query"):
                    on_callback(token, update["callback_query"])
                elif update.get("message"):
                    on_message(token, update["message"])
            except Exception as exc:  # noqa: BLE001
                print("ошибка:", type(exc).__name__, exc)


# ────────────────────────────── проверки без сети ──────────────────────────────

def all_screens() -> dict[str, dict]:
    state = {"steps": [], "user": 1, "name": "Ты"}
    screens = {}
    for action in ("boot", "c:food", "l:food:coffee:0", "c:places", "c:events", "c:routes", "pp"):
        screens[action] = build(action, dict(state))
    screens["card"] = build("o:" + CATALOG.food[0]["id"], {"steps": ["l:food:coffee:0"], "user": 1, "name": "Ты"})
    if CATALOG.places:
        screens["card_place"] = build("o:" + CATALOG.places[0]["id"], {"steps": ["c:places"], "user": 1, "name": "Ты"})
    return screens


def check() -> int:
    html = WIDGET_HTML.read_text(encoding="utf-8")
    raw = len(html.encode("utf-8"))
    packed = len(zlib.compress(html.encode("utf-8"), 9))
    problems = []
    if raw > 32768:
        problems.append(f"HTML {raw} > 32768")
    if packed > 4096:
        problems.append(f"сжатие {packed} > 4096")

    print(f"виджет: {raw} байт, после сжатия {packed} (лимиты 32768 / 4096)")
    if CATALOG.error:
        print("таблица:", CATALOG.error)

    for name, screen in all_screens().items():
        payload = fit(screen)
        size = len(payload.encode("utf-8"))
        mark = "ok " if size <= MAX_ANSWER else "ПЕРЕБОР"
        print(f"  {mark} {name:<16} {size:>4} байт · {screen.get('t','')[:34]}")
        if size > MAX_ANSWER:
            problems.append(f"{name}: {size}")

    return 1 if problems else 0


def preview(target: Path) -> int:
    """Собирает страницу, где виджет работает сам по себе — для браузера."""
    target.mkdir(parents=True, exist_ok=True)
    screens = all_screens()

    # заглушка вместо бота: отвечает заранее собранными экранами
    stub = {"boot": screens["boot"], "m": screens["boot"], "c:food": screens["c:food"],
            "l:food:coffee:0": screens["l:food:coffee:0"], "c:places": screens["c:places"],
            "c:events": screens["c:events"], "c:routes": screens["c:routes"], "pp": screens["pp"],
            "c:map": screens["boot"], "rp:0": screens["boot"], "rp:1": screens["boot"],
            "rp:2": screens["boot"]}
    for item in CATALOG.food[:6]:
        stub[f"o:{item['id']}"] = build(f"o:{item['id']}", {"steps": ["l:food:coffee:0"], "user": 1, "name": "Ты"})
    for item in CATALOG.places[:6]:
        stub[f"o:{item['id']}"] = build(f"o:{item['id']}", {"steps": ["c:places"], "user": 1, "name": "Ты"})
    for item in CATALOG.routes[:6]:
        stub[f"o:{item['id']}"] = build(f"o:{item['id']}", {"steps": ["c:routes"], "user": 1, "name": "Ты"})

    widget = WIDGET_HTML.read_text(encoding="utf-8")
    injection = (
        "<script>\n"
        "  window.TelegramWidget = { request: function (d) {\n"
        "    var map = " + json.dumps(stub, ensure_ascii=False) + ";\n"
        "    var screen = map[d] || map['boot'];\n"
        "    return Promise.resolve({ result: JSON.stringify(screen) });\n"
        "  } };\n"
        "</script>\n"
    )
    page = widget.replace("<div id=\"root\"></div>", injection + "<div id=\"root\"></div>")
    page = page.replace("min-height: 100vh;", "min-height: 100vh; max-width: 390px; margin: 0 auto;")
    page = page.replace("<body", "<body style=\"background:#0a0b09\"")
    (target / "widget_preview.html").write_text(page, encoding="utf-8")
    print(f"предпросмотр: {target / 'widget_preview.html'}")
    return 0


def main() -> int:
    if "--check" in sys.argv:
        return check()
    if "--preview" in sys.argv:
        index = sys.argv.index("--preview")
        folder = Path(sys.argv[index + 1]) if len(sys.argv) > index + 1 else BASE / "widgets"
        return preview(folder)

    token = (os.getenv("TG_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
    if ":" not in token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if token and not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{30,}", token):
        print("Это не похоже на токен: ожидаю 8123456789:AAH... (цифры, двоеточие, ~35 символов).\n"
              "Проверь, что в файл или переменную попал именно токен, а не имя секрета.\n")
    if ":" not in token:
        print("Нужен токен тестового бота.\n"
              "  Windows: положи его в widgets\\token.txt или запусти TESTBOT.bat\n"
              "  иначе:   set TG_TOKEN=123456:AA...")
        return 1
    try:
        poll(token)
    except KeyboardInterrupt:
        print("\nостановлен")
    except RuntimeError as exc:
        print(f"\nНе смог подключиться: {exc}")
        print("Проверь интернет и токен (widgets\\token.txt или TG_TOKEN).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
