# Sevastopol AI Bot 🤖🏙

Телеграм-бот — гид по Севастополю: где поесть, пляжи, локации, музеи,
маршруты и события. Данные хранятся в Google-таблице (`Sevastopol AI База.xlsx`
→ Google Sheets), бот скачивает её и держит в памяти, обновляя кэш в фоне.

Бот в Telegram: [@SevastopolAiBot](https://t.me/SevastopolAiBot)

## Структура репозитория

| Файл | Что это |
|---|---|
| `sevastopolaibot.py` | Код бота (aiogram 3) |
| `Sevastopol AI База.xlsx` | База: Где поесть / Локации / События / Маршруты / Меню Справочник |
| `Sevastopol AI База.zip` | Та же база + html-экспорты листов |
| `requirements.txt` | Зависимости |
| `.env.example` | Шаблон настроек (скопировать в `.env`) |
| `Dockerfile` | Запуск в контейнере |
| `tools/` | Скрипты пакетного добавления строк в базу (openpyxl) |

## Быстрый старт (локально)

```bash
# 1. Клонируй
git clone https://github.com/Yurich-citycode/SevastopolAIbot.git
cd SevastopolAIbot

# 2. Виртуальное окружение + зависимости
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Настройки
cp .env.example .env               # Windows: copy .env.example .env
#   открой .env и впиши TG_TOKEN от @BotFather

# 4. Запуск
python sevastopolaibot.py
```

## Запуск из Google Colab

Токен не хранится в коде — задай его переменной окружения до запуска бота:

```python
import os
os.environ["TG_TOKEN"] = "123456789:AAABBBCCC"   # токен от @BotFather

# Скачиваем и запускаем свежую версию из GitHub
!git clone https://github.com/Yurich-citycode/SevastopolAIbot.git
%cd SevastopolAIbot
!pip install -q -r requirements.txt

from sevastopolaibot import main
import asyncio
await main()          # в ячейке кода (не в Colab-форме!) выполняется нормально
```

> В Colab «форма» (Form) исполняет ячейки как приложение, а не как блокнот —
> тогда `await main()` не работает. Вставь код в обычную кодовую ячейку
> (правый клик → «Remove form») или используй такой вызов:
> ```python
> import asyncio, nest_asyncio
> nest_asyncio.apply()
> asyncio.run(main())
> ```

## Запуск 24/7 (бесплатно)

Colab выключается через пару часов бездействия. Чтобы бот работал постоянно:

1. **PythonAnywhere (самый простой бесплатный способ)**
   - https://www.pythonanywhere.com → Bash console:
     ```bash
     git clone https://github.com/Yurich-citycode/SevastopolAIbot.git
     cd SevastopolAIbot
     python3 -m venv .venv && source .venv/bin/activate
     pip install -r requirements.txt
     nano .env          # вставь TG_TOKEN=...
     ```
   - Вкладка **Files** → открой `sevastopolaibot.py`, замени последнюю строку
     `asyncio.run(main())` на `await main()` и сохрани (сделай это вручную).
   - Запуск:
     ```bash
     cd ~/SevastopolAIbot && source .venv/bin/activate && python sevastopolaibot.py
     ```
   - Чтобы работал всегда: вкладка **Schedule** → «Add a new scheduled task» →
     любой интервал (например, daily) → в команду впиши запуск выше. PythonAnywhere
     перезапустит бота, если он упал.

2. **Railway / Render / Fly.io** — бесплатные тарифы умеют деплоить репозиторий
   с GitHub напрямую. Добавь переменную окружения `TG_TOKEN` — и всё.

3. **Docker**:
   ```bash
   docker build -t sevastopol-ai-bot .
   docker run -d --restart unless-stopped -e TG_TOKEN=123456789:AAABBBCCC sevastopol-ai-bot
   ```

## Настройки (переменные окружения)

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `TG_TOKEN` | — (обязательно) | Токен бота от @BotFather |
| `SPREADSHEET_ID` | ID текущей базы | Google-таблица с данными |
| `ADMIN_ID` | 6106999216 | Кому доступна `/admin` |
| `REFRESH_SECONDS` | 600 | Как часто перечитывать таблицу |
| `STATE_FILE` | `bot_state.json` | Файл с XP-паспортами и статистикой |

## Обновление базы данных

1. Правь Google-таблицу (или `Sevastopol AI База.xlsx` и загрузи его обратно
   в Google Sheets) — бот сам подхватит изменения в течение `REFRESH_SECONDS`.
2. Или обнови локальный xlsx скриптами из `tools/` и запуши в репозиторий.

## Безопасность ⚠️

Токен бота не хранится в коде — только в `.env` (не попадает в git) или в
переменной окружения. Если токен когда-либо засветился в git-истории —
перевыпусти его: @BotFather → /mybots → API Token → Revoke.

---

База наполняется вручную и скриптами: кофейни, рестораны, кафе, пекарни,
бары, доставки, пляжи, музеи, маршруты. Новые строки добавляются в конец
соответствующего листа в том же формате, что и существующие.
