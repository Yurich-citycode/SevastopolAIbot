# Sevastopol AI Bot 🤖🏙

Телеграм-бот — гид по Севастополю: где поесть, пляжи, локации, музеи,
маршруты и события. Данные живут в Google-таблице, бот скачивает её и держит
в памяти, обновляя кэш в фоне.

Бот в Telegram: [@SevastopolAiBot](https://t.me/SevastopolAiBot)

- 📄 [AUDIT_REPORT.md](AUDIT_REPORT.md) — разбор структуры, запуск локально / Docker / Colab / VPS, перенос
- 🔐 [SECURITY.md](SECURITY.md) — где хранить токены, права 600, ротация, Vault / Doppler / Cloudflare

## Структура репозитория

| Файл | Что это |
|---|---|
| `sevastopolaibot.py` | Код бота (aiogram 3) |
| `Sevastopol AI База.xlsx` | База: Где поесть / Локации / События / Маршруты + служебные листы |
| `Sevastopol AI База.zip` | Та же база + html-экспорты листов |
| `requirements.txt` | Зависимости бота |
| `.env.example` | Шаблон настроек (скопировать в `.env`, `chmod 600`) |
| `Dockerfile`, `.dockerignore` | Запуск в контейнере |
| `SECURITY.md` | Хранение и ротация секретов |
| `AUDIT_REPORT.md` | Аудит репозитория и инструкция по переносу |
| `tests/test_carousels.py` | Тесты бота: карусели, колбэки, XP, лимиты Telegram, состояние, ENV |
| `tools/check_base.py` | Проверка базы: дубликаты, координаты, лимиты Telegram, даты |
| `tools/add_*.py`, `tools/fill_coords.py` | Скрипты пакетного наполнения базы (openpyxl) |
| `tools/rebuild_zip.py` | Пересборка `Sevastopol AI База.zip` по актуальному xlsx |
| `notebooks/SevastopolAI_bot.ipynb` | Colab-ноутбук — запуск бота одной ячейкой |
| `suggest.html` | Веб-форма «✍️ Предложить место» (GitHub Pages) |
| `.nojekyll` | Отключает Jekyll на GitHub Pages — страница отдаётся как есть |
| `worker/` | Cloudflare Worker — приём заявок с формы (инструкция внутри) |

Парсер каналов (`events/`, `notebooks/SevastopolAI_parser.ipynb`,
`tests/test_forwarder.py`) из репозитория удалён: он работал от личного
аккаунта, к боту отношения не имел и требовал собственного набора секретов.
Лист «События» теперь наполняется вручную — `tools/add_events.py` или правка
Google-таблицы. Кнопка «📰 Новости города» осталась: она ведёт на канал
`NEWS_CHANNEL_URL`.

## Быстрый старт (локально)

```bash
git clone https://github.com/Yurich-citycode/SevastopolAIbot.git
cd SevastopolAIbot

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env
chmod 600 .env                     # вписать TG_TOKEN и ADMIN_ID (ID: @userinfobot)

python sevastopolaibot.py
```

Нужны два значения: `TG_TOKEN` (@BotFather → /mybots → API Token) и `ADMIN_ID`
(твой Telegram ID — для `/admin` и пересылки заявок с формы). Остальное
работает на значениях по умолчанию. Файл `.env` не обязателен: те же
переменные можно задать окружением (Docker `-e`, systemd `EnvironmentFile`,
GitHub Secrets, Railway/Render, Vault, Doppler) — `os.getenv()` их подхватит,
а реальное окружение всегда приоритетнее `.env`.

## Запуск в Google Colab (одна ячейка)

Colab — самый быстрый способ проверить бота без сервера.
Открой `notebooks/SevastopolAI_bot.ipynb` (или скопируй ячейку ниже)
и нажми ▶️ — токен ячейка **спросит** (`getpass`, ввод не сохраняется в файле)
или возьмёт из Colab → 🔑 Secrets (`TG_TOKEN`, `ADMIN_ID`).

```python
# ═══════════ Sevastopol AI — запуск бота одной ячейкой ═══════════
ADMIN_ID = ""     # твой Telegram ID (узнать: @userinfobot) — для /admin и заявок с формы

import os, shutil, subprocess, sys

def colab_secret(name):
    try:
        from google.colab import userdata
        return str(userdata.get(name) or "").strip()
    except Exception:
        return ""

TG_TOKEN = colab_secret("TG_TOKEN")
if not TG_TOKEN:
    import getpass
    TG_TOKEN = getpass.getpass("TG_TOKEN от @BotFather: ").strip()
if not ADMIN_ID:
    ADMIN_ID = colab_secret("ADMIN_ID")

REPO = "https://github.com/Yurich-citycode/SevastopolAIbot.git"
DIR = "/content/SevastopolAIbot"


def sh(*cmd, cwd=None):
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


if os.path.isdir(DIR):
    if subprocess.run(["git", "-C", DIR, "pull", "--ff-only", "origin", "main"]).returncode:
        shutil.rmtree(DIR)
if not os.path.isdir(DIR):
    sh("git", "clone", "--depth", "1", REPO, DIR)

sh(sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt", cwd=DIR)

# настройки передаём процессу окружением — файл .env на диске не создаём
settings = dict(os.environ)
settings.update({
    "TG_TOKEN": TG_TOKEN,
    "ADMIN_ID": ADMIN_ID,
    "SPREADSHEET_ID": "1RaHoS_8Ov-kNKSZJK015ceC6H3fsWnW-D-8Yee4ckQI",
    "NEWS_CHANNEL_URL": "https://t.me/Sevastopol_AI",
    "REFRESH_SECONDS": "600",
    "STATE_FILE": "bot_state.json",
})

subprocess.run([sys.executable, "-u", "sevastopolaibot.py"], cwd=DIR, env=settings)
```

Остановка — ■ (прервать ячейку). Colab засыпает без активности, поэтому
для работы 24/7 нужен сервер (ниже).

⚠️ Никогда не вписывай токен строкой в ячейку: он уедет в git вместе с
ноутбуком. Засветился — @BotFather → /mybots → API Token → **Revoke**.

## Запуск 24/7

### Docker (рекомендуется для VPS)

```bash
docker build -t sevastopol-ai-bot .

sudo install -m 600 /dev/null /etc/sevastopol-ai-bot.env
sudo nano /etc/sevastopol-ai-bot.env    # TG_TOKEN=… ADMIN_ID=… STATE_FILE=/data/bot_state.json

docker run -d --name sevastopol-ai-bot --restart unless-stopped \
  --env-file /etc/sevastopol-ai-bot.env \
  -v sevastopol-state:/data \
  sevastopol-ai-bot

docker logs -f sevastopol-ai-bot
```

Том `sevastopol-state` сохраняет XP-паспорта и статистику между перезапусками:
без него `bot_state.json` живёт внутри контейнера и теряется при его
пересоздании. Варианты с `-e TG_TOKEN=…` и с секретами Docker — в
[SECURITY.md](SECURITY.md).

### systemd (VPS без Docker)

```bash
git clone https://github.com/Yurich-citycode/SevastopolAIbot.git /opt/sevastopol-ai-bot
cd /opt/sevastopol-ai-bot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

sudo install -m 600 /dev/null /etc/sevastopol-ai-bot.env
sudo nano /etc/sevastopol-ai-bot.env    # TG_TOKEN=… ADMIN_ID=…
```

`/etc/systemd/system/sevastopol-ai-bot.service`:

```ini
[Unit]
Description=Sevastopol AI Bot
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/sevastopol-ai-bot
EnvironmentFile=/etc/sevastopol-ai-bot.env
ExecStart=/opt/sevastopol-ai-bot/.venv/bin/python -u sevastopolaibot.py
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sevastopol-ai-bot
journalctl -u sevastopol-ai-bot -f      # логи
```

Секреты лежат в `EnvironmentFile` вне репозитория с правами 600 — в коде и в
git их нет. Ротация токена: правка файла → `systemctl restart`.

### PythonAnywhere / Railway / Render / Fly.io

Бесплатные тарифы умеют деплоить репозиторий с GitHub: укажи команду запуска
`python sevastopolaibot.py` и добавь переменные окружения `TG_TOKEN` и
`ADMIN_ID` в панели платформы.

- **Railway**: Variables → New Variable; для состояния — Volume и
  `STATE_FILE=/data/bot_state.json`.
- **Render**: Settings → Environment; диск для `STATE_FILE`.
- **Fly.io**: `fly secrets set TG_TOKEN=… ADMIN_ID=…` + `fly volumes create state`.

> Важно: бот должен запускаться как обычный процесс (`python sevastopolaibot.py`),
> а не импортом `main()` в REPL.

## Настройки (переменные окружения)

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `TG_TOKEN` | — (обязательно) | Токен бота от @BotFather. Синоним: `BOT_TOKEN` |
| `ADMIN_ID` | — (обязательно для админ-функций) | Кому доступна `/admin`, куда пересылают предложения |
| `SPREADSHEET_ID` | ID текущей базы | Google-таблица с данными |
| `NEWS_CHANNEL_URL` | `https://t.me/Sevastopol_AI` | Канал в кнопке «📰 Новости города» |
| `SUGGEST_FORM_URL` | страница `suggest.html` | Веб-форма «✍️ Предложить место» |
| `REFRESH_SECONDS` | 600 | Как часто перечитывать таблицу |
| `STATE_FILE` | `bot_state.json` | XP-паспорта, рефералы и статистика |
| `ENV_FILE` | — | Необязательно: путь к своему файлу настроек вместо `.env` |

Без `TG_TOKEN` бот печатает подсказку и выходит с кодом 2. Без `ADMIN_ID`
бот работает, но пишет в лог предупреждение: `/admin` и пересылка заявок
с формы отключены. Значения читаются один раз на старте.

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
- **Дата** события — `ДД.ММ.ГГГГ`. События в прошлом бот не показывает, поэтому
  лист «События» нужно регулярно обновлять вручную (`tools/add_events.py`).
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
python tools/rebuild_zip.py    # пересобрать «Sevastopol AI База.zip» по xlsx
```

## Проверка кода

```bash
python tests/test_carousels.py    # бот: карусели, колбэки, XP, лимиты Telegram, состояние, ENV
```

Тесты работают без сети и без Telegram: кэш заполняется из xlsx, объекты
aiogram — заглушки. Ожидаемый результат: `ИТОГ: 111 прошло, 0 упало`.

## Форма предложений и GitHub Pages

`suggest.html` публикуется на GitHub Pages (Settings → Pages → Branch: `main`,
folder `/`). Файл `.nojekyll` отключает сборку Jekyll — страница отдаётся
как есть, без риска, что Jekyll что-то пересоберёт или пропустит.

Заявка с формы уходит в Cloudflare Worker (`worker/`), а он — в личку
`ADMIN_ID` через Bot API. Токен хранится в секрете Worker'а:

```bash
cd worker
npx wrangler secret put BOT_TOKEN
npx wrangler secret put ADMIN_ID
npx wrangler deploy
```

Если адрес Worker'а ещё не прописан в `suggest.html` (`WORKER_URL`), форма
переключается в резервный режим: предлагает скопировать текст заявки и
вставить в бота — бот распознаёт префикс `✍️ ПРЕДЛОЖЕНИЕ:` и пересылает
владельцу, начисляя +5 XP.

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
- 📊 `/admin` — статистика: пользователи, паспорта, действия, свежесть кэша.

## Безопасность ⚠️

Секретов в репозитории нет: `TG_TOKEN` берётся только из окружения, `ADMIN_ID`
— тоже (значения по умолчанию в коде нет). `.env` и `bot_state.json` в
`.gitignore`, `.env` рекомендуется держать с правами 600, `bot_state.json`
бот сохраняет атомарно (`.tmp` + `os.replace`) и выставляет 600 сам.

Подробности — где хранить, как не засветить в git, как ротировать через
@BotFather `/revoke`, Docker volume для `STATE_FILE`, systemd `EnvironmentFile`,
`wrangler secret put`, Vault / Doppler / SOPS / GitHub Secrets — в
**[SECURITY.md](SECURITY.md)**.
