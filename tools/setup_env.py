#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Мастер первого запуска: создаёт .env с правами 600 и проверяет токен у Telegram.

Запуск:  python tools/setup_env.py
Спрашивает токен от @BotFather и ADMIN_ID от @userinfobot, кладёт их в .env
рядом с ботом и проверяет токен запросом getMe. Используется только стандартная
библиотека Python — скрипт работает до установки зависимостей.
"""

import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = Path(os.environ.get("ENV_FILE") or (BASE_DIR / ".env"))
EXAMPLE_FILE = BASE_DIR / ".env.example"

PLACEHOLDERS = {
    "",
    "123456789:AAABBBCCC",
    "123456789:AAH...",
    "вставь_сюда",
    "your_token_here",
}
TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")
KEEP_WORDS = {"оставить", "оставляю", "оставь", "keep", "да", "yes", "y", "д"}
NEW_WORDS = {"новый", "новый токен", "new", "заменить", "нет", "no", "n", "н"}

DEFAULTS = [
    "TG_TOKEN=123456789:AAABBBCCC",
    "ADMIN_ID=",
    "SPREADSHEET_ID=1RaHoS_8Ov-kNKSZJK015ceC6H3fsWnW-D-8Yee4ckQI",
    "NEWS_CHANNEL_URL=https://t.me/Sevastopol_AI",
    "SUGGEST_FORM_URL=https://yurich-citycode.github.io/SevastopolAIbot/suggest.html",
    "REFRESH_SECONDS=600",
    "STATE_FILE=bot_state.json",
]


def say(text=""):
    print(text)


def read_lines(path):
    if path.exists():
        return path.read_text(encoding="utf-8").splitlines()
    return list(DEFAULTS)


def parse_env(lines):
    env, order = {}, []
    for line in lines:
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            env[key] = value.strip()
            order.append(key)
    return env, order


def mask(value):
    if len(value) <= 12:
        return "…"
    return value[:6] + "…" + value[-4:]


def looks_like_token(value):
    return bool(TOKEN_RE.match((value or "").strip()))


def is_placeholder(value):
    return (value or "").strip() in PLACEHOLDERS


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def ask_hidden(prompt):
    try:
        return getpass.getpass(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        say()
        return ""


def ask_new_token():
    while True:
        value = ask_hidden("Вставь токен от @BotFather (ввод не отображается): ").strip().strip("'\"")
        if is_placeholder(value):
            say("  ⚠️ Это заглушка из шаблона, а не настоящий токен. Нужна строка вида 123456789:AAH…")
            continue
        if not looks_like_token(value):
            say("  ⚠️ Не похоже на токен: он выглядит как 123456789:AAH-длинная-строка. Попробуй ещё раз.")
            continue
        return value


def pick_token(current):
    if looks_like_token(current):
        say(f"В .env уже есть токен: {mask(current)}")
        answer = ask("Оставить прежний токен или ввести новый? (Enter — оставить, «новый» — ввести, или сразу вставь токен): ")
        if looks_like_token(answer):
            return answer.strip().strip("'\"")
        if answer == "" or answer.lower() in KEEP_WORDS:
            return current
        if answer.lower() in NEW_WORDS:
            return ask_new_token()
        say("  ⚠️ Не понял ответ — считаю, что токен нужно ввести заново.")
        return ask_new_token()
    say("Токена пока нет. Возьми его у @BotFather: /mybots → твой бот → API Token.")
    return ask_new_token()


def pick_admin(current):
    if current and current.isdigit():
        say(f"В .env уже есть ADMIN_ID: {current}")
        answer = ask("Оставить его? (Enter — оставить или сразу вставь новый ID): ").strip()
        if answer == "" or answer.lower() in KEEP_WORDS:
            return current
        if answer.isdigit():
            return answer
        say("  ⚠️ ADMIN_ID — это только цифры (например 6106999216). Оставляю прежний.")
        return current
    say("Свой ADMIN_ID можно узнать у @userinfobot: нажми Start — он пришлёт число.")
    while True:
        answer = ask("ADMIN_ID (можно оставить пустым): ").strip()
        if answer == "":
            return ""
        if answer.isdigit():
            return answer
        say("  ⚠️ Нужны только цифры, например 6106999216")


def write_env(env, order, path):
    lines = read_lines(EXAMPLE_FILE)
    out, seen = [], set()
    for line in lines:
        if line.strip().startswith("#") or "=" not in line:
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in env:
            out.append(f"{key}={env[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key in order:
        if key not in seen and key in env:
            out.append(f"{key}={env[key]}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def telegram_error(error):
    try:
        data = json.loads(error.read().decode("utf-8", "replace"))
        return data.get("description") or f"HTTP {error.code}"
    except Exception:
        return f"HTTP {error.code}"


def check_token(token):
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        say(f"❌ Telegram не принял токен: {telegram_error(error)}")
        say("   Возьми новый: @BotFather → /mybots → твой бот → API Token (или Revoke).")
        return False
    except Exception as error:
        say(f"⚠️ Не удалось проверить токен — похоже, нет интернета ({error}).")
        say("   Токен сохранён, он проверится при первом запуске бота.")
        return True
    if data.get("ok"):
        bot = data.get("result", {})
        username = bot.get("username", "")
        name = bot.get("first_name", "")
        say(f"✅ Токен рабочий: @{username}" + (f" ({name})" if name else ""))
        return True
    say(f"❌ Telegram ответил отказом: {data.get('description')}")
    return False


def main():
    say("=== Sevastopol AI: настройка окружения ===")
    say(f"Файл настроек: {ENV_FILE}")
    say()

    source = ENV_FILE if ENV_FILE.exists() else EXAMPLE_FILE
    env, order = parse_env(read_lines(source))

    token = pick_token(env.get("TG_TOKEN", ""))
    say()
    admin = pick_admin(env.get("ADMIN_ID", ""))
    say()

    env["TG_TOKEN"] = token
    env["ADMIN_ID"] = admin
    for key in ("SPREADSHEET_ID", "NEWS_CHANNEL_URL", "SUGGEST_FORM_URL", "REFRESH_SECONDS", "STATE_FILE"):
        env.setdefault(key, "")
    write_env(env, order, ENV_FILE)
    say(f"Файл .env записан с правами 600: {ENV_FILE}")
    say()

    ok = check_token(token)
    say()
    if ok:
        say("Дальше: запусти бота — python sevastopolaibot.py")
        say("Подробная инструкция: START_HERE.md")
    else:
        say("Проверь токен и запусти мастер ещё раз: python tools/setup_env.py")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
