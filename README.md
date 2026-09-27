# Sevastopol AI Bot 🤖🏙

Это мой Telegram-бот и мой гид по Севастополю. Я собираю в нём места, где
поесть, пляжи, локации, музеи, маршруты и события. Данные я храню в
Google-таблице: бот загружает их в память и обновляет кэш в фоне.

Бот в Telegram: [@SevastopolAiBot](https://t.me/SevastopolAiBot)

- 🚀 [START_HERE.md](START_HERE.md) — мой пошаговый запуск с нуля: токен, Colab, VPS, Cloudflare Worker и чек-лист проверки
- 📦 [FILL_PACK.md](FILL_PACK.md) — готовые блоки данных для вставки в Google-таблицу по колонкам
- 🔐 [SECURITY.md](SECURITY.md) — где я храню токены, как использую права 600 и как делаю ротацию секретов

## Структура репозитория

| Файл | Что это |
|---|---|
| `sevastopolaibot.py` | Код моего бота на aiogram 3 |
| `Sevastopol AI База.xlsx` | База: Где поесть / Локации / События / Маршруты и служебные листы |
| `Sevastopol AI Архив событий.xlsx` | Прошедшие события — я храню их на память, бот их не читает |
| `requirements.txt` | Зависимости моего бота |
| `.env.example` | Шаблон настроек: я копирую его в `.env` и ставлю права `600` |
| `Dockerfile`, `.dockerignore` | Запуск моего бота в контейнере |
| `START_HERE.md` | Моя инструкция по запуску для владельца бота |
| `FILL_PACK.md` | Что и как я вставляю в Google-таблицу вручную |
| `SECURITY.md` | Как я храню и ротирую секреты |
| `tests/test_carousels.py` | Мои тесты: карусели, колбэки, XP, лимиты Telegram, состояние и ENV |
| `tools/check_base.py` | Моя проверка базы: дубликаты, координаты, лимиты Telegram и даты |
| `tools/setup_env.py` | Мастер первого запуска: создаёт `.env` и проверяет токен |
| `notebooks/SevastopolAI_bot.ipynb` | Colab-ноутбук — я запускаю бота одной ячейкой |
| `suggest.html` | Моя веб-форма «✍️ Предложить место» на GitHub Pages |
| `.nojekyll` | Отключает Jekyll на GitHub Pages, чтобы страница отдавалась как есть |
| `worker/` | Мой Cloudflare Worker, который принимает заявки с формы |

Парсер каналов (`events/`, `notebooks/SevastopolAI_parser.ipynb`,
`tests/test_forwarder.py`) я убрал из репозитория: он работал от личного
аккаунта, к этому боту отношения не имел и требовал отдельный набор секретов.
Скрипты разового наполнения базы (`tools/add_*.py`, `tools/fill_coords.py`,
`tools/rebuild_zip.py`) и `AUDIT_REPORT.md` я тоже убрал — теперь я правлю
данные прямо в Google-таблице. Лист «События» я заполняю вручную, прошедшие
события лежат в `Sevastopol AI Архив событий.xlsx`. Кнопка «📰 Новости города»
осталась: она ведёт на канал из `NEWS_CHANNEL_URL`.

## Быстрый старт (локально)

Я запускаю бота локально так:

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

Мне нужны два значения: `TG_TOKEN` от @BotFather и мой `ADMIN_ID` — Telegram ID
для `/admin` и пересылки заявок с формы. Остальные параметры работают со
значениями по умолчанию. Файл `.env` необязателен: я могу передать те же
переменные через окружение (Docker `-e`, systemd `EnvironmentFile`, GitHub
Secrets, Railway/Render, Vault или Doppler). `os.getenv()` их подхватит, а
настоящие переменные окружения имеют приоритет над `.env`.

## Запуск в Google Colab (одна ячейка)

Colab я использую, когда нужно быстро проверить бота без сервера. Я открываю
`notebooks/SevastopolAI_bot.ipynb` или копирую ячейку ниже и нажимаю ▶️. Токен
ячейка спрашивает через `getpass` — ввод не сохраняется в файле — или берёт из
Colab → 🔑 Secrets (`TG_TOKEN`, `ADMIN_ID`).

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

Чтобы остановить бота, я прерываю ячейку кнопкой ■. Colab засыпает без
активности, поэтому для работы 24/7 я использую сервер.

⚠️ Я не вписываю токен строкой в ячейку: так он может попасть в git вместе с
ноутбуком. Если токен засветился, я открываю @BotFather → /mybots → API Token
→ **Revoke** и выпускаю новый.

## Запуск 24/7

### Docker (я использую этот способ для VPS)

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

Том `sevastopol-state` сохраняет мои XP-паспорта и статистику между
перезапусками. Без него `bot_state.json` живёт внутри контейнера и теряется,
если контейнер пересоздать. Варианты с `-e TG_TOKEN=…` и секретами Docker я
описал в [SECURITY.md](SECURITY.md).

### systemd (VPS без Docker)

```bash
git clone https://github.com/Yurich-citycode/SevastopolAIbot.git /opt/sevastopol-ai-bot
cd /opt/sevastopol-ai-bot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

sudo install -m 600 /dev/null /etc/sevastopol-ai-bot.env
sudo nano /etc/sevastopol-ai-bot.env    # TG_TOKEN=… ADMIN_ID=…
```

Я создаю `/etc/systemd/system/sevastopol-ai-bot.service` с таким содержимым:

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

Я храню секреты в `EnvironmentFile` вне репозитория с правами 600. В код и в
git они не попадают. Если ротирую токен, правлю файл и выполняю
`systemctl restart sevastopol-ai-bot`.

### PythonAnywhere / Railway / Render / Fly.io

Я могу задеплоить репозиторий с GitHub на бесплатном тарифе: команда запуска —
`python sevastopolaibot.py`, а `TG_TOKEN` и `ADMIN_ID` я добавляю в панели
платформы.

- **Railway**: Variables → New Variable; для состояния я создаю Volume и ставлю `STATE_FILE=/data/bot_state.json`.
- **Render**: Settings → Environment; для `STATE_FILE` нужен диск.
- **Fly.io**: `fly secrets set TG_TOKEN=… ADMIN_ID=…` + `fly volumes create state`.

> Важно: я запускаю бота как обычный процесс (`python sevastopolaibot.py`), а
> не импортирую `main()` в REPL.

## Настройки (переменные окружения)

| Переменная | По умолчанию | Для чего я её использую |
|---|---|---|
| `TG_TOKEN` | — (обязательно) | Токен моего бота от @BotFather. Синоним: `BOT_TOKEN` |
| `ADMIN_ID` | — (обязательно для админ-функций) | Мой ID: мне доступна `/admin`, сюда приходят предложения |
| `SPREADSHEET_ID` | ID текущей базы | Google-таблица с моими данными |
| `NEWS_CHANNEL_URL` | `https://t.me/Sevastopol_AI` | Канал для кнопки «📰 Новости города» |
| `SUGGEST_FORM_URL` | страница `suggest.html` | Моя веб-форма «✍️ Предложить место» |
| `REFRESH_SECONDS` | 600 | Как часто я перечитываю таблицу |
| `STATE_FILE` | `bot_state.json` | Где я храню XP-паспорта, рефералы и статистику |
| `ENV_FILE` | — | Необязательно: путь к моему файлу настроек вместо `.env` |

Без `TG_TOKEN` бот печатает подсказку и завершается с кодом 2. Без `ADMIN_ID`
бот работает, но пишет в лог предупреждение: `/admin` и отправка заявок с формы
мне отключены. Значения читаются один раз при запуске.

## Google-таблица и база данных

Я использую локальный файл `Sevastopol AI База.xlsx` как актуальную копию для
истории и Google-таблицу из `SPREADSHEET_ID` как рабочую базу, которую читает
бот. Я правлю Google-таблицу — изменения подхватываются в течение
`REFRESH_SECONDS`, перезапуск для этого не нужен.

**Я обязательно открываю доступ к таблице «по ссылке»:** Файл → Настройки
доступа → «Все, у кого есть ссылка» → Читатель. Иначе бот получит вместо xlsx
страницу входа и напишет в логах «Google вернул не XLSX».

**Вкладки, которые я использую:**

| Вкладка | Колонки |
|---|---|
| Где поесть | Категория · Подкатегория · Название · Описание · Адрес · Район · Координаты · Ссылка на фото · Вконтакте · Telegram · Instagram · Сайт · Телефон · Время работы · Меню Справочник |
| Локации | Категория · Название · Описание · Ориентир · Координаты · Ссылка на фото |
| Маршруты | Категория · Название · Длина/Время · Сложность · Описание · Ссылка на фото · Ссылка на карту |
| События | Категория · Дата · Место · Название · Описание · Ссылка на афишу · Купить |

**Служебные вкладки** бот не читает, но я оставляю их для проекта:

| Вкладка | Зачем она мне нужна |
|---|---|
| Меню Справочник | Меню заведений: название и позиции/цены. Колонка «Меню Справочник» на листе «Где поесть» тянет их формулой `XLOOKUP` по названию |
| Лист9 | Черновик афиши со ссылками на посты-первоисточники |
| People / Analytics / Passport | Заготовки под выгрузку моей статистики и паспортов |

### Как я заполняю таблицу

- **Координаты** записываю строкой `44.616658, 33.523904` — широта и долгота через запятую.
- **Ссылка на фото** должна быть прямым адресом картинки (`.jpg`, `.png` и т. п.). Ссылка на пост Telegram (`t.me/...`) картинкой не покажется: бот отдаст карточку текстом.
- **Дату** события ставлю в формате `ДД.ММ.ГГГГ`. Прошедшие события бот не показывает, поэтому лист «События» я регулярно обновляю вручную. Готовые блоки лежат в [FILL_PACK.md](FILL_PACK.md), старые события — в `Sevastopol AI Архив событий.xlsx`.
- Строку без **Названия** бот игнорирует. Пустые строки в конце листа можно не удалять.
- Колонки бот ищет по шапке, поэтому порядок колонок я могу менять. Шапки с латинской `B` (`Bремя работы`, `Bконтакте`) он тоже понимает, но я держу русскую `В`.
- Для нового заведения с меню я добавляю строку в «Где поесть» и запись в «Меню Справочник». Название должно совпадать, тогда формула подтянет меню.

Перед публикацией я проверяю базу:

```bash
python tools/check_base.py     # дубликаты, координаты, ссылки, лимиты, даты
```

Данные я пополняю руками через Google-таблицу, бот сам подхватывает изменения.
Готовые блоки значений и пошаговая инструкция — в [FILL_PACK.md](FILL_PACK.md).
Файл `Sevastopol AI База.xlsx` в репозитории — только копия для истории: я не
импортирую его поверх Google-таблицы, потому что в колонке «Меню Справочник»
есть формулы `XLOOKUP`.

## Как я проверяю код и устраняю проблемы

```bash
python tests/test_carousels.py    # карусели, колбэки, XP, лимиты Telegram, состояние, ENV
```

Мои тесты работают без сети и Telegram: кэш заполняется из xlsx, объекты
aiogram заменяются заглушками. Я проверяю качество, а не фиксированное число
строк в базе: в каждой категории должны быть данные, карточки должны
собираться, а лимиты Telegram не должны превышаться. Нормальный результат — ни
одного `❌` и строка `ИТОГ: N прошло, 0 упало`.

Если бот не стартует, я сначала проверяю следующее:

- нет `TG_TOKEN` — бот подскажет причину и завершится с кодом 2;
- нет `ADMIN_ID` — основные функции работают, но `/admin` и заявки мне недоступны;
- таблица не загружается — проверяю `SPREADSHEET_ID` и доступ «Все, у кого есть ссылка»;
- данные не обновились — проверяю `REFRESH_SECONDS` и смотрю, что правлю именно рабочую Google-таблицу;
- после изменения настроек — перезапускаю процесс и смотрю логи (`docker logs -f ...` или `journalctl -u sevastopol-ai-bot -f`).

## Форма предложений и Cloudflare Worker

Я публикую `suggest.html` на GitHub Pages: Settings → Pages → Branch: `main`,
folder `/`. Файл `.nojekyll` отключает сборку Jekyll, поэтому страница
отдаётся как есть.

Заявка из формы уходит в мой Cloudflare Worker (`worker/`), а Worker отправляет
её мне в личку через Telegram Bot API на `ADMIN_ID`. Секреты я храню в Worker,
а не в коде:

```bash
cd worker
npx wrangler secret put BOT_TOKEN
npx wrangler secret put ADMIN_ID
npx wrangler deploy
```

Адрес Worker я указываю в `suggest.html` в переменной `WORKER_URL`:

```js
var WORKER_URL = "https://sevastopol-suggest.your-name.workers.dev";
```

Если там стоит заглушка `__WORKER_URL__` или Worker временно недоступен, форма
переходит в резервный режим: предлагает скопировать текст и вставить его в
бота. Я получаю такую заявку в личке, а пользователю начисляется +5 XP.
Подробная инструкция по Cloudflare — в [worker/README.md](worker/README.md).

## Что умеет мой бот

- 🍽 Еда: категории и фильтры — рядом со мной, район, список и подкатегория; карусели с фото и шеринг.
- 📍 Локации и 🗺 маршруты: карусели и «🍔 Съестное рядом» с возвратом на ту же карточку.
- 🎲 «Случайное место / локация / маршрут» — кнопка в каждой карусели.
- 📅 События: ближайшие события одним сообщением и кнопки на билеты.
- 📰 «Новости города» — ссылка на канал [t.me/Sevastopol_AI](https://t.me/Sevastopol_AI), без рассылок по личкам.
- ✍️ «Предложить место» — моя веб-форма; заявки приходят мне через Worker.
- 🛂 City Passport: XP за первый запуск, активность не чаще раза в день на действие и рефералов; уровни и ранги.
- 📊 `/admin` — моя статистика: пользователи, паспорта, действия и свежесть кэша.

## Безопасность ⚠️

Секретов в репозитории нет. `TG_TOKEN` и `ADMIN_ID` я передаю только через
окружение; значений по умолчанию в коде нет. `.env` и `bot_state.json` уже в
`.gitignore`. Я держу `.env` с правами 600, а `bot_state.json` бот сохраняет
атомарно (`.tmp` + `os.replace`) и сам выставляет ему права 600.

Подробнее я описал хранение секретов, защиту от случайной публикации в git,
ротацию через @BotFather `/revoke`, Docker volume для `STATE_FILE`, systemd
`EnvironmentFile`, `wrangler secret put`, Vault / Doppler / SOPS / GitHub
Secrets в **[SECURITY.md](SECURITY.md)**.
