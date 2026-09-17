# Парсер каналов на личном аккаунте (отдельный сервис)

`events/forwarder.py` — самостоятельный скрипт, **не часть основного бота**.

**Зачем личный аккаунт.** Боты Telegram не видят каналы, где они не
администраторы, — чужие городские каналы так не прочитать. Поэтому здесь
работает **юзер-клиент Telethon**: он заходит под твоим личным аккаунтом и
читает **любой публичный канал по ссылке** (`https://t.me/имя`), ничего не
спрашивая у владельцев.

**Что делает:** раз в `poll_seconds` смотрит каналы из `events/sources.json`
и новые посты копирует в цель (`target`, по умолчанию `me` — «Избранное»
твоего аккаунта):

- сначала пробует **форвард** — тогда в посте остаётся подпись канала-источника,
  а альбомы пересылаются одной группой (по `grouped_id`);
- если канал **запретил форвардирование** — делает ручную копию: медиа/текст
  с исходным форматированием (`entities`) + строка `🔗 https://t.me/канал/ид`
  (у альбома ссылка одна, в конце);
- служебные сообщения канала (заявка на вступление, закреплённый пост и т.п.)
  пропускаются;
- `FloodWaitError` — честно ждём `e.seconds` и повторяем;
- прогресс (последний виденный id по каждому каналу) хранится в
  `events/forwarder_state.json` **атомарно** — после перезапуска дубликатов нет;
- первый запуск **без** `include_history` стартует с последнего поста: старая
  история не выливается.

**Зависимость одна** — `telethon`:

```bash
pip install telethon
```

В корневой `requirements.txt` её **нет** (там зависимости бота).

---

## 1. API_ID и API_HASH (2 минуты)

1. Открой https://my.telegram.org и войди под **своим** аккаунтом (телефон).
2. Подтверди вход кодом из Telegram.
3. Перейди в **API development tools**.
4. Заполни форму (App title / Short name — любые, например `Sevastopol Parser`,
   Platform: `Other`) → **Create application**.
5. Получишь `api_id` (число) и `api_hash` (строка). Это ключи **твоего
   аккаунта**, не бота.

## 2. Секреты — только в `events/.env`

Создай файл `events/.env` (он в `.gitignore`, в git не попадает):

```
TELETHON_API_ID=12345678
TELETHON_API_HASH=0123456789abcdef0123456789abcdef
TELETHON_SESSION=
FORWARDER_TARGET=me
```

| Переменная | Что это |
|---|---|
| `TELETHON_API_ID` | число из my.telegram.org |
| `TELETHON_API_HASH` | строка оттуда же |
| `TELETHON_SESSION` | строка сессии — выдаёт команда `login` |
| `FORWARDER_TARGET` | куда копировать: `me` (Избранное, по умолчанию), `@username`, `https://t.me/username` или числовой id чата |

> ⚠️ **Строка сессии = полный доступ к твоему аккаунту** (читать и писать от
> твоего имени). Не публикуй её, не присылай никому в чаты, не коммить в git.
> Скомпрометирована — Telegram → Настройки → Устройства → убей сессию и
> сделай `login` заново.

## 3. Вход: `login`

```bash
python events/forwarder.py login --save
```

Скрипт спросит телефон (в формате `+7…`), затем код из Telegram и, если
включена, облачный пароль (2FA). После входа напечатает **строку сессии**
(`TELETHON_SESSION=1BVts…`) и с флагом `--save` сам допишет её в
`events/.env` (права файла 600). Без `--save` — просто скопируй строку руками.

Повторно входить не нужно: дальше всё работает по сохранённой строке сессии.

## 4. Список каналов: `events/sources.json`

```json
{
  "target": "me",
  "channels": [
    "https://t.me/Sevastopol_AI",
    "@another_channel",
    "https://t.me/third/123"
  ],
  "poll_seconds": 12,
  "include_history": false
}
```

- ссылки нормализуются автоматически: `https://t.me/name/123` → `name`,
  `t.me/s/name` → `name`, приватная `https://t.me/c/1234567890/55` →
  `-1001234567890`;
- `target` — куда копировать (переменная `FORWARDER_TARGET` важнее этого поля);
- `poll_seconds` — пауза между кругами опроса (минимум 3, по умолчанию 12);
- `include_history: true` — на первом запуске скопировать последние
  ~15 постов каждого канала вместо «только новые».

## 5. Запуск: `run`

```bash
python events/forwarder.py run
```

Остановка — `Ctrl+C` (прогресс сохраняется). Полезные флаги:

```bash
python events/forwarder.py run --once    # один круг и выйти (проверка настроек)
python events/forwarder.py run --reset   # забыть прогресс, начать с текущих постов
```

---

## Проверка кода

```bash
python -m py_compile events/forwarder.py   # синтаксис
python tests/test_forwarder.py             # ссылки, альбомы, стейт, логика копирования
```

Тесты работают **без telethon и без сети** (объекты-заглушки).

---

## Запуск в Google Colab (одна ячейка)

Открой `notebooks/SevastopolAI_parser.ipynb` (или скопируй ячейку ниже),
впиши `API_ID` / `API_HASH` и нажми ▶️. `SESSION` оставь пустым — ячейка сама
спросит телефон и код из Telegram, напечатает строку сессии и продолжит работу.

```python
# ═══════════ Sevastopol AI — парсер каналов одной ячейкой ═══════════
API_ID = 0                                     # ← my.telegram.org → API development tools
API_HASH = ""                                  # ← оттуда же
SESSION = ""                                   # пусто → ячейка спросит телефон и код сама

CHANNELS = ["https://t.me/Sevastopol_AI"]      # любые публичные каналы (ссылка или @имя)
TARGET = "me"                                  # "me" = Избранное, либо "@имя" / "-1001234567890"
POLL_SECONDS = 12                              # пауза между кругами опроса
INCLUDE_HISTORY = False                        # True — на старте скопировать последние ~15 постов

import json, os, pathlib, shutil, subprocess, sys

REPO = "https://github.com/Yurich-citycode/SevastopolAIbot.git"
DIR = "/content/SevastopolAIbot"


def sh(*cmd, cwd=None):
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


# 1) код + telethon
if os.path.isdir(DIR):
    if subprocess.run(["git", "-C", DIR, "pull", "--ff-only", "origin", "main"]).returncode:
        shutil.rmtree(DIR)                      # локальные правки мешают — клонируем заново
if not os.path.isdir(DIR):
    sh("git", "clone", "--depth", "1", REPO, DIR)
sh(sys.executable, "-m", "pip", "install", "-q", "telethon")

# 2) список каналов и настройки (events/sources.json)
(pathlib.Path(DIR) / "events" / "sources.json").write_text(json.dumps({
    "target": TARGET,
    "channels": CHANNELS,
    "poll_seconds": POLL_SECONDS,
    "include_history": INCLUDE_HISTORY,
}, ensure_ascii=False, indent=2), encoding="utf-8")

os.environ["TELETHON_API_ID"] = str(API_ID)
os.environ["TELETHON_API_HASH"] = API_HASH
os.environ["FORWARDER_TARGET"] = TARGET

sys.path.insert(0, os.path.join(DIR, "events"))
import forwarder as fw

# 3) вход, если строки сессии ещё нет (спросит телефон, код из Telegram, 2FA)
if not SESSION.strip():
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    client.parse_mode = None
    await client.start()
    me = await client.get_me()
    SESSION = client.session.save()
    print("Аккаунт: %s (@%s, id %s)" % (me.first_name, me.username, me.id))
    print("\nTELETHON_SESSION — сохрани, чтобы не входить заново:")
    print(SESSION)
    await client.disconnect()
os.environ["TELETHON_SESSION"] = SESSION.strip()

# 4) запуск — живёт, пока не нажмёшь ■; прогресс в events/forwarder_state.json
await fw.run_async(reset=False, once=False)
```

Ячейка использует тот же код, что и `events/forwarder.py` — логика одна,
расхождений между Colab и сервером нет.

Остановка — ■ (прервать ячейку). Прогресс (последний виденный id по каждому
каналу) лежит в `/content/SevastopolAIbot/events/forwarder_state.json`: пока жив
рантайм, перезапуск ячейки не даёт дубликатов. На новом рантайме диска нет —
парсер снова стартует «с последнего поста», старую историю не льёт.

⚠️ Строка сессии печатается в выводе ячейки. Не публикуй ноутбук с ней;
скомпрометирована — Telegram → Настройки → Устройства → заверши сессию.

---

## Частые вопросы

- **Канал не читается** — он приватный (вход только по пригласительной ссылке)
  или ты не подписан. Публичные каналы по `https://t.me/имя` читаются всегда.
- **«forwarding messages is disabled»** — канал запретил форварды; скрипт сам
  переключается на ручную копию со ссылкой на оригинал.
- **Сколько каналов можно** — десятки; узкое место не чтение, а отправка.
  При большом потоке Telegram выдаёт `FloodWait` — скрипт ждёт сам.
- **Основной бот при этом может не работать** — сервисы полностью независимы.
