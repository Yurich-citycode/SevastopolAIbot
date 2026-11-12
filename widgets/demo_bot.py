#!/usr/bin/env python3
"""Пробная копия бота на HTML-виджетах (Bot API 10.4).

Что это
-------
Виджет — это маленький HTML прямо внутри сообщения. Он рисуется в песочнице
Telegram и умеет ровно одно: спросить бота через TelegramWidget.request(...).
Бот отвечает answerWidgetQuery, и виджет перерисовывается — без новых сообщений
в чате. Здесь так показываются три маршрута: нажал строку — она подсветилась,
цифры остались в том же сообщении.

Почему отдельный файл, а не бот
-------------------------------
Библиотека aiogram Bot API 10.4 пока не знает (issue #2006), поэтому здесь
прямые вызовы API через requests. Рабочий sevastopolaibot.py не тронут: если
эксперимент не понравится — этот файл просто не запускается.

Запуск
------
    set TG_TOKEN=...           (Windows)
    export TG_TOKEN=...        (macOS/Linux)
    python widgets/demo_bot.py

    python widgets/demo_bot.py --check     только проверить размеры виджета

Нужен отдельный тестовый бот: виджеты живут только в личных чатах, и мешать
основному боту незачем.

Ограничения Telegram, под которые подогнан код:
  * HTML до 32 КБ, после сжатия zlib (уровень 9) — до 4 КБ;
  * запрос из виджета 1–64 байта, ответ бота до 1024 байт;
  * ответить надо за 15 секунд, иначе виджет покажет TIMEOUT;
  * не больше 5 запросов за 5 секунд от одного человека;
  * отправка только в личные чаты.
"""

from __future__ import annotations

import json
import os
import sys
import time
import zlib
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
WIDGET = Path(__file__).resolve().parent / "alive_widget.html"
POIS = ROOT / "alive-maps-service" / "data" / "pois.geojson"

API_BASE = "https://api.telegram.org/bot{token}/{method}"
MAP_URL = (os.getenv("ALIVE_MAP_URL") or "http://localhost:8080").rstrip("/")
TIMEOUT = 25

MAX_HTML = 32_768
MAX_PACKED = 4_096
MAX_ANSWER = 1_024

# что помним про открытый виджет: чат+сообщение → маршруты и выбор
screens: dict[tuple[int, int], dict] = {}
# чат → куда идём (место из базы + координаты)
pending: dict[int, dict] = {}


# ────────────────────────────── Telegram ──────────────────────────────

def call(method: str, token: str, **params):
    """Один вызов Bot API. Возвращает result или бросает RuntimeError."""
    url = API_BASE.format(token=token, method=method)
    try:
        resp = requests.post(url, json=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise RuntimeError(f"{method}: нет связи ({exc})") from exc
    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"{method}: ответ не JSON") from exc
    if not payload.get("ok"):
        raise RuntimeError(f"{method}: {payload.get('description')}")
    return payload.get("result")


def say(token: str, chat_id: int, text: str, **extra) -> None:
    call("sendMessage", token, chat_id=chat_id, text=text, **extra)


# ────────────────────────────── данные ──────────────────────────────

def load_places() -> list[dict]:
    if not POIS.exists():
        return []
    data = json.loads(POIS.read_text(encoding="utf-8"))
    out = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        lon, lat = geometry["coordinates"][:2]
        props = feature.get("properties") or {}
        out.append({
            "name": str(props.get("name") or "").strip(),
            "kind": props.get("kind"),
            "lon": lon,
            "lat": lat,
        })
    return [item for item in out if item["name"]]


def find_place(query: str, places: list[dict]) -> dict | None:
    needle = query.strip().lower().replace("ё", "е")
    if len(needle) < 2:
        return None
    for place in places:
        if needle in place["name"].lower().replace("ё", "е"):
            return place
    return None


def build_routes(start_lat: float, start_lon: float, place: dict) -> dict | None:
    """Три маршрута из сервиса карты в коротком виде, как их ждёт виджет."""
    try:
        resp = requests.post(
            f"{MAP_URL}/api/compare",
            json={"start": [start_lon, start_lat], "end": [place["lon"], place["lat"]]},
            timeout=TIMEOUT,
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None

    picked = []
    for key, title in (("fast", "fast"), ("alive", "alive"), ("most_alive", "most")):
        route = data.get(key) or {}
        if not route:
            continue
        picked.append({
            "key": title,
            "minutes": round(float(route.get("time_s") or 0) / 60),
            "km": round(float(route.get("distance_m") or 0) / 1000, 1),
            "score": int(((route.get("score") or {}).get("score")) or 0),
        })
    if not picked:
        return None
    return {"place": place["name"], "routes": picked, "selected": 1 if len(picked) > 1 else 0}


def render(state: dict) -> str:
    """HTML виджета с вшитыми данными: ничего не надо читать при загрузке."""
    template = WIDGET.read_text(encoding="utf-8")
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    html = template.replace("__DATA__", payload)
    packed = len(zlib.compress(html.encode("utf-8"), 9))
    if len(html.encode("utf-8")) > MAX_HTML or packed > MAX_PACKED:
        raise ValueError(f"виджет великоват: {len(html.encode('utf-8'))} байт, после сжатия {packed}")
    return html


# ────────────────────────────── сценарий ──────────────────────────────

def show_widget(token: str, chat_id: int, state: dict) -> None:
    message = call(
        "sendWidget", token,
        chat_id=chat_id,
        html=render(state),
        caption="Нажми строку — маршрут останется в этом же сообщении",
        allow_queries=True,
        height=250,
    )
    message_id = int((message or {}).get("message_id") or 0)
    if message_id:
        screens[(chat_id, message_id)] = state


def handle_query(token: str, query: dict) -> None:
    """Нажатие внутри виджета: подсветить выбранный маршрут."""
    chat = query.get("chat") or {}
    chat_id = int(chat.get("id") or 0)
    message_id = int(query.get("message_id") or 0)
    data = str(query.get("data") or "")

    state = screens.get((chat_id, message_id))
    if not state:
        call("answerWidgetQuery", token, widget_query_id=query["id"], data="")
        return

    if data.startswith("pick:"):
        try:
            index = int(data.split(":", 1)[1])
        except ValueError:
            index = state["selected"]
        if 0 <= index < len(state["routes"]):
            state["selected"] = index

    try:
        answer = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        if len(answer.encode("utf-8")) > MAX_ANSWER:
            answer = ""
        call("answerWidgetQuery", token, widget_query_id=query["id"], data=answer)
    except RuntimeError as exc:
        print("не ответил на запрос:", exc)

    # состояние сообщения тоже обновляем: если человек вернётся к нему позже
    try:
        call("editMessageWidgetData", token, chat_id=chat_id, message_id=message_id,
             chat_data=json.dumps({"selected": state["selected"]}))
    except RuntimeError:
        pass


def handle_message(token: str, message: dict, places: list[dict]) -> None:
    chat = message.get("chat") or {}
    chat_id = int(chat.get("id") or 0)
    text = (message.get("text") or "").strip()
    location = message.get("location")

    if location:
        target = pending.get(chat_id)
        if not target:
            say(token, chat_id, "Сначала скажи, куда идём: /map музей")
            return
        state = build_routes(location["latitude"], location["longitude"], target)
        if not state:
            say(token, chat_id, "Карта не ответила. Проверь, что сервис запущен на "
                               f"{MAP_URL} (start.bat в alive-maps-service).")
            return
        try:
            show_widget(token, chat_id, state)
        except (RuntimeError, ValueError) as exc:
            say(token, chat_id, f"Виджет не отправился: {exc}")
        pending.pop(chat_id, None)
        return

    if text.startswith("/start") or text.startswith("/help"):
        say(token, chat_id,
            "Это проба виджетов Bot API 10.4.\n\n"
            "/map музей — выбери место и скинь геопозицию.\n"
            "Дальше появится карточка с тремя маршрутами: нажимай строки прямо в сообщении.")
        return

    if text.startswith("/map"):
        query = text[4:].strip()
        if not query:
            say(token, chat_id, "Напиши место: /map музей или /map кофе")
            return
        place = find_place(query, places)
        if not place:
            say(token, chat_id, f"В базе нет «{query}». Попробуй иначе: музей, кофе, пляж.")
            return
        pending[chat_id] = place
        say(token, chat_id, f"До «{place['name']}». Скинь геопозицию 📎 — покажу три маршрута.")
        return

    say(token, chat_id, "Я понимаю /start, /help и /map <место>.")


def poll(token: str) -> int:
    places = load_places()
    print(f"мест в базе: {len(places)} · карта: {MAP_URL}")
    me = call("getMe", token)
    print(f"бот: @{me.get('username')} — жду сообщения")

    offset = 0
    while True:
        try:
            updates = call("getUpdates", token, offset=offset, timeout=30,
                           allowed_updates=["message", "widget_query"])
        except RuntimeError as exc:
            print("опрос не удался:", exc)
            time.sleep(3)
            continue

        for update in updates or []:
            offset = max(offset, int(update.get("update_id") or 0) + 1)
            try:
                if update.get("widget_query"):
                    handle_query(token, update["widget_query"])
                elif update.get("message"):
                    handle_message(token, update["message"], places)
            except RuntimeError as exc:
                print("ошибка обработки:", exc)
            except Exception as exc:  # noqa: BLE001 — проба не должна падать целиком
                print("непредвиденное:", type(exc).__name__, exc)


def check() -> int:
    """Проверка без сети: влезает ли виджет в лимиты Telegram."""
    state = {"place": "Балаклавский подземный музейный комплекс",
             "routes": [{"key": "fast", "minutes": 33, "km": 2.7, "score": 42},
                        {"key": "alive", "minutes": 38, "km": 3.0, "score": 71},
                        {"key": "most", "minutes": 47, "km": 3.8, "score": 86}],
             "selected": 1}
    html = render(state)
    raw = len(html.encode("utf-8"))
    packed = len(zlib.compress(html.encode("utf-8"), 9))
    answer = len(json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    print(f"HTML: {raw} байт (лимит {MAX_HTML})")
    print(f"после сжатия: {packed} байт (лимит {MAX_PACKED})")
    print(f"ответ виджету: {answer} байт (лимит {MAX_ANSWER})")
    ok = raw <= MAX_HTML and packed <= MAX_PACKED and answer <= MAX_ANSWER
    print("итог:", "влезает" if ok else "НЕ влезает")
    return 0 if ok else 1


def main() -> int:
    if "--check" in sys.argv:
        return check()

    token = (os.getenv("TG_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
    if not token or ":" not in token:
        print("Нужен токен тестового бота: set TG_TOKEN=123456:AA... (или export)")
        return 1
    try:
        return poll(token)
    except KeyboardInterrupt:
        print("\nостановлен")
        return 0


if __name__ == "__main__":
    sys.exit(main())
