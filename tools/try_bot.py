#!/usr/bin/env python3
"""Потыкать бота прямо в терминале: без Telegram, без интернета, без Docker.

Зачем: проверить, что кнопки и команды отвечают так, как задумано, не заходя
в мессенджер и не создавая токен. Всё, что бот отправил бы человеку, здесь
печатается в консоль.

Как запускать (из папки с ботом):

    python tools/try_bot.py                 # интерактивно: пиши как в чат
    python tools/try_bot.py /start /menu    # сразу прогнать список сообщений
    echo "/start" | python tools/try_bot.py # из файла или пайпа

Что можно писать:
    /start, /help, /route Фиолент, любой текст — как обычное сообщение;
    !<callback_data>                        — нажать кнопку, например !alive:panel
    @44.6134,33.5225                        — отправить геопозицию

Важно: настоящий бот при этом не запускается, настоящая переписка не трогается.
Состояние пишется во временный файл и удаляется при выходе, чтобы не портить
рабочий bot_state.json.
"""

from __future__ import annotations

import asyncio
import html
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# значения по умолчанию — только для локального прогона, настоящие не нужны
os.environ.setdefault("TG_TOKEN", "123456789:ЛОКАЛЬНЫЙ-ПРОГОН-БЕЗ-TELEGRAM")
os.environ.setdefault("ADMIN_ID", "1")
if not os.getenv("STATE_FILE"):
    os.environ["STATE_FILE"] = str(Path(tempfile.mkdtemp(prefix="try-bot-")) / "state.json")
os.environ.setdefault("ALIVE_MAP_URL", os.getenv("ALIVE_MAP_URL", "http://localhost:8080"))


def _fill_cache(bot_module) -> None:
    """Набивает кэш из локальной таблицы, чтобы места искались без интернета.

    В обычной работе кэш приходит из Google Sheets. Здесь сети нет, поэтому
    берём тот же xlsx, что лежит рядом с ботом.
    """
    xlsx = ROOT / "Sevastopol AI База.xlsx"
    if not xlsx.exists():
        print("   (нет файла «Sevastopol AI База.xlsx» — поиск мест работать не будет)")
        return
    try:
        import pandas as pd

        excel = pd.ExcelFile(xlsx)
        sheets = {name.strip(): name for name in excel.sheet_names}
        pairs = (
            ("Где поесть", ("Где поесть?", "Где поесть")),
            ("Локации", ("Локации",)),
            ("Маршруты", ("Маршруты",)),
            ("События", ("События",)),
        )
        for key, aliases in pairs:
            sheet = next((sheets[a] for a in aliases if a in sheets), None)
            if not sheet:
                continue
            frame = pd.read_excel(excel, sheet_name=sheet).astype(object).where(
                lambda d: d.notna(), ""
            )
            rows = bot_module.valid_rows(
                frame.to_dict(orient="records"), require_date=(key == "События")
            )
            bot_module.TABLE_CACHE[key] = rows
        excel.close()
    except Exception as exc:  # noqa: BLE001 — прогон важнее полноты базы
        print(f"   (таблица не прочиталась: {exc})")


def _say(text: str) -> None:
    """Печатает ответ так, как его прочитает человек: без служебной разметки."""
    plain = html.unescape(re.sub(r"<[^>]+>", "", text or ""))
    prefix = "\033[38;5;154m🤖\033[0m "
    lines = plain.split("\n")
    print(prefix + ("\n" + " " * 2).join(lines))


async def run(lines: list[str]) -> int:
    from aiogram import Bot
    from aiogram.client.session.base import BaseSession
    from aiogram.methods import SendMessage, SendPhoto
    from aiogram.types import Chat, Message, Update, User

    sent: list[dict] = []

    class Capture(BaseSession):
        """Никуда не ходит в сеть: запоминает, что бот хотел отправить."""

        async def make_request(self, bot, method, timeout=None):  # type: ignore[override]
            markup = getattr(method, "reply_markup", None)
            buttons = [
                button.text
                for row in (getattr(markup, "inline_keyboard", None) or [])
                for button in row
                if getattr(button, "text", None)
            ]
            if isinstance(method, SendMessage):
                sent.append({"text": method.text or "", "buttons": buttons})
            elif isinstance(method, SendPhoto):
                sent.append({"text": f"[картинка] {method.caption or ''}".strip(), "buttons": buttons})
            returning = getattr(type(method), "__returning__", bool)
            if returning is Message:
                return Message.model_construct(
                    message_id=len(sent) + 1,
                    date=datetime.now(),
                    chat=Chat.model_construct(id=1, type="private"),
                    text=(getattr(method, "text", "") or ""),
                )
            if returning is bool:
                return True
            return None

        async def close(self) -> None:
            return None

        async def stream_content(self, *args, **kwargs):  # pragma: no cover
            return None

    bot = Bot(token=os.environ["TG_TOKEN"], session=Capture())
    import sevastopolaibot  # noqa: E402 — после подмены окружения

    _fill_cache(sevastopolaibot)

    dp = sevastopolaibot.dp
    user = User.model_construct(id=1, is_bot=False, first_name="Ты", username="you")
    chat = Chat.model_construct(id=1, type="private")
    msg_id = 0
    update_id = 0

    async def feed(text: str) -> None:
        nonlocal msg_id, update_id
        msg_id += 1
        update_id += 1

        if text.startswith("!"):
            # нажатие кнопки
            from aiogram.types import CallbackQuery

            callback = CallbackQuery.model_construct(
                id=str(update_id), from_user=user, chat_instance="local",
                data=text[1:],
                message=Message.model_construct(
                    message_id=msg_id, date=datetime.now(), chat=chat, text="",
                ).as_(bot),
            ).as_(bot)
            update = Update.model_construct(update_id=update_id, callback_query=callback)
        elif text.startswith("@"):
            from aiogram.types import Location

            try:
                lat, lon = (float(part) for part in text[1:].split(",", 1))
            except ValueError:
                print("   (нужно так: @44.6134,33.5225)")
                return
            message = Message.model_construct(
                message_id=msg_id, date=datetime.now(), chat=chat, from_user=user,
                location=Location(latitude=lat, longitude=lon),
            ).as_(bot)
            update = Update.model_construct(update_id=update_id, message=message)
        else:
            message = Message.model_construct(
                message_id=msg_id, date=datetime.now(), chat=chat,
                from_user=user, text=text,
            ).as_(bot)
            update = Update.model_construct(update_id=update_id, message=message)

        before = len(sent)
        try:
            await dp.feed_update(bot, update)
        except Exception as exc:  # noqa: BLE001 — в прогоне показываем, что упало
            print(f"\033[31mобработчик упал:\033[0m {type(exc).__name__}: {exc}")
            return
        for item in sent[before:]:
            _say(item["text"] if item["text"] else "(пустое сообщение)")
            for number, label in enumerate(item["buttons"], start=1):
                print(f"[2m     кнопка {number}:[0m {label}")
        if len(sent) == before:
            print("   (бот ничего не отправил)")

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("!"):
            shown = f"нажал кнопку [{line[1:]}]"
        elif line.startswith("@"):
            shown = f"отправил геопозицию {line[1:]}"
        else:
            shown = line
        print(f"\n\033[2mты:\033[0m {shown}")
        await feed(line)

    await bot.session.close()
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args:
        return asyncio.run(run(args))

    print("Локальный прогон бота. Пиши сообщения и команды, пустая строка или Ctrl+D — выход.")
    print("Примеры: /start · /help · /route Фиолент · !alive:panel\n")
    lines = [line for line in sys.stdin.read().splitlines()]
    return asyncio.run(run(lines))


if __name__ == "__main__":
    sys.exit(main())
