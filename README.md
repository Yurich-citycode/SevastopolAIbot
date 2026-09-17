# Sevastopol AI Bot 🤖🏙

Телеграм-бот — гид по Севастополю: где поесть, пляжи, локации, музеи,
маршруты и события. Данные живут в Google-таблице, бот скачивает её и держит
в памяти, обновляя кэш в фоне.

Бот в Telegram: [@SevastopolAiBot](https://t.me/SevastopolAiBot)

## Структура репозитория

| Файл | Что это |
|---|---|
| `sevastopolaibot.py` | Код бота (aiogram 3) |
| `Sevastopol AI База.xlsx` | База: Где поесть / Локации / События / Маршруты + служебные листы |
| `Sevastopol AI База.zip` | Та же база + html-экспорты листов |
| `requirements.txt` | Зависимости бота |
| `.env.example` | Шаблон настроек (скопировать в `.env`) |
| `Dockerfile` | Запуск в контейнере |
| `tests/` | `test_carousels.py` (бот) и `test_forwarder.py` (парсер каналов) |
| `tools/check_base.py` | Проверка базы: дубликаты, координаты, лимиты Telegram, даты |
| `tools/add_*.py`, `tools/fill_coords.py` | Скрипты пакетного наполнения базы (openpyxl) |
| `tools/rebuild_zip.py` | Пересборка `Sevastopol AI База.zip` по актуальному xlsx |
| `notebooks/` | Готовые Colab-ноутбуки — бот и парсер, каждый в **одной ячейке** |
| `suggest.html` | Веб-форма «✍️ Предложить место» (GitHub Pages) |
| `worker/` | Cloudflare Worker — приём заявок с формы (инструкция внутри) |
| `events/` | Парсер каналов на личном аккаунте (Telethon) — отдельный сервис |

## Быстрый старт (локально)

```bash
git clone https://github.com/Yurich-citycode/SevastopolAIbot.git
cd SevastopolAIbot

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env
#   впиши в .env свой TG_TOKEN от @BotFather

python sevastopolaibot.py
```

## Запуск в Google Colab (одна ячейка)

Colab — самый быстрый способ проверить бота без сервера.
Открой `notebooks/SevastopolAI_bot.ipynb` (или скопируй ячейку ниже),
впиши токен и нажми ▶️.

```python
# ═══════════ Sevastopol AI — запуск бота одной ячейкой ═══════════
TG_TOKEN = "ВСТАВЬ_ТОКЕН_ОТ_BOTFATHER"      # ← сюда токен, остальное ячейка сделает сама

import os, pathlib, shutil, subprocess, sys

REPO = "https://github.com/Yurich-citycode/SevastopolAIbot.git"
DIR = "/content/SevastopolAIbot"


def sh(*cmd, cwd=None):
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


# 1) свежий код
if os.path.isdir(DIR):
    if subprocess.run(["git", "-C", DIR, "pull", "--ff-only", "origin", "main"]).returncode:
        shutil.rmtree(DIR)                      # локальные правки мешают — клонируем заново
if not os.path.isdir(DIR):
    sh("git", "clone", "--depth", "1", REPO, DIR)

# 2) зависимости
sh(sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt", cwd=DIR)

# 3) настройки (файл .env в git не попадает)
env = pathlib.Path(DIR) / ".env"
env.write_text("\n".join([
    f"TG_TOKEN={TG_TOKEN}",
    "SPREADSHEET_ID=1RaHoS_8Ov-kNKSZJK015ceC6H3fsWnW-D-8Yee4ckQI",
    "ADMIN_ID=6106999216",
    "NEWS_CHANNEL_URL=https://t.me/Sevastopol_AI",
    "REFRESH_SECONDS=600",
    "STATE_FILE=bot_state.json",
]) + "\n", encoding="utf-8")
env.chmod(0o600)

# 4) запуск — процесс живёт, пока не нажмёшь ■
subprocess.run([sys.executable, "-u", "sevastopolaibot.py"], cwd=DIR)
```

Остановка — ■ (прервать ячейку). Colab засыпает без активности, поэтому
для работы 24/7 нужен сервер (ниже).

⚠️ Токен в ячейке виден всем, у кого есть доступ к ноутбуку. Не публикуй
ноутбук с вписанным токеном; засветился — перевыпусти у @BotFather.

## Запуск 24/7

### Docker (рекомендуется для VPS)

```bash
docker build -t sevastopol-ai-bot .
docker run -d --name sevastopol-ai-bot --restart unless-stopped \
  -e TG_TOKEN=123456789:AAABBBCCC \
  -e ADMIN_ID=6106999216 \
  -e STATE_FILE=/data/bot_state.json \
  -v sevastopol-state:/data \
  sevastopol-ai-bot
```

Том `sevastopol-state` сохраняет XP-паспорта и статистику между перезапусками:
без него `bot_state.json` живёт внутри контейнера и теряется при его пересоздании.

### systemd (VPS без Docker)

```bash
git clone https://github.com/Yurich-citycode/SevastopolAIbot.git /opt/sevastopol-ai-bot
cd /opt/sevastopol-ai-bot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
printf 'TG_TOKEN=123456789:AAABBBCCC\n' > .env && chmod 600 .env
```

`/etc/systemd/system/sevastopol-ai-bot.service`:

```ini
[Unit]
Description=Sevastopol AI Bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/sevastopol-ai-bot
ExecStart=/opt/sevastopol-ai-bot/.venv/bin/python -u sevastopolaibot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now sevastopol-ai-bot
journalctl -u sevastopol-ai-bot -f      # логи
```

### PythonAnywhere / Railway / Render / Fly.io

Бесплатные тарифы умеют деплоить репозиторий с GitHub: укажи команду запуска
`python sevastopolaibot.py` и добавь переменную окружения `TG_TOKEN` — всё.

> Важно: бот должен запускаться как обычный процесс (`python sevastopolaibot.py`),
> а не импортом `main()` в REPL.

## Настройки (переменные окружения)

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `TG_TOKEN` | — (обязательно) | Токен бота от @BotFather |
| `SPREADSHEET_ID` | ID текущей базы | Google-таблица с данными |
| `ADMIN_ID` | 6106999216 | Кому доступна `/admin`, куда пересылают предложения |
| `NEWS_CHANNEL_URL` | `https://t.me/Sevastopol_AI` | Канал в кнопке «📰 Новости города» |
| `SUGGEST_FORM_URL` | страница `suggest.html` | Веб-форма «✍️ Предложить место» |
| `REFRESH_SECONDS` | 600 | Как часто перечитывать таблицу |
| `STATE_FILE` | `bot_state.json` | XP-паспорта, рефералы и статистика |

## База данных

Таблица: `Sevastopol AI База.xlsx` (в репозитории) ↔ Google-таблица
`SPREADSHEET_ID` (её читает бот). Правь Google-таблицу — изменения подхватятся
в течение `REFRESH_SECONDS` без перезапуска бота.

**Доступ к таблице обязателен «по ссылке»:** Файл → Настройки доступа →
«Все, у кого есть ссылка» → Читатель. Иначе бот получит вместо xlsx страницу
входа и напишет в логах «Google вернул не XLSX».

**Вкладки, которые читает бот:**

| Вкладка | Колонки |
|---|---|
| Где поесть | Категория · Подкатегория · Название · Описание · Адрес · Район · Координаты · Ссылка на фото · Вконтакте · Telegram · Instagram · Сайт · Телефон · Время работы · Меню Справочник |
| Локации | Категория · Название · Описание · Ориентир · Координаты · Ссылка на фото |
| Маршруты | Категория · Название · Длина/Время · Сложность · Описание · Ссылка на фото · Ссылка на карту |
| События | Категория · Дата · Место · Название · Описание · Ссылка на афишу · Купить |

**Служебные вкладки** (бот их не читает, но они нужны проекту):

| Вкладка | Зачем |
|---|---|
| Меню Справочник | Меню заведений: название + позиции/цены. Колонка «Меню Справочник» на листе «Где поесть» тянет их формулой `XLOOKUP` по названию |
| Лист9 | Черновик афиши (ссылки на посты-первоисточники) |
| People / Analytics / Passport | Заготовки под выгрузку статистики и паспортов |

Правила заполнения:

- **Координаты** — строкой `44.616658, 33.523904` (широта, долгота через запятую).
- **Ссылка на фото** — прямой адрес картинки (`.jpg/.png/...`). Ссылка на пост
  Telegram (`t.me/...`) картинкой не покажется: бот отдаст карточку текстом.
- **Дата** события — `ДД.ММ.ГГГГ`. События в прошлом бот не показывает.
- Строка без **Названия** ботом игнорируется — пустые строки в конце листа
  можно не удалять, на работу они не влияют.
- Колонки бот ищет по шапке, поэтому порядок колонок можно менять; шапки
  «Bремя работы» / «Bконтакте» с латинской `B` тоже читаются.
- Новое заведение с меню: строка в «Где поесть» + запись в «Меню Справочник»
  (название должно совпадать) — формула подтянет меню сама.

Проверка базы перед публикацией:

```bash
python tools/check_base.py     # дубликаты, координаты, ссылки, лимиты, даты
```

Наполнение пачками — скрипты `tools/add_*.py` (пишут прямо в xlsx):

```bash
python tools/add_cafe.py       # пример: дописывает кафе в конец листа
```

## Проверка кода

```bash
python tests/test_carousels.py    # бот: карусели, колбэки, XP, лимиты Telegram, состояние
python tests/test_forwarder.py    # парсер: ссылки, альбомы, стейт, копирование постов
```

Тесты работают без сети и без Telegram: кэш заполняется из xlsx, объекты
aiogram/Telethon — заглушки.

## Что умеет бот

- 🍽 Еда: категории, фильтры (рядом со мной / район / список / подкатегория),
  карусели с фото, шеринг.
- 📍 Локации и 🗺 маршруты: карусели, «🍔 Съестное рядом» (возврат — на ту же
  карточку, откуда ушли).
- 🎲 «Случайное место / локация / маршрут» — кнопка в каждой карусели.
- 📅 События: все ближайшие — одним сообщением, кнопки на билеты.
- 📰 «Новости города» — ссылка на канал [t.me/Sevastopol_AI](https://t.me/Sevastopol_AI).
  Рассылок по личкам нет.
- ✍️ «Предложить место» — веб-форма, заявка уходит владельцу (`ADMIN_ID`).
- 🛂 City Passport: XP за первый запуск, за активность (не чаще раза в день
  на действие) и за рефералов; уровни и ранги.

## Безопасность ⚠️

Токен не хранится в коде — только в `.env` (в git не попадает) или в переменной
окружения. Засветился в git-истории — перевыпусти: @BotFather → /mybots →
API Token → Revoke.

Строка сессии парсера (`TELETHON_SESSION`) — это полный доступ к личному
аккаунту: держи её в `events/.env` и никому не показывай.
