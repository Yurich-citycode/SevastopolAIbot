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

## Запуск в Google Colab (ноутбук «Парсер»)

### Ячейка 1 — установка

```python
!pip install -q telethon
```

### Ячейка 2 — вход (один раз, печатает строку сессии)

```python
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(input("TELETHON_API_ID (my.telegram.org → API development tools): ").strip())
API_HASH = input("TELETHON_API_HASH: ").strip()

client = TelegramClient(StringSession(), API_ID, API_HASH)
client.parse_mode = None
await client.start()              # спросит телефон, код из Telegram, пароль 2FA
me = await client.get_me()
print("Аккаунт:", me.first_name, "@%s" % me.username, "id", me.id)
print("\nTELETHON_SESSION (скопируй в ячейку 3):")
print(client.session.save())
await client.disconnect()
```

### Ячейка 3 — настройки

```python
API_ID = 12345678                                        # свой
API_HASH = "0123456789abcdef0123456789abcdef"            # свой
SESSION = "1BVtsOK…"                                     # строка из ячейки 2
CHANNELS = ["https://t.me/Sevastopol_AI"]                # любые публичные каналы
TARGET = "me"                                            # "me" = Избранное
POLL_SECONDS = 12
INCLUDE_HISTORY = False
```

### Ячейка 4 — запуск (полностью самодостаточный код)

```python
import asyncio, io, json, os, time
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

STATE_PATH = "/content/forwarder_state.json"
FETCH_LIMIT, TEXT_LIMIT, CAPTION_LIMIT = 15, 4096, 1024
NON_FILE_MEDIA = ("MessageMediaWebPage", "MessageMediaContact", "MessageMediaGeo",
                  "MessageMediaGeoLive", "MessageMediaVenue", "MessageMediaPoll",
                  "MessageMediaDice", "MessageMediaInvoice", "MessageMediaGame",
                  "MessageMediaStory")

def log(m): print(time.strftime("[%H:%M:%S] ") + m, flush=True)

def norm_source(s):
    s = str(s or "").strip()
    for p in ("https://", "http://"):
        if s.lower().startswith(p): s = s[len(p):]
    for d in ("t.me/", "telegram.me/", "telegram.dog/"):
        if s.lower().startswith(d): s = s[len(d):]
    s = s.split("?", 1)[0].split("#", 1)[0].strip("/")
    parts = [p for p in s.split("/") if p]
    if not parts: return ""
    if parts[0].lower() == "c" and len(parts) > 1 and parts[1].lstrip("-").isdigit():
        return "-100" + parts[1].lstrip("-")
    if parts[0].lower() == "s" and len(parts) > 1: parts = parts[1:]
    name = parts[0].lstrip("@").strip()
    return "" if (not name or name.startswith("+")) else name

def post_link(src, mid):
    src = str(src)
    if src.lstrip("-").isdigit():
        internal = src[4:] if src.startswith("-100") else src.lstrip("-")
        return "https://t.me/c/%s/%s" % (internal, mid)
    return "https://t.me/%s/%s" % (src.lstrip("@"), mid)

def group_new(msgs):
    groups, index = [], {}
    for m in msgs:
        gid = getattr(m, "grouped_id", None)
        if gid:
            if gid in index: index[gid].append(m)
            else:
                b = [m]; index[gid] = b; groups.append(b)
        else: groups.append([m])
    return groups

def clip_entities(ents, limit):
    if not ents: return None
    out = []
    for e in ents:
        o, l = getattr(e, "offset", 0), getattr(e, "length", 0)
        if o >= limit: continue
        if o + l > limit:
            try: e = e.clone()
            except Exception: continue
            e.length = limit - o
        out.append(e)
    return out or None

def media_is_file(m):
    media = getattr(m, "media", None)
    return media is not None and type(media).__name__ not in NON_FILE_MEDIA

def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("channels"), dict): return d
    except Exception: pass
    return {"version": 2, "channels": {}}

def save_state(state):                       # атомарно: tmp + os.replace
    state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)

async def send_media(client, target, m, caption, ents):
    try:
        await client.send_file(target, file=m.media, caption=caption,
                               formatting_entities=ents,
                               attributes=getattr(m, "attributes", None))
        return
    except Exception as e:
        log("   ⚠️ медиа по ссылке не ушло (%s) — скачиваю" % e)
    buf = io.BytesIO(); await client.download_media(m, file=buf); buf.seek(0)
    await client.send_file(target, file=buf, caption=caption, formatting_entities=ents)

async def copy_group(client, target, key, entity, group, title):
    ids = [m.id for m in group]
    link = post_link(key, ids[0])
    try:                                     # 1) форвард: альбом едет группой
        await client.forward_messages(target, ids, from_peer=entity)
        log("   ↪️ форвард «%s» id %s" % (title, ids if len(ids) > 1 else ids[0]))
        return
    except FloodWaitError as e:
        log("   ⏳ FloodWait %d c" % e.seconds); await asyncio.sleep(e.seconds)
        await client.forward_messages(target, ids, from_peer=entity); return
    except Exception as e:                   # 2) запрет форвардов → ручная копия
        log("   ⚠️ форвард не сработал (%s) — копирую вручную" % e)
    album = len(group) > 1
    for i, m in enumerate(group):
        text = m.message or ""
        tail_link = link if (not album or i == len(group) - 1) else None
        tail = "\n\n🔗 " + tail_link if tail_link else ""
        try:
            if media_is_file(m):
                if len(text) + len(tail) > CAPTION_LIMIT:
                    await send_media(client, target, m, text[:CAPTION_LIMIT],
                                     clip_entities(m.entities, CAPTION_LIMIT))
                    if tail_link: await client.send_message(target, "🔗 " + tail_link)
                else:
                    await send_media(client, target, m, text + tail, m.entities)
            else:
                body = text or ("(медиа без описания)" if getattr(m, "media", None) else "")
                if len(body) + len(tail) <= TEXT_LIMIT:
                    await client.send_message(target, body + tail, formatting_entities=m.entities)
                else:
                    await client.send_message(target, body[:TEXT_LIMIT],
                                              formatting_entities=clip_entities(m.entities, TEXT_LIMIT))
                    if tail_link: await client.send_message(target, "🔗 " + tail_link)
            log("   📄 копия «%s» id %d" % (title, m.id))
        except FloodWaitError as e:
            log("   ⏳ FloodWait %d c" % e.seconds); await asyncio.sleep(e.seconds)
        except Exception as e:
            log("   ⚠️ не скопировал id %d: %s" % (m.id, e))
            try: await client.send_message(target, "🔗 " + link)
            except Exception: pass

async def poll_channel(client, cfg_target, src, state):
    key, entity, title = src["key"], src["entity"], src["title"]
    try:
        msgs = list(await client.get_messages(entity, limit=FETCH_LIMIT) or [])
    except FloodWaitError as e:
        log("⏳ FloodWait «%s»: %d c" % (title, e.seconds)); await asyncio.sleep(e.seconds); return 0
    except Exception as e:
        log("⚠️ «%s»: %s" % (title, e)); return 0
    if not msgs: return 0
    asc = sorted(msgs, key=lambda m: m.id)
    newest = asc[-1].id
    saved = state["channels"].get(key)
    if saved is None:                        # первый запуск
        saved = max(0, newest - FETCH_LIMIT) if INCLUDE_HISTORY else newest
        log("«%s»: отсчёт с id %s%s" % (title, saved,
            "" if INCLUDE_HISTORY else " (историю не копирую)"))
    fresh = [m for m in asc if m.id > saved and not getattr(m, "action", None)]
    if fresh:
        log("📨 «%s»: новых %d" % (title, len(fresh)))
        for g in group_new(fresh):
            try:
                await copy_group(client, cfg_target, key, entity, g, title)
            except FloodWaitError as e:
                log("⏳ FloodWait %d c" % e.seconds); await asyncio.sleep(e.seconds)
                try: await copy_group(client, cfg_target, key, entity, g, title)
                except Exception as e2: log("   ⚠️ %s" % e2)
            except Exception as e:
                log("⚠️ ошибка на id %s: %s" % ([m.id for m in g], e))
    state["channels"][key] = max(newest, state["channels"].get(key) or 0)
    save_state(state)
    return len(fresh)

client = TelegramClient(StringSession(SESSION.strip()), API_ID, API_HASH.strip())
client.parse_mode = None                    # шлём текст как есть + исходные entities
await client.connect()
if not await client.is_user_authorized():
    raise SystemExit("Сессия недействительна — выполни ячейку 2 заново")
me = await client.get_me()
log("Аккаунт: %s (@%s)" % (me.first_name, me.username))
target = "me" if str(TARGET).lower() in ("me", "self", "saved") else (
    int(TARGET) if str(TARGET).lstrip("-").isdigit() else norm_source(TARGET))
sources = []
for raw in CHANNELS:
    key = norm_source(raw)
    if not key: continue
    try:
        e = await client.get_entity(int(key) if key.lstrip("-").isdigit() else key)
        sources.append({"key": key, "entity": e, "title": getattr(e, "title", None) or key})
    except Exception as ex:
        log("⚠️ канал %r недоступен: %s" % (raw, ex))
if not sources: raise SystemExit("Ни один канал не открылся — проверь ссылки")
state = load_state()
log("Каналов: %d · опрос раз в %d c · цель: %s" % (len(sources), POLL_SECONDS, TARGET))
try:
    while True:
        for src in sources:
            await poll_channel(client, target, src, state)
        await asyncio.sleep(POLL_SECONDS)
except KeyboardInterrupt:
    log("Остановлено. Прогресс в %s" % STATE_PATH)
finally:
    save_state(state)
    await client.disconnect()
```

> Colab засыпает без активности: держи вкладку открытой. Стейт лежит в
> `/content/forwarder_state.json` — пока жив диск, перезапуск ячейки не даёт
> дубликатов; на новом рантайме стейт пустой и парсер снова стартует
> «с последнего поста».

---

## Частые вопросы

- **Канал не читается** — он приватный (вход только по пригласительной ссылке)
  или ты не подписан. Публичные каналы по `https://t.me/имя` читаются всегда.
- **«forwarding messages is disabled»** — канал запретил форварды; скрипт сам
  переключается на ручную копию со ссылкой на оригинал.
- **Сколько каналов можно** — десятки; узкое место не чтение, а отправка.
  При большом потоке Telegram выдаёт `FloodWait` — скрипт ждёт сам.
- **Основной бот при этом может не работать** — сервисы полностью независимы.
