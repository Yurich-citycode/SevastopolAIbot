# AUDIT REPORT — SevastopolAIbot

Дата аудита: **2026-09-25** · ветка: `arena/01a0d7ab-sevastopolaibot` (от `main`, коммит `12eb550`)
Результат: парсер удалён, бот почищен и переведён на `python-dotenv`, секреты — только из окружения,
тесты **111/111 зелёные** (было 98), добавлены `SECURITY.md`, `.nojekyll`, этот отчёт.

---

## 1. Итог в одну строку

| Было | Стало |
|---|---|
| 32 файла в git, 1 ветка, бот + парсер + 2 набора тестов | 30 файлов, 1 ветка, только бот и его инфраструктура |
| Токен вписан строкой в Colab-ноутбуке (в git-истории) | Токен нигде не хранится: `getpass` / Colab Secrets / ENV |
| `ADMIN_ID` зашит дефолтом в боте и в Worker'е | `ADMIN_ID` только из ENV (`os.getenv`), дефолта нет |
| Свой `_load_env()` на 15 строк | `python-dotenv` (`load_dotenv`), + поддержка `ENV_FILE` |
| `requirements.txt`: 4 пакета | 5 пакетов (+`python-dotenv`), лишних нет |
| `tests/test_carousels.py`: 98 проверок | 111 проверок (+блок «Конфигурация из ENV») |
| `tools/rebuild_zip.py` падал и дублировал xlsx | работает без git-истории, без дублей |
| `sevastopolaibot.py`: 1481 строка, 22 комментария, 50 строк поясняющих docstring | 1566 строк (PEP 8: 2 пустые между функциями), 0 поясняющих комментариев, 67,9 КБ вместо 69,8 КБ |

Функционал и поведение бота сохранены 1:1 — см. раздел 7.

---

## 2. Ветки

```bash
git ls-remote --heads origin
# 12eb550…  refs/heads/main
```

В удалённом репозитории **одна ветка — `main`**. Мёртвых, заброшенных и
дублирующих веток нет, удалять нечего. Локальная `main` = `origin/main`.
Работа велась в `arena/01a0d7ab-sevastopolaibot` → PR в `main`.

История — один коммит `12eb550 Add files via upload` (репозиторий был
перезалит целиком). Следствие: `tools/rebuild_zip.py` ссылался на коммит
`4440faa`, которого в истории больше нет → инструмент был нерабочим (исправлено).

---

## 3. Структура репозитория (что где и зачем)

```
SevastopolAIbot/
├── sevastopolaibot.py          бот целиком: кэш Google Sheets, карусели, XP, рефералы, /admin
├── requirements.txt            aiogram, pandas, openpyxl, requests, python-dotenv
├── .env.example                шаблон 7 переменных (секретов нет)
├── Dockerfile, .dockerignore   образ python:3.12-slim, секреты не копируются
├── .gitignore                  .env, .env.*, bot_state.json, *.json.tmp, venv, кэши
├── .nojekyll                   GitHub Pages без сборки Jekyll (suggest.html отдаётся как есть)
├── README.md                   быстрый старт, 24/7, база, настройки, безопасность
├── SECURITY.md                 хранение/ротация секретов, 600, Docker, systemd, Vault, wrangler
├── AUDIT_REPORT.md             этот файл
├── suggest.html                веб-форма «✍️ Предложить место» (GitHub Pages)
├── worker/
│   ├── index.js                Cloudflare Worker: приём заявки → sendMessage владельцу
│   ├── wrangler.toml           имя / main / compatibility_date; секреты — только через CLI/Dashboard
│   └── README.md               деплой за 10 минут через браузер + через wrangler
├── notebooks/
│   └── SevastopolAI_bot.ipynb  запуск бота в Colab одной ячейкой (токен через getpass/Secrets)
├── tests/
│   └── test_carousels.py       111 проверок: карусели, колбэки, XP, лимиты, состояние, ENV
├── tools/
│   ├── check_base.py           аудит xlsx: дубликаты, координаты, URL, даты, лимиты Telegram
│   ├── add_places.py, add_places_rest.py, add_cafe.py, add_conf.py,
│   │   add_beaches.py, add_attractions.py, add_batch3.py, add_batch4.py,
│   │   add_events.py           пакетное наполнение листов (openpyxl)
│   ├── fill_coords.py          дозаполнение координат
│   └── rebuild_zip.py          пересборка «Sevastopol AI База.zip» по актуальному xlsx
├── Sevastopol AI База.xlsx     75 КБ — локальная копия базы (бот читает Google-таблицу)
├── Sevastopol AI База.zip      612 КБ — xlsx + html-экспорты листов + sheet.css
├── ai-screen.jpg, sevastopol-ai.jpg   картинки для оформления (README/Pages)
```

Удалено (парсер, по заданию):

| Удалено | Было |
|---|---|
| `events/forwarder.py` | 691 строка, Telethon-клиент личного аккаунта |
| `events/README.md` | 225 строк инструкции по API_ID/API_HASH/сессии |
| `events/sources.json` | список каналов + target |
| `notebooks/SevastopolAI_parser.ipynb` | Colab-ячейка парсера |
| `tests/test_forwarder.py` | 340 строк тестов парсера |
| упоминания `TELETHON_API_ID`, `TELETHON_API_HASH`, `TELETHON_SESSION`, `FORWARDER_TARGET` | из `.env.example`, `README.md`, `.gitignore`, `.dockerignore` |

`events/.env` и `events/forwarder_state.json` в git не было никогда (они и до
этого лежали в `.gitignore`) — удалять из репозитория было нечего. Локально,
если папка `events/` осталась от прошлых запусков, снеси её сам:
`rm -rf events/` — там могла лежать строка сессии личного аккаунта.

Проверка, что следов парсера не осталось:

```bash
grep -rn "TELETHON\|FORWARDER\|telethon\|forwarder\|events/" . \
  --exclude-dir=.git --exclude-dir=.venv --exclude=AUDIT_REPORT.md
# пусто (кроме assert'а в tests и строки «что удалено» в README)
```

---

## 4. Найденные проблемы и что сделано

### 4.1 🔴 Критично: живой токен бота в git

В `notebooks/SevastopolAI_bot.ipynb` (коммит `12eb550`) токен бота был
вписан строкой в первую переменную ячейки — с пометкой «ВРЕМЕННО: токен вшит
для теста в Colab и будет перевыпущен после него». Ноутбук публичный, значит
токен считался опубликованным.

**Что сделано:** ячейка переписана — токена в файле больше нет, он берётся из
Colab Secrets (`userdata.get("TG_TOKEN")`) или спрашивается через
`getpass.getpass()` (ввод не сохраняется в notebook). Настройки передаются
процессу через `env=`, файл `.env` в Colab не создаётся.

**Что нужно сделать тебе (вручную, я не могу):** @BotFather → `/mybots` →
`@SevastopolAiBot` → **API Token → Revoke**, затем обновить токен там, где бот
запущен, и в секрете Worker'а (`npx wrangler secret put BOT_TOKEN`).
Удаление файла из рабочей копии историю не чистит — инструкция по
`git filter-repo` в `SECURITY.md` → раздел 3.

### 4.2 🔴 `ADMIN_ID` был зашит в коде

- `sevastopolaibot.py`: `int(os.getenv("ADMIN_ID", "6106999216"))` — личный ID
  как значение по умолчанию.
- `worker/index.js`: `const OWNER_CHAT_ID = "6106999216";`.
- `.env.example`, `README.md`, ноутбук: тот же ID строкой.

**Стало:** `ADMIN_ID = env_int("ADMIN_ID")` — дефолта нет. Если переменная не
задана, бот стартует и работает, но пишет в лог
`ADMIN_ID не задан: /admin и пересылка предложений с формы отключены`;
`/admin` молча игнорируется (`is_admin()`), заявки с формы не пересылаются
(в логе — предупреждение). Worker без `ADMIN_ID` отвечает
`server_not_configured` (500). Значение переехало в ENV/секреты, из шаблонов
и документации убрано.

### 4.3 🟠 Кастомный `_load_env` → `python-dotenv`

Свой парсер `.env` не понимал `export KEY=`, многострочные значения, экранирование
и комментарии после значения. Заменён на `load_dotenv()` (добавлен в
`requirements.txt`). Поведение совместимо: реальное окружение приоритетнее файла
(`override=False` — как было с `os.environ.setdefault`).

Добавлено:

- поиск `.env` рядом со скриптом **и** в текущей директории (запуск из любой
  точки: `python /opt/bot/sevastopolaibot.py`);
- переменная `ENV_FILE` — свой путь к настройкам (Docker Secrets, SOPS, tmpfs);
- `BOT_TOKEN` как синоним `TG_TOKEN` (приоритет у `TG_TOKEN`) — удобнее при
  переносе на платформы, где переменная называется `BOT_TOKEN`;
- `env_str()` / `env_int()`: пустое значение → дефолт, мусор в числе →
  предупреждение в лог и дефолт (раньше `int("abc")` ронял бота на старте).

### 4.4 🟠 Права на файлы с данными

- `.env`: при старте `warn_insecure_files()` проверяет права `.env` (рядом со
  скриптом и в CWD), файла из `ENV_FILE` и `bot_state.json`, и логирует
  предупреждение, если файл читается не только владельцем
  (`/tmp/smoke.env: права 644 — рекомендую chmod 600`).
- `bot_state.json`: атомарная запись **уже была** (`.tmp` + `os.replace`) —
  проверена тестами и оставлена без изменений; добавлен `os.chmod(..., 0o600)`
  после записи (там содержатся ID пользователей, XP и аналитика).

### 4.5 🟡 Мёртвый и неоптимальный код в боте

| Что | Было | Стало |
|---|---|---|
| `cleaned = {n: n for n in sheet_names}` | словарь-пустышка, имя в имя | `sheets = {strip: original}` — реально сопоставляет «Где поесть» с фактическим названием вкладки |
| `pd.ExcelFile(...)` | не закрывался → `ResourceWarning`, утечка fd при каждом refresh | `try/finally: excel_file.close()` |
| `save_state()` | `del ANALYTICS_ROWS[:-2000]`, затем ещё и срез `[-2000:]` | одна обрезка, в payload идёт готовый список |
| `parse_event_date()` | `for width, fmt in ((10, …), (10, …))` — `width` всегда 10 | `for fmt in (…)` + `s[:10]` |
| `get_rank` / `get_progress_bar` / `xp_to_next` | пороги 100/300/800/2000/4000/7000 продублированы трижды | константы `XP_LEVELS`, `XP_RANKS` — одно место правки |
| `invite_friend()` | «+25 XP» и «7 дней — ещё +40 XP» строками | `REFERRAL_XP` / `REFERRAL_BONUS_DAYS` / `REFERRAL_BONUS_XP` (текст идентичен) |
| `yandex_maps_url()` | промежуточная переменная + комментарий | одно выражение |
| `tools/add_places.py` | `import sys` не использовался | убран (pyflakes чист) |
| комментарии | 22 строки `#`-пояснений + 3 внутристрочных + 50 строк поясняющих docstring | 0 пояснений; остались только 14 разделителей секций (`# ── карусели ──`) и docstring модуля |

`callback_handler` отвечает на каждый колбэк дважды (внутри веток меню и в
`finally`) — **оставлено намеренно**: это гарантия, что «часики» у пользователя
гаснут даже в ветках, которые ничего не отвечают. Лишний API-вызов дёшев,
ошибка на повторный `answerCallbackQuery` подавляется.

### 4.6 🟡 `tools/rebuild_zip.py` был сломан

1. `git show 4440faa:"Sevastopol AI База.zip"` — коммита нет в истории
   (репозиторий перезалит) → `CalledProcessError` и падение.
2. Даже с рабочей основой: xlsx копировался из архива-основы **и** дописывался
   снова → `UserWarning: Duplicate name` и два одинаковых файла в архиве.

**Стало:** `read_base_archive()` — сначала пытается взять архив из git, при
неудаче берёт текущий zip в рабочей копии (с внятным сообщением), а если нет
ни того ни другого — выходит с понятной ошибкой. При копировании запись с
именем xlsx пропускается. Проверено: 11 файлов, дублей 0, md5 xlsx внутри
архива совпадает с исходным.

### 4.7 🟡 Данные: лист «События» устарел

`python tools/check_base.py` → **0 ошибок, 20 предупреждений**: 13 из 20
событий уже в прошлом (17.09–24.09.2026), предстоящих — 7. Плюс 837 пустых
строк в «Где поесть» (бот их игнорирует — это не ошибка).

Раньше афишу планировалось тянуть парсером. Парсер удалён → события нужно
вносить вручную: `tools/add_events.py` (пишет в xlsx) или прямо в
Google-таблицу. Когда предстоящих событий не останется, бот честно покажет
«На ближайшие дни событий не найдено. Самое время устроить чилл! 🌅» —
кнопка не сломается. Источник городских новостей в боте остался: кнопка
«📰 Новости города» → `NEWS_CHANNEL_URL`.

### 4.8 🟢 GitHub Pages

Pages включён (`build_type: legacy`, ветка `main`, корень) — это сборка
Jekyll. Добавлен пустой `.nojekyll`: Jekyll отключается, `suggest.html` и
картинки отдаются как есть, сборка быстрее, нет риска, что файлы с `_`
в начале имени потеряются. На работу формы не влияет.

### 4.9 🟢 `.gitignore` / `.dockerignore`

Убраны строки `events/.env`, `events/forwarder_state.json`. Добавлены
`.env.*` (с исключением `!.env.example` — шаблон должен коммититься),
`*.json.tmp` (след атомарной записи состояния), `.pytest_cache/`.
В `.dockerignore` — то же, плюс уже игнорировались `notebooks/`, `tests/`, `.git`.

---

## 5. Что нужно для запуска

### 5.1 Локально (5 минут)

```bash
git clone https://github.com/Yurich-citycode/SevastopolAIbot.git && cd SevastopolAIbot
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env && chmod 600 .env                  # вписать TG_TOKEN и ADMIN_ID
python sevastopolaibot.py
```

Требуется: Python 3.10+ (в образе 3.12; код использует `dict | None`),
доступ к `api.telegram.org` и `docs.google.com`.
Обязательные переменные: `TG_TOKEN`. Для `/admin` и заявок с формы — `ADMIN_ID`.
Остальное работает на дефолтах. Признак успеха в логах: `✅ Кэш обновлён`,
`🚀 Бот запущен`.

Без токена бот печатает подсказку и выходит с кодом 2. С отозванным токеном —
плашка `❌ БОТ НЕ ЗАПУСТИЛСЯ` и код 1 (не висит молча).

### 5.2 Docker

```bash
docker build -t sevastopol-ai-bot .
sudo install -m 600 /dev/null /etc/sevastopol-ai-bot.env
sudo nano /etc/sevastopol-ai-bot.env     # TG_TOKEN=… ADMIN_ID=… STATE_FILE=/data/bot_state.json
docker run -d --name sevastopol-ai-bot --restart unless-stopped \
  --env-file /etc/sevastopol-ai-bot.env -v sevastopol-state:/data sevastopol-ai-bot
docker logs -f sevastopol-ai-bot
```

Volume обязателен для сохранения `bot_state.json` между пересозданиями
контейнера. В образ `.env`, `bot_state.json`, `notebooks/`, `tests/`, `.git`
не попадают (`.dockerignore`).

### 5.3 Google Colab

`notebooks/SevastopolAI_bot.ipynb` → ▶️. Ячейка сама: `git clone --depth 1` →
`pip install -r requirements.txt` → спросит токен (или возьмёт из 🔑 Secrets)
→ запустит процесс и покажет логи. Остановка — ■. Colab засыпает без
активности, для 24/7 нужен сервер. Токен в файл ноутбука больше не пишется.

### 5.4 VPS (systemd, без Docker)

```bash
git clone https://github.com/Yurich-citycode/SevastopolAIbot.git /opt/sevastopol-ai-bot
cd /opt/sevastopol-ai-bot && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo install -m 600 /dev/null /etc/sevastopol-ai-bot.env   # TG_TOKEN=… ADMIN_ID=…
```

Юнит — в `README.md` → «systemd (VPS без Docker)» и `SECURITY.md` → раздел 5
(`EnvironmentFile`, `Restart=always`, `NoNewPrivileges`, `ProtectSystem`).

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now sevastopol-ai-bot
journalctl -u sevastopol-ai-bot -f
```

### 5.5 Форма предложений (отдельно от бота)

1. `suggest.html` публикуется GitHub Pages (Settings → Pages → `main`, `/`).
2. Worker: Dashboard → Create Worker → вставить `worker/index.js` → Deploy,
   затем секреты `BOT_TOKEN` и `ADMIN_ID` (или `npx wrangler secret put …`).
3. Адрес Worker'а — в `suggest.html`, переменная `WORKER_URL` (сейчас там
   `https://sevastopol-suggest.web3yurich.workers.dev`).

---

## 6. Как переносить (миграция)

### 6.1 Переезд на новый сервер / платформу

1. **Секреты.** На новом месте задай `TG_TOKEN` и `ADMIN_ID`: `--env-file`
   (Docker), `EnvironmentFile` (systemd), Variables (Railway/Render),
   `fly secrets set`, `wrangler secret put`, Vault/Doppler — что угодно,
   боту хватает `os.getenv()`. Код менять **не нужно**.
2. **Состояние.** Забери `bot_state.json` со старого места и положи на новое —
   иначе обнулятся XP-паспорта, рефералы и аналитика:

   ```bash
   # Docker: из volume
   docker run --rm -v sevastopol-state:/data -v "$PWD":/backup alpine \
     cp /data/bot_state.json /backup/
   # systemd: просто файл в WorkingDirectory
   scp user@old:/opt/sevastopol-ai-bot/bot_state.json .
   # на новое место
   docker cp bot_state.json sevastopol-ai-bot:/data/ && docker restart sevastopol-ai-bot
   ```

   Формат файла обратно совместим: `_normalize_passport()` достраивает
   недостающие поля, битый json не роняет старт (проверено тестами).
3. **Один токен — один процесс.** Сначала останови старый инстанс
   (`docker stop` / `systemctl stop`), потом запускай новый. Иначе
   `409 Conflict: terminated by other getUpdates request`.
4. **Проверка.** В логах `🚀 Бот запущен`; в Telegram `/start` → «Панель
   управления загружена», карусель «🍽 Где поесть» листается, `/admin`
   (для `ADMIN_ID`) показывает статистику и время обновления кэша.
5. **Worker и Pages** переезжать не обязаны: они не зависят от сервера бота.
   Достаточно, что `BOT_TOKEN`/`ADMIN_ID` в секретах Worker'а актуальны.

### 6.2 Смена таблицы / канала / формы

Правится только ENV, код не трогаем: `SPREADSHEET_ID` (новая таблица должна
быть открыта «по ссылке → Читатель» и содержать листы «Где поесть?»,
«Локации», «Маршруты», «События»), `NEWS_CHANNEL_URL`, `SUGGEST_FORM_URL`,
`REFRESH_SECONDS`. После смены `SUGGEST_FORM_URL` — перезапуск бота (значение
читается один раз на старте и «зашивается» в кнопку меню).

### 6.3 Обновление кода на сервере

```bash
cd /opt/sevastopol-ai-bot && git pull && .venv/bin/pip install -r requirements.txt
sudo systemctl restart sevastopol-ai-bot
# Docker: docker build -t sevastopol-ai-bot . && docker rm -f sevastopol-ai-bot && docker run … (volume остаётся)
```

Откат: `git checkout <предыдущий коммит>` → рестарт. Состояние не теряется
(файл живёт вне кода / в volume).

---

## 7. Что НЕ менялось (поведение сохранено 1:1)

- **Карусели** еды / локаций / маршрутов: тексты, эмодзи, кнопки, шеринг
  («⭐ Сохранить / Скинуть другу»), счётчик `🔹 N / M 🔹`, кольцевая навигация
  `(index ± 1) % total`, «🎲 Случайное место/локация/маршрут».
- **Анимации и способ обновления карточки**: `_send_carousel_page` —
  `edit_media` для фото→фото, иначе `delete` + `answer_photo` / `answer`;
  `send_card` — сначала ответ, потом удаление старого сообщения;
  «Секунду, ищу ближайшие...» с `ReplyKeyboardRemove` и возврат главной
  клавиатуры вместе с карточкой. Всё побайтово как было.
- **Еда**: 6 категорий, фильтры «рядом со мной / НА РАЙОНЕ / все списком /
  по подкатегории», `nearfood_back` — возврат на ту же карточку, откуда ушли.
- **События**: одним сообщением, маркеры 1️⃣…🔟, запас 300 символов до лимита
  4096, кнопки билетов, подпись «Показаны первые N из M».
- **Паспорт/XP**: +10 за создание, ранги и уровни, прогресс-бар, «раз в день
  на действие», `daily_xp` с очисткой прошлых дней.
- **Рефералы**: +25 XP за регистрацию, +40 XP после 7 дней активности,
  защита от самореферала и повторного начисления, уведомление рефереру.
- **Форма предложений**: `SUGGEST_WEB_PREFIX`, пересылка `copy_to(ADMIN_ID)`,
  +5 XP, резервный режим «вставь текст в бота».
- **Роутинг колбэков**: порядок веток и префиксы не тронуты (важно: `page_`
  раньше `locselect_`, `rnd_` раньше `cat_` и т.д.).
- **Лимиты Telegram**: подпись фото ≤ 1024, текст ≤ 4096, `callback_data`
  ≤ 64 байта с обрезкой и логом.
- **Устойчивость**: пустые строки таблицы отсеиваются, «нан»-значения не
  показываются, латинские шапки «Bремя работы»/«Bконтакте» читаются, ссылки на
  посты `t.me` не отдаются как фото, битый `bot_state.json` не роняет старт.

Единственное видимое изменение для пользователя: если `ADMIN_ID` не задан,
`/admin` молчит и заявки с формы не пересылаются (в логе — предупреждение).
При заданном `ADMIN_ID` всё как раньше.

---

## 8. Проверки (как воспроизвести)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python tests/test_carousels.py
#   ИТОГ: 111 прошло, 0 упало

.venv/bin/python tools/check_base.py
#   ошибок: 0 · предупреждений: 20   (13 событий с прошедшей датой)

.venv/bin/python -m pyflakes sevastopolaibot.py tests/test_carousels.py tools/*.py
#   тихо (неиспользуемых импортов и переменных нет)

.venv/bin/python -m compileall -q sevastopolaibot.py tools tests
#   compile OK

grep -rEn "[0-9]{8,10}:AA[0-9A-Za-z_-]{30}" . --exclude-dir=.git --exclude-dir=.venv
#   пусто (в рабочей копии токенов нет)

grep -rn "6106999216" . --exclude-dir=.git --exclude-dir=.venv --exclude=AUDIT_REPORT.md
#   пусто в коде, шаблонах, README и Worker'е
#   (единственное совпадение — assert в tests/test_carousels.py, который как раз
#    проверяет отсутствие этого ID в исходнике бота)

grep -rn "TELETHON\|FORWARDER\|telethon\|forwarder" . \
  --exclude-dir=.git --exclude-dir=.venv --exclude=AUDIT_REPORT.md
#   пусто (парсер и его переменные удалены отовсюду, кроме этого отчёта,
#   где они процитированы как «что именно удалено»)

.venv/bin/python -c "import os; os.environ.pop('TG_TOKEN',None); \
  import sevastopolaibot as b; print('token:', repr(b.TG_TOKEN), '| admin:', b.ADMIN_ID)"
#   token: '' | admin: None      → бот без ENV не стартует и ничего не зашил
```

Что покрыто новыми тестами (блок «12. Конфигурация из ENV»): `TG_TOKEN` и
`ADMIN_ID` берутся из окружения, `is_admin()` работает, `env_int()` не падает
на мусоре, `env_str()` отдаёт дефолт на пустом значении, `load_env()` читает
файл из `ENV_FILE`, реальное окружение приоритетнее `.env`, в исходнике нет
токена и личного `ADMIN_ID`, `python-dotenv` подключён, `bot_state.json`
сохраняется с правами 600.

Тесты не трогают сеть и Telegram: кэш заполняется из `Sevastopol AI База.xlsx`,
объекты aiogram — заглушки, состояние пишется во временный файл.

---

## 9. Рекомендации на будущее (не блокирует)

1. **Отозвать токен** из п.4.1 и (по желанию) вычистить git-историю —
   `SECURITY.md` → раздел 3.
2. **Обновить лист «События»** — 13 событий с прошедшей датой (п.4.7).
3. **CI**: добавить `.github/workflows/test.yml` — `pip install -r requirements.txt`
   и `python tests/test_carousels.py` на каждый push/PR (тесты не требуют
   секретов, `TG_TOKEN` подставляется заглушкой внутри теста).
4. **Зафиксировать версии**: `requirements.txt` сейчас с диапазонами
   (`aiogram>=3.7,<4`). Для воспроизводимого деплоя стоит добавить
   `requirements.lock` (`pip freeze`) или `pip-tools`.
5. **Форматтер**: `ruff format` / `black` — стиль уже приведён к PEP 8
   (2 пустые строки между функциями), конфиг закрепит его навсегда.
6. **`bot_state.json` растёт**: аналитика обрезается до 2000 записей, этого
   хватает для `/admin`, но для долгосрочной истории лучше выгружать в
   Google-таблицу (листы People/Analytics/Passport уже заготовлены).
7. **Два больших бинарника в git** (`xlsx` 75 КБ, `zip` 612 КБ). Если база
   будет расти — вынести их в релизы/Git LFS, в репозитории оставить только
   `xlsx`.
8. **`suggest.html`**: поле `WORKER_URL` зашито в HTML. Если Worker переедет,
   страницу придётся править и ждать обновления Pages; альтернатива — вынести
   адрес в `config.js` рядом со страницей.
