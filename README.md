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
| `suggest.html` | Веб-форма «✍️ Предложить место» (GitHub Pages), заявки уходят через Worker |
| `worker/` | Cloudflare Worker — принимает форму и шлёт заявку владельцу в личку (инструкция внутри) |
| `events/` | Парсер каналов на личном аккаунте (Telethon) — отдельный сервис (инструкция внутри) |
| `tests/` | Тесты: `test_carousels.py` (бот, 75 проверок) и `test_forwarder.py` (парсер каналов) |

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
| `ADMIN_ID` | 6106999216 | Кому доступна `/admin`, куда пересылают «предложенные места» |
| `NEWS_CHANNEL_URL` | `https://t.me/Sevastopol_AI` | Канал с новостями (кнопка «📰 Новости города») |
| `REFRESH_SECONDS` | 600 | Как часто перечитывать таблицу |
| `STATE_FILE` | `bot_state.json` | Файл с XP-паспортами и статистикой |

## Что умеет бот

- 🍽 Еда: категории, фильтры (рядом со мной / район / список / подкатегория),
  карусели с фото, шеринг.
- 📍 Локации и 🗺 маршруты: карусели, «🍔 Съестное рядом» (возврат — на ту же
  карточку, откуда ушли).
- 🎲 «Случайное место / локация / маршрут» — кнопка в каждой карусели.
- 📅 События: все ближайшие события — **одним сообщением**, кнопки на билеты.
- 📰 «Новости города» — ссылка на канал [t.me/Sevastopol_AI](https://t.me/Sevastopol_AI)
  (`NEWS_CHANNEL_URL`). Рассылок по личкам нет — новости живут в канале.
- ✍️ «Предложить место» — пользователь описывает место (текст/фото/гео),
  бот пересылает это **только владельцу** (`ADMIN_ID`).
- 🛂 City Passport: XP за первый запуск, за активность (не чаще 1 раза в день
  на действие), за рефералов; уровни и ранги.

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
