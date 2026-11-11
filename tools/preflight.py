#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Проверка перед запуском: что уже готово, а чего не хватает.

Один взгляд — и понятно, можно ли стартовать завтра утром: есть ли Python
и библиотеки, заполнен ли .env, собраны ли данные карты, поднят ли Docker
и отвечает ли сервис.

Запуск:
    python tools/preflight.py          полная проверка
    python tools/preflight.py --wait-map 180   подождать, пока карта поднимется

Только стандартная библиотека: работает даже до pip install.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SERVICE_DIR = BASE_DIR / "alive-maps-service"
DATA_DIR = SERVICE_DIR / "data"
ENV_FILE = BASE_DIR / ".env"
MAP_URL = (os.getenv("ALIVE_MAP_URL") or "http://localhost:8080").rstrip("/")

OK, WARN, BAD = "ok", "warn", "bad"
MARKS = {OK: "[ok]", WARN: "[ !]", BAD: "[ x]"}

problems: list[str] = []
warnings: list[str] = []
oks = 0


def line(status: str, text: str) -> None:
    global oks
    if status == OK:
        oks += 1
    print(f"  {MARKS[status]:<5} {text}")


def section(title: str) -> None:
    print()
    print(title)


def fix(text: str) -> None:
    problems.append(text)


# ---------------- 1. python и библиотеки ----------------

def check_python() -> None:
    section("1. Python и библиотеки")
    version = ".".join(str(v) for v in sys.version_info[:3])
    if sys.version_info >= (3, 10):
        line(OK, f"Python {version}")
    else:
        line(BAD, f"Python {version} — нужен 3.10 или новее")
        fix("поставь Python 3.12 с python.org (галочка «Add to PATH»)")

    missing = []
    for module, package in (
        ("aiogram", "aiogram"),
        ("pandas", "pandas"),
        ("openpyxl", "openpyxl"),
        ("requests", "requests"),
        ("dotenv", "python-dotenv"),
    ):
        if importlib.util.find_spec(module) is None:
            missing.append(package)

    if not missing:
        line(OK, "библиотеки бота на месте")
    else:
        line(BAD, "не хватает: " + ", ".join(missing))
        fix("поставь библиотеки: python -m pip install -r requirements.txt")


# ---------------- 2. настройки ----------------

def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        values[key.strip()] = value.strip()
    return values


def mask(value: str) -> str:
    if len(value) <= 10:
        return "***"
    return value[:8] + "…" + value[-4:]


def check_env() -> None:
    section("2. Настройки бота (.env)")
    if not ENV_FILE.exists():
        line(BAD, "файла .env нет")
        fix("создай .env мастером: python tools/setup_env.py")
        return

    env = read_env()
    token = env.get("TG_TOKEN", "")
    admin = env.get("ADMIN_ID", "")

    if token and token != "123456789:AAABBBCCC" and ":" in token and len(token) > 30:
        line(OK, f"TG_TOKEN задан ({mask(token)})")
    else:
        line(BAD, "TG_TOKEN не заполнен")
        fix("токен от @BotFather → в .env (или запусти python tools/setup_env.py)")

    if admin.isdigit():
        line(OK, f"ADMIN_ID задан ({admin})")
    else:
        line(BAD, "ADMIN_ID не заполнен — не будет админки и заявок с формы")
        fix("свой ID у @userinfobot → ADMIN_ID=… в .env")

    if env.get("ALIVE_MAP_PUBLIC", "").startswith("https://"):
        line(OK, "публичный адрес карты задан — мини-апп можно включать")
    else:
        line(WARN, "ALIVE_MAP_PUBLIC пуст — карта пока только на этом компьютере")

    if env.get("ALIVE_MAP_URL"):
        line(OK, f"ALIVE_MAP_URL={env['ALIVE_MAP_URL']}")
    else:
        line(OK, "ALIVE_MAP_URL не задан — бот найдёт карту сам")


# ---------------- 3. данные карты ----------------

def human(size: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit in ("Б", "КБ") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ГБ"


def check_data() -> None:
    section("3. Данные карты")
    if not SERVICE_DIR.exists():
        line(BAD, "нет папки alive-maps-service")
        fix("скачай архив с GitHub и распакуй рядом с ботом")
        return

    missing_data: list[str] = []

    pbf = DATA_DIR / "sevastopol.osm.pbf"
    if pbf.exists():
        line(OK, f"данные OSM: {human(pbf.stat().st_size)}")
    else:
        line(WARN, "данных OSM ещё нет — скачаются при первом запуске")
        missing_data.append("OSM")

    zones = DATA_DIR / "zones.geojson"
    if zones.exists():
        try:
            count = len(json.loads(zones.read_text(encoding="utf-8"))["features"])
            line(OK, f"живые зоны: {count}")
        except (ValueError, KeyError, OSError):
            line(WARN, "zones.geojson есть, но читается странно")
    else:
        line(WARN, "живые зоны ещё не собраны — соберутся при первом запуске")
        missing_data.append("зоны")

    mbtiles = DATA_DIR / "sevastopol.mbtiles"
    if mbtiles.exists():
        line(OK, f"тайлы карты: {human(mbtiles.stat().st_size)}")
    else:
        line(WARN, "тайлы ещё не собраны — соберутся при первом запуске (3–10 мин)")
        missing_data.append("тайлы")

    fonts = DATA_DIR / "fonts"
    faces = len([p for p in fonts.iterdir() if p.is_dir()]) if fonts.exists() else 0
    if faces:
        line(OK, f"шрифты для подписей: {faces}")
    else:
        line(WARN, "шрифтов нет — карта будет без подписей")

    pois = DATA_DIR / "pois.geojson"
    if pois.exists():
        try:
            count = len(json.loads(pois.read_text(encoding="utf-8"))["features"])
            line(OK, f"мои места из базы: {count}")
        except (ValueError, KeyError, OSError):
            line(WARN, "pois.geojson есть, но читается странно")
    else:
        line(WARN, "нет pois.geojson — маршруты будут только по OSM")


    if missing_data:
        warnings.append("данных карты ещё нет: " + ", ".join(missing_data)
                        + " — start.bat соберёт их при первом запуске")


# ---------------- 4. Docker ----------------

def run(cmd: list[str], timeout: float = 8.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (FileNotFoundError, subprocess.SubprocessError):
        return 127, ""


def check_docker() -> None:
    section("4. Docker")
    if shutil.which("docker") is None and shutil.which("podman") is None:
        line(BAD, "ни Docker, ни Podman не найдены")
        fix("поставь Docker Desktop (или Podman Desktop) и перезагрузи компьютер")
        return

    engine = "docker" if shutil.which("docker") else "podman"
    code, out = run([engine, "--version"])
    if code == 0:
        line(OK, out.strip().splitlines()[0] if out.strip() else engine)
    else:
        line(BAD, f"{engine} не отвечает")
        fix(f"перезапусти {engine} Desktop")

    code, out = run([engine, "info"])
    if code == 0:
        line(OK, "движок запущен")
    else:
        line(BAD, "движок не запущен")
        fix(f"открой {engine} Desktop и дождись «Engine running»")

    code, _ = run([engine, "compose", "version"])
    if code == 0:
        line(OK, "docker compose есть")
    else:
        line(BAD, "нет docker compose")
        fix("обнови Docker Desktop — compose идёт в комплекте")


# ---------------- 5. сервис карты ----------------

def http_json(url: str, timeout: float = 3.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status >= 400:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError):
        return None


def check_service(wait: float = 0.0) -> None:
    section("5. Сервис карты")
    if wait > 0:
        print(f"  ждём карту на {MAP_URL} (до {wait:.0f} с)…")
        deadline = time.time() + wait
        while time.time() < deadline:
            if http_json(f"{MAP_URL}/health", timeout=2.0):
                break
            print("  …", end="", flush=True)
            time.sleep(3)
        print()

    health = http_json(f"{MAP_URL}/api/health")
    if not health:
        line(WARN, f"ещё не запущен на {MAP_URL} — RUN.bat поднимет его сам")
        return

    line(OK, f"сервис отвечает: {MAP_URL}")
    zones = health.get("zones") or 0
    own = health.get("own") or 0
    gh = (health.get("graphhopper") or {})
    line(OK, f"зон: {zones} · моих мест: {own}")
    if gh.get("ok"):
        line(OK, "GraphHopper готов считать маршруты")
    else:
        line(WARN, "GraphHopper ещё импортирует граф (1–3 минуты после старта)")


# ---------------- итог ----------------

def main() -> int:
    wait = 0.0
    args = sys.argv[1:]
    if "--wait-map" in args:
        try:
            wait = float(args[args.index("--wait-map") + 1])
        except (IndexError, ValueError):
            wait = 120.0

    print("Sevastopol AI — проверка перед запуском")
    print(f"папка: {BASE_DIR}")

    check_python()
    check_env()
    check_data()
    check_docker()
    check_service(wait)

    print()
    print("─" * 56)
    if problems:
        print(f"готово: {oks} ок · проблем: {len(problems)}")
        print()
        print("что сделать:")
        seen: set[str] = set()
        idx = 0
        for item in problems:
            if item in seen:
                continue
            seen.add(item)
            idx += 1
            print(f"  {idx}. {item}")
        return 1

    if warnings:
        print(f"готово: {oks} ок · замечаний: {len(warnings)} — запускать можно")
        for item in warnings:
            print(f"  · {item}")
    else:
        print(f"готово: {oks} ок · всё на месте, можно запускать")
    print()
    print("запуск: RUN.bat (Windows) — поднимет карту и бота разом")
    return 0


if __name__ == "__main__":
    sys.exit(main())
