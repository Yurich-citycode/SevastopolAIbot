# -*- coding: utf-8 -*-
"""Проверка базы «Sevastopol AI База.xlsx» перед публикацией в Google Sheets.

Находит то, из-за чего бот показывает кривые карточки: пустые строки,
дубликаты, битые координаты, ссылки не-картинки в поле фото, даты в прошлом,
слишком длинные описания (лимит Telegram 4096 / подпись фото 1024),
неизвестные категории и шапки колонок с латинской «B».

Запуск из корня репозитория:
    python tools/check_base.py
Код возврата 1 — найдены ошибки, 0 — база чистая.
"""

import os
import sys
from datetime import datetime

import openpyxl

XLSX = "Sevastopol AI База.xlsx"

# Границы Севастополя с запасом: координаты вне них — почти всегда опечатка
LAT_MIN, LAT_MAX = 44.30, 44.75
LON_MIN, LON_MAX = 33.20, 33.90

FOOD_CATEGORIES = {"Кофе", "Рестораны", "Кафе", "Пекарни", "Кондитерские", "Доставки"}
LOC_CATEGORIES = {"Пляжи", "Смотровые", "Закаты", "Hidden Gems", "Прогулки", "Достопримечательности", "Музеи"}
ROUTE_CATEGORIES = {"Пешие", "Велосипед", "Авто", "Вода"}

URL_COLS = ("Ссылка на фото", "Сайт", "Вконтакте", "Telegram", "Instagram", "Ссылка на карту", "Купить", "Ссылка на афишу")

CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096

problems = 0
warnings = 0


def err(msg):
    global problems
    problems += 1
    print("  ❌ " + msg)


def warn(msg):
    global warnings
    warnings += 1
    print("  ⚠️ " + msg)


def ok(msg):
    print("  ✅ " + msg)


def rows_of(ws):
    """(номер строки, {заголовок: значение}) — только строки с непустым «Название»."""
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    out = []
    for r in range(2, ws.max_row + 1):
        values = {h: ws.cell(r, c).value for c, h in enumerate(headers, 1) if h}
        out.append((r, values))
    return headers, out


def clean(v):
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def check_headers(headers, sheet):
    """Латинская «B» вместо кириллической «В» — бот такое читает, но шапка должна быть чистой."""
    for h in headers:
        if isinstance(h, str) and h.startswith("B") and any("\u0400" <= ch <= "\u04FF" for ch in h[1:]):
            warn(f"«{sheet}»: в шапке «{h}» первая буква латинская, должно быть «В{h[1:]}»")


def check_coords(sheet, r, row):
    coords = clean(row.get("Координаты"))
    if not coords:
        warn(f"«{sheet}» строка {r} «{clean(row.get('Название'))}»: нет координат (не будет кнопки карты)")
        return
    if "," not in coords:
        err(f"«{sheet}» строка {r} «{clean(row.get('Название'))}»: координаты без запятой: {coords!r}")
        return
    try:
        lat, lon = (float(x.strip()) for x in coords.split(",", 1))
    except ValueError:
        err(f"«{sheet}» строка {r} «{clean(row.get('Название'))}»: координаты не числа: {coords!r}")
        return
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        err(f"«{sheet}» строка {r} «{clean(row.get('Название'))}»: координаты вне Севастополя: {coords!r}")


def check_urls(sheet, r, row):
    for col in URL_COLS:
        value = clean(row.get(col))
        if not value:
            continue
        if not value.startswith(("http://", "https://")):
            err(f"«{sheet}» строка {r}: {col} = {value!r} — нужен полный http(s)-адрес")
        elif col == "Ссылка на фото" and any(d in value for d in ("t.me", "telegram.me", "telegram.dog")):
            warn(
                f"«{sheet}» строка {r} «{clean(row.get('Название'))}»: фото указано ссылкой на пост "
                f"({value}) — картинкой не покажется, нужен прямой адрес файла"
            )


def check_length(sheet, r, row, has_photo):
    name = clean(row.get("Название")) or "Без названия"
    desc = clean(row.get("Описание"))
    limit = CAPTION_LIMIT if has_photo else TEXT_LIMIT
    if len(desc) > limit - 200:
        where = "подпись к фото (1024)" if has_photo else "текст (4096)"
        warn(f"«{sheet}» строка {r} «{name}»: описание {len(desc)} симв. — бот обрежет его под {where}")


# ─────────────────────────── Где поесть ───────────────────────────

def check_menu_formula(ws):
    """Колонка «Меню Справочник» тянет меню XLOOKUP'ом — проверяем, что формулы живы."""
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    if "Меню Справочник" not in headers:
        warn("нет колонки «Меню Справочник» — меню к заведениям не подтягивается")
        return
    col = headers.index("Меню Справочник") + 1
    formulas, broken = 0, []
    for r in range(2, ws.max_row + 1):
        if not clean(ws.cell(r, 3).value):
            continue                      # пустая строка — формула не нужна
        v = ws.cell(r, col).value
        text = getattr(v, "text", v)
        if text and str(text).startswith("="):
            formulas += 1
            if "Меню Справочник" not in str(text):
                broken.append(r)
    if broken:
        err(f"в строках {broken[:5]} формула меню не ссылается на «Меню Справочник»")
    if formulas == 0:
        warn("в колонке «Меню Справочник» нет формул — меню подтягиваться не будет")
    else:
        print(f"  ✅ формул XLOOKUP в колонке «Меню Справочник»: {formulas}")


def check_food(ws, ws_formulas):
    print("\n== Где поесть ==")
    headers, rows = rows_of(ws)
    check_headers(headers, "Где поесть")
    check_menu_formula(ws_formulas)

    filled, seen = 0, {}
    for r, row in rows:
        name, addr = clean(row.get("Название")), clean(row.get("Адрес"))
        if not name:
            continue
        filled += 1
        cat = clean(row.get("Категория"))
        if cat not in FOOD_CATEGORIES:
            err(f"строка {r} «{name}»: неизвестная категория «{cat}» (ожидалось: {', '.join(sorted(FOOD_CATEGORIES))})")
        if not addr:
            warn(f"строка {r} «{name}»: не заполнен адрес")
        key = (name.lower(), addr.lower())
        if key in seen:
            err(f"строка {r} «{name}»: дубликат строки {seen[key]} (то же название и адрес)")
        else:
            seen[key] = r
        check_coords("Где поесть", r, row)
        check_urls("Где поесть", r, row)
        check_length("Где поесть", r, row, has_photo=bool(clean(row.get("Ссылка на фото"))))
    ok(f"заведений: {filled}")
    return filled


# ─────────────────────────── Локации / Маршруты ────────────────────

def check_locations(ws):
    print("\n== Локации ==")
    headers, rows = rows_of(ws)
    check_headers(headers, "Локации")
    filled, seen = 0, {}
    for r, row in rows:
        name = clean(row.get("Название"))
        if not name:
            continue
        filled += 1
        cat = clean(row.get("Категория"))
        if cat not in LOC_CATEGORIES:
            err(f"строка {r} «{name}»: неизвестная категория «{cat}»")
        if name.lower() in seen:
            err(f"строка {r} «{name}»: дубликат строки {seen[name.lower()]}")
        else:
            seen[name.lower()] = r
        check_coords("Локации", r, row)
        check_urls("Локации", r, row)
        check_length("Локации", r, row, has_photo=bool(clean(row.get("Ссылка на фото"))))
    ok(f"локаций: {filled}")
    return filled


def check_routes(ws):
    print("\n== Маршруты ==")
    headers, rows = rows_of(ws)
    check_headers(headers, "Маршруты")
    filled, seen = 0, {}
    for r, row in rows:
        name = clean(row.get("Название"))
        if not name:
            continue
        filled += 1
        cat = clean(row.get("Категория"))
        if cat not in ROUTE_CATEGORIES:
            err(f"строка {r} «{name}»: неизвестная категория «{cat}»")
        if name.lower() in seen:
            err(f"строка {r} «{name}»: дубликат строки {seen[name.lower()]}")
        else:
            seen[name.lower()] = r
        check_urls("Маршруты", r, row)
        check_length("Маршруты", r, row, has_photo=bool(clean(row.get("Ссылка на фото"))))
    ok(f"маршрутов: {filled}")
    return filled


# ─────────────────────────────── События ──────────────────────────

def parse_date(raw):
    s = clean(raw)
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.strptime(s[:10], "%d.%m.%Y").date()
    except ValueError:
        return None


def check_events(ws):
    print("\n== События ==")
    headers, rows = rows_of(ws)
    check_headers(headers, "События")
    today = datetime.now().date()
    filled, past, upcoming = 0, 0, 0
    for r, row in rows:
        name = clean(row.get("Название"))
        if not name:
            continue
        filled += 1
        d = parse_date(row.get("Дата"))
        if d is None:
            err(f"строка {r} «{name}»: дата не читается: {row.get('Дата')!r} (нужен формат ДД.ММ.ГГГГ)")
        elif d < today:
            past += 1
            warn(f"строка {r} «{name}»: дата {d} уже прошла — бот событие не покажет")
        else:
            upcoming += 1
        if not clean(row.get("Место")):
            warn(f"строка {r} «{name}»: не заполнено место")
        check_urls("События", r, row)
    ok(f"событий: {filled} (предстоящих: {upcoming}, прошедших: {past})")
    if upcoming == 0:
        err("нет ни одного предстоящего события — раздел «📅 События» будет пустым")
    return filled, upcoming


# ───────────────────────────────── main ───────────────────────────

def main():
    if not os.path.exists(XLSX):
        print(f"❌ Файл {XLSX!r} не найден. Запусти из корня репозитория.")
        return 1

    wb = openpyxl.load_workbook(XLSX, data_only=True)          # значения
    wb_f = openpyxl.load_workbook(XLSX, data_only=False)       # формулы
    required = ["Где поесть", "Локации", "Маршруты", "События"]
    for sheet in required:
        if sheet not in wb.sheetnames:
            err(f"нет вкладки «{sheet}»")
    if problems:
        return 1

    # Служебные вкладки бот не читает, но они нужны проекту: «Меню Справочник» —
    # источник для XLOOKUP в колонке P листа «Где поесть», остальные — под аналитику.
    service = [s for s in wb.sheetnames if s not in required]
    if service:
        print("\n== Служебные вкладки (бот их не читает) ==")
        for s in service:
            print(f"  · {s}")

    food = check_food(wb["Где поесть"], wb_f["Где поесть"])
    locs = check_locations(wb["Локации"])
    routes = check_routes(wb["Маршруты"])
    events, upcoming = check_events(wb["События"])

    print("\n== Пустые строки (бот их игнорирует, можно не трогать) ==")
    for sheet, name_col in (("Где поесть", 3), ("Локации", 2), ("Маршруты", 2), ("События", 4)):
        ws = wb[sheet]
        empty = sum(1 for r in range(2, ws.max_row + 1) if not clean(ws.cell(r, name_col).value))
        if empty:
            print(f"  · «{sheet}»: {empty} строк без названия (строки {ws.max_row - empty + 1}–{ws.max_row})")

    print("\n== Итог ==")
    print(f"  заведений: {food} · локаций: {locs} · маршрутов: {routes} · событий: {events} ({upcoming} предстоящих)")
    print(f"  ошибок: {problems} · предупреждений: {warnings}")
    if problems:
        print("  ❌ Базу нужно поправить — ошибки выше.")
        return 1
    print("  ✅ База в порядке." if warnings == 0 else "  ✅ Ошибок нет, предупреждения — на твоё усмотрение.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
