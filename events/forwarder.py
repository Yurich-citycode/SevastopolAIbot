#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер каналов на ЛИЧНОМ аккаунте (Telethon) — отдельный сервис, не часть бота.

Боты не видят каналы, где они не админы, поэтому здесь работает юзер-клиент:
он читает ЛЮБОЙ публичный канал по ссылке и копирует новые посты
(текст / фото / видео / альбомы, с форматированием и caption) в целевой чат —
по умолчанию в «Избранное» личного аккаунта.

Единственная зависимость — telethon:
    pip install telethon
(в корневой requirements.txt её НЕТ — там зависимости основного бота)

СЕКРЕТЫ — только в окружении или в файле events/.env (в git не попадает):
    TELETHON_API_ID     — my.telegram.org → API development tools
    TELETHON_API_HASH   — там же
    TELETHON_SESSION    — строка сессии (команда login её печатает)
    FORWARDER_TARGET    — куда копировать: "me" (Избранное, по умолчанию),
                          "@username", "https://t.me/username" или числовой id

⚠️ Строка сессии = полный доступ к аккаунту. Никому её не показывай.

Команды:
    python events/forwarder.py login            # войти и напечатать строку сессии
    python events/forwarder.py login --save     # …и дописать её в events/.env
    python events/forwarder.py run              # запустить парсер (Ctrl+C — стоп)
    python events/forwarder.py run --reset      # забыть прогресс и начать заново
    python events/forwarder.py run --once       # один проход и выход (проверка)

Список каналов — events/sources.json. Подробная инструкция — events/README.md.
"""

import asyncio
import io
import json
import os
import sys
import time

try:
    # telethon — единственная зависимость парсера. Импорт ошибки здесь нужен,
    # чтобы ниже честно писать `except FloodWaitError`.
    from telethon.errors import FloodWaitError
except ImportError:  # telethon не установлен — чистые функции всё равно работают
    class FloodWaitError(Exception):  # type: ignore[no-redef]
        seconds = 0

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
CONFIG_PATH = os.path.join(BASE_DIR, "sources.json")
STATE_PATH = os.path.join(BASE_DIR, "forwarder_state.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")
ROOT_ENV_PATH = os.path.join(ROOT_DIR, ".env")

# сколько последних постов смотрим за один опрос канала
FETCH_LIMIT = 15
# лимиты Telegram
TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024

DEFAULT_POLL_SECONDS = 12
DEFAULT_TARGET = "me"

# эти «медиа» файлом не отправить — копируем как текст
NON_FILE_MEDIA = (
    "MessageMediaWebPage", "MessageMediaContact", "MessageMediaGeo",
    "MessageMediaGeoLive", "MessageMediaVenue", "MessageMediaPoll",
    "MessageMediaDice", "MessageMediaInvoice", "MessageMediaGame",
    "MessageMediaStory",
)

SELF_WORDS = ("me", "self", "saved", "избранное")


def log(msg):
    print(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg, flush=True)


# ──────────────────────────── окружение и конфиг ────────────────────────────

def _read_env_file(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def load_dotenv():
    """Секреты читаем из events/.env, затем из корневого .env (оба не обязательны)."""
    _read_env_file(ENV_PATH)
    _read_env_file(ROOT_ENV_PATH)


def write_env_file(path, values):
    """Дописывает/обновляет KEY=VALUE в .env-файле (атомарно, права 600)."""
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    left = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in left:
            out.append("%s=%s" % (key, left.pop(key)))
        else:
            out.append(line)
    for key, val in left.items():
        out.append("%s=%s" % (key, val))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip("\n") + "\n")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def env(name, default=""):
    return os.getenv(name, default).strip()


# ────────────────────────── нормализация ссылок ─────────────────────────────

def norm_source(s):
    """
    Любой вид ссылки/имени канала → короткое имя (или числовой id строкой).

        https://t.me/name/123  → name
        https://t.me/s/name    → name
        t.me/name              → name
        @name                  → name
        name                   → name
        https://t.me/c/1234/56 → -1001234        (приватный канал)
        -1001234567890         → -1001234567890
    """
    s = str(s or "").strip()
    if not s:
        return ""
    for prefix in ("https://", "http://"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
    for domain in ("t.me/", "telegram.me/", "telegram.dog/"):
        if s.lower().startswith(domain):
            s = s[len(domain):]
    s = s.split("?", 1)[0].split("#", 1)[0].strip("/")
    parts = [p for p in s.split("/") if p]
    if not parts:
        return ""
    # приватный канал: t.me/c/<внутренний id>/<номер поста>
    if parts[0].lower() == "c" and len(parts) > 1 and parts[1].lstrip("-").isdigit():
        return "-100" + parts[1].lstrip("-")
    # предпросмотр канала: t.me/s/name
    if parts[0].lower() == "s" and len(parts) > 1:
        parts = parts[1:]
    name = parts[0].lstrip("@").strip()
    if not name or name.startswith("+"):
        return ""  # пусто или пригласительная ссылка t.me/+… — так не читаем
    return name


def is_numeric(s):
    return str(s).lstrip("-").isdigit()


def post_link(source, message_id):
    """Ссылка на пост: https://t.me/name/123 (приватные — https://t.me/c/id/123)."""
    src = str(source)
    if is_numeric(src):
        internal = src[4:] if src.startswith("-100") else src.lstrip("-")
        return "https://t.me/c/{}/{}".format(internal, message_id)
    return "https://t.me/{}/{}".format(src.lstrip("@"), message_id)


def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError) as e:
            log("⚠️ Не читается %s (%s) — беру значения по умолчанию" % (CONFIG_PATH, e))
            cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    channels = cfg.get("channels") or []
    if isinstance(channels, str):
        channels = [channels]
    try:
        poll = int(cfg.get("poll_seconds") or DEFAULT_POLL_SECONDS)
    except (TypeError, ValueError):
        poll = DEFAULT_POLL_SECONDS
    if poll < 3:
        poll = 3
    return {
        # FORWARDER_TARGET из окружения важнее sources.json
        "target": env("FORWARDER_TARGET") or str(cfg.get("target") or DEFAULT_TARGET),
        "channels": [n for n in (norm_source(c) for c in channels) if n],
        "poll_seconds": poll,
        "include_history": bool(cfg.get("include_history")),
    }


# ─────────────────────────────── стейт (прогресс) ───────────────────────────

def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("channels"), dict):
                return data
        except (OSError, ValueError):
            pass
    return {"version": 2, "channels": {}}


def save_state(state):
    """Атомарная запись: временный файл + os.replace (не побьётся при Ctrl+C)."""
    state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_PATH)


# ─────────────────────────── разбор новых постов ────────────────────────────

def group_new(messages):
    """
    Список постов (по возрастанию id) → список групп: части альбома (общий
    grouped_id) идут одной группой, одиночные посты — группами из одного.
    """
    groups, index = [], {}
    for m in messages:
        gid = getattr(m, "grouped_id", None)
        if gid:
            if gid in index:
                index[gid].append(m)
            else:
                bucket = [m]
                index[gid] = bucket
                groups.append(bucket)
        else:
            groups.append([m])
    return groups


def clip_entities(entities, limit):
    """Обрезает список entities под укороченный текст (смещения остаются валидными)."""
    if not entities:
        return None
    out = []
    for e in entities:
        offset = getattr(e, "offset", 0)
        length = getattr(e, "length", 0)
        if offset >= limit:
            continue
        if offset + length > limit:
            try:
                e = e.clone()
            except Exception:
                continue
            e.length = limit - offset
        out.append(e)
    return out or None


def media_is_file(m):
    """True, если медиа поста можно отправить файлом (фото/видео/документ…)."""
    media = getattr(m, "media", None)
    if media is None:
        return False
    return type(media).__name__ not in NON_FILE_MEDIA


# ──────────────────────────────── login ─────────────────────────────────────

def cmd_login(save=False):
    load_dotenv()
    api_id = env("TELETHON_API_ID")
    api_hash = env("TELETHON_API_HASH")

    print("Вход на ЛИЧНЫЙ аккаунт Telegram (Telethon).")
    print("API_ID / API_HASH: https://my.telegram.org → API development tools.")
    print()
    if not api_id:
        api_id = input("TELETHON_API_ID: ").strip()
    if not api_hash:
        api_hash = input("TELETHON_API_HASH: ").strip()
    if not api_id or not api_hash:
        print("❌ Нужны оба значения — API_ID и API_HASH.")
        sys.exit(1)
    if not api_id.isdigit():
        print("❌ TELETHON_API_ID должен быть числом (например 12345678).")
        sys.exit(1)

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("❌ Не установлен telethon:  pip install telethon")
        sys.exit(1)

    client = TelegramClient(StringSession(), int(api_id), api_hash)
    client.parse_mode = None
    with client:
        client.start()  # спросит телефон, код из Telegram и пароль 2FA (если есть)
        me = client.get_me()
        session_str = client.session.save()

    print()
    log("✓ Вход выполнен: %s (@%s, id %s)" % (
        me.first_name or "", me.username or "—", me.id))
    print()
    print("Строка сессии (TELETHON_SESSION):")
    print(session_str)
    print()
    print("⚠️ Эта строка = полный доступ к аккаунту. Не публикуй и не коммить её.")

    if save:
        values = {"TELETHON_SESSION": session_str}
        if not env("TELETHON_API_ID"):
            values["TELETHON_API_ID"] = api_id
        if not env("TELETHON_API_HASH"):
            values["TELETHON_API_HASH"] = api_hash
        write_env_file(ENV_PATH, values)
        log("✓ Сохранил в %s (файл в .gitignore, права 600)" % ENV_PATH)
    else:
        log("Скопируй строку в events/.env строкой TELETHON_SESSION=… "
            "или перезапусти с --save")
    print()
    log("Дальше: заполни events/sources.json и запусти  python events/forwarder.py run")


# ───────────────────────────────── run ──────────────────────────────────────

def require_credentials():
    api_id = env("TELETHON_API_ID")
    api_hash = env("TELETHON_API_HASH")
    session = env("TELETHON_SESSION")
    missing = [n for n, v in (("TELETHON_API_ID", api_id),
                              ("TELETHON_API_HASH", api_hash),
                              ("TELETHON_SESSION", session)) if not v]
    if missing:
        print("❌ Не заданы: %s" % ", ".join(missing))
        print("   Секреты кладутся в events/.env (шаблон — .env.example в корне).")
        print("   Строку сессии выдаёт команда:  python events/forwarder.py login --save")
        sys.exit(1)
    if not api_id.isdigit():
        print("❌ TELETHON_API_ID должен быть числом.")
        sys.exit(1)
    return int(api_id), api_hash, session


async def resolve_target(client, target):
    """'me' → Избранное аккаунта; '@name' / ссылка / числовой id → сущность."""
    raw = str(target or DEFAULT_TARGET).strip()
    if raw.lower() in SELF_WORDS:
        return "me", "Избранное (%s)" % raw.lower()
    if raw.startswith("-") or is_numeric(raw):
        entity = await client.get_entity(int(raw))
        return entity, "чат id %s" % raw
    name = norm_source(raw)
    entity = await client.get_entity(name)
    title = getattr(entity, "title", None) or getattr(entity, "username", None) or name
    return entity, "«%s»" % title


async def send_with_link(client, target, text, entities, link):
    """Текст с исходными entities + строка «🔗 ссылка» (влезает — одним сообщением)."""
    body = text or ""
    tail = "\n\n🔗 " + link
    if len(body) + len(tail) <= TEXT_LIMIT:
        await client.send_message(target, body + tail, formatting_entities=entities)
        return
    if body:
        await client.send_message(target, body[:TEXT_LIMIT],
                                  formatting_entities=clip_entities(entities, TEXT_LIMIT))
    await client.send_message(target, "🔗 " + link)


async def send_media(client, target, m, caption, entities):
    """
    Медиа вручную: сначала отправляем исходный объект (без скачивания),
    если не вышло — скачиваем в память и шлём файлом.
    """
    kwargs = {"caption": caption, "formatting_entities": entities}
    attributes = getattr(m, "attributes", None)
    try:
        await client.send_file(target, file=m.media, attributes=attributes, **kwargs)
        return
    except Exception as e:
        log("   ⚠️ медиа по ссылке не отправилось (%s) — скачиваю" % e)
    buf = io.BytesIO()
    await client.download_media(m, file=buf)
    buf.seek(0)
    name = None
    for a in (attributes or []):
        name = getattr(a, "file_name", None) or name
    if name:
        buf.name = name
    await client.send_file(target, file=buf, **kwargs)


async def copy_group(client, target, source_key, entity, group, title):
    """
    Группа постов (одиночный пост или альбом) → целевой чат.
    Сначала форвард (сохраняет канал-источник и альбом), при запрете — ручная копия.
    """
    ids = [m.id for m in group]
    link = post_link(source_key, ids[0])

    # 1) форвард: один вызов на всю группу → альбом остаётся альбомом
    try:
        await client.forward_messages(target, ids, from_peer=entity)
        log("   ↪️ форвард: «%s» id %s" % (title, ids if len(ids) > 1 else ids[0]))
        return
    except FloodWaitError as e:
        log("   ⏳ FloodWait на форварде: жду %d c" % e.seconds)
        await asyncio.sleep(e.seconds)
        await client.forward_messages(target, ids, from_peer=entity)
        log("   ↪️ форвард после ожидания: «%s» id %s" % (title, ids))
        return
    except Exception as e:
        log("   ⚠️ форвард не сработал (%s: %s) — копирую вручную"
            % (type(e).__name__, e))

    # 2) ручная копия: медиа/текст как есть + «🔗 ссылка» на оригинал
    album = len(group) > 1
    for i, m in enumerate(group):
        text = m.message or ""
        # у альбома ссылка одна — в самом конце
        tail_link = link if (not album or i == len(group) - 1) else None
        tag = " (альбом %d/%d)" % (i + 1, len(group)) if album else ""
        try:
            if media_is_file(m):
                tail = "\n\n🔗 " + tail_link if tail_link else ""
                if len(text) + len(tail) > CAPTION_LIMIT:
                    # caption не резиновый: текст по лимиту, ссылка отдельно
                    await send_media(client, target, m, text[:CAPTION_LIMIT],
                                     clip_entities(m.entities, CAPTION_LIMIT))
                    if tail_link:
                        await client.send_message(target, "🔗 " + tail_link)
                else:
                    await send_media(client, target, m, text + tail, m.entities)
            else:
                body = text or ("(медиа без описания)" if getattr(m, "media", None) else "")
                if tail_link:
                    await send_with_link(client, target, body, m.entities, tail_link)
                else:
                    await client.send_message(
                        target, body[:TEXT_LIMIT],
                        formatting_entities=clip_entities(m.entities, TEXT_LIMIT))
            log("   📄 копия: «%s» id %d%s" % (title, m.id, tag))
        except FloodWaitError as e:
            log("   ⏳ FloodWait: жду %d c и повторяю id %d" % (e.seconds, m.id))
            await asyncio.sleep(e.seconds)
            await copy_one(client, target, m, text, tail_link, title, tag)
        except Exception as e:
            log("   ⚠️ не скопировал id %d из «%s» (%s: %s)"
                % (m.id, title, type(e).__name__, e))
            try:
                await client.send_message(target, "🔗 " + link)
            except Exception:
                pass


async def copy_one(client, target, m, text, tail_link, title, tag):
    """Повтор одной копии после FloodWait (тело — то же, что в copy_group)."""
    if media_is_file(m):
        tail = "\n\n🔗 " + tail_link if tail_link else ""
        await send_media(client, target, m, (text + tail)[:CAPTION_LIMIT],
                         clip_entities(m.entities, CAPTION_LIMIT))
    else:
        body = text or ("(медиа без описания)" if getattr(m, "media", None) else "")
        if tail_link:
            await send_with_link(client, target, body, m.entities, tail_link)
        else:
            await client.send_message(target, body[:TEXT_LIMIT],
                                      formatting_entities=clip_entities(m.entities, TEXT_LIMIT))
    log("   📄 копия после ожидания: «%s» id %d%s" % (title, m.id, tag))


async def poll_channel(client, cfg, target, src, state):
    """
    Один опрос одного канала: читаем последние FETCH_LIMIT постов, копируем
    те, что новее сохранённого id, и обновляем стейт. Возвращает число постов.
    """
    key, entity, title = src["key"], src["entity"], src["title"]
    try:
        msgs = await client.get_messages(entity, limit=FETCH_LIMIT)
    except FloodWaitError as e:
        log("⏳ FloodWait на «%s»: жду %d c" % (title, e.seconds))
        await asyncio.sleep(e.seconds)
        return 0
    except Exception as e:
        log("⚠️ «%s»: не прочитал (%s: %s)" % (title, type(e).__name__, e))
        return 0

    msgs = list(msgs or [])
    if not msgs:
        return 0

    asc = sorted(msgs, key=lambda m: m.id)
    newest = asc[-1].id
    saved = state["channels"].get(key)

    if saved is None:
        # первый запуск: без include_history стартуем с последнего поста —
        # историю не льём, только то, что появится дальше
        saved = max(0, newest - FETCH_LIMIT) if cfg["include_history"] else newest
        log("«%s»: точка отсчёта id %s%s" % (
            title, saved, "" if cfg["include_history"] else " (историю не копирую)"))

    fresh, service = [], 0
    for m in asc:
        if m.id <= saved:
            continue
        if getattr(m, "action", None):
            service += 1          # служебные сообщения не копируем
            continue
        fresh.append(m)
    if service:
        log("«%s»: пропущено служебных сообщений: %d" % (title, service))

    if fresh:
        log("📨 «%s»: новых постов %d" % (title, len(fresh)))
        for group in group_new(fresh):
            try:
                await copy_group(client, target, key, entity, group, title)
            except FloodWaitError as e:
                log("⏳ FloodWait: жду %d c" % e.seconds)
                await asyncio.sleep(e.seconds)
                try:
                    await copy_group(client, target, key, entity, group, title)
                except Exception as e2:
                    log("⚠️ не вышло после ожидания: %s" % e2)
            except Exception as e:
                log("⚠️ ошибка на постах id %s: %s" % ([m.id for m in group], e))

    # прогресс — на максимальный увиденный id (служебные в том числе),
    # чтобы после перезапуска не было дубликатов
    state["channels"][key] = max(newest, state["channels"].get(key) or 0)
    save_state(state)
    return len(fresh)


async def poll_round(client, cfg, target, sources, state):
    """Один круг по всем каналам."""
    total = 0
    for src in sources:
        total += await poll_channel(client, cfg, target, src, state)
    return total


async def run_async(reset=False, once=False):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id, api_hash, session_str = require_credentials()
    cfg = load_config()
    if not cfg["channels"]:
        print("❌ Пустой список каналов в %s." % CONFIG_PATH)
        print('   Пример: {"target":"me","channels":["https://t.me/имя"],'
              '"poll_seconds":12,"include_history":false}')
        sys.exit(1)

    try:
        client = TelegramClient(StringSession(session_str), api_id, api_hash)
    except Exception as e:
        print("❌ Не удалось прочитать TELETHON_SESSION (%s: %s)." % (type(e).__name__, e))
        print("   Получи новую строку:  python events/forwarder.py login --save")
        sys.exit(1)
    client.parse_mode = None  # текст шлём как есть + исходные entities

    try:
        await client.connect()
    except Exception as e:
        print("❌ Не подключился к Telegram (%s: %s). Проверь сеть." % (type(e).__name__, e))
        sys.exit(1)
    if not await client.is_user_authorized():
        print("❌ Сессия недействительна. Заново:  python events/forwarder.py login --save")
        await client.disconnect()
        sys.exit(1)

    me = await client.get_me()
    log("Аккаунт: %s (@%s, id %s)" % (me.first_name or "", me.username or "—", me.id))

    try:
        target, target_name = await resolve_target(client, cfg["target"])
    except Exception as e:
        print("❌ Не удалось определить целевой чат %r: %s" % (cfg["target"], e))
        await client.disconnect()
        sys.exit(1)
    log("Куда копирую: %s" % target_name)

    sources = []
    for raw in cfg["channels"]:
        try:
            entity = await client.get_entity(raw)
        except Exception as e:
            log("⚠️ Канал %r недоступен (%s: %s) — пропускаю" % (raw, type(e).__name__, e))
            continue
        sources.append({"key": raw,
                        "entity": entity,
                        "title": getattr(entity, "title", None) or raw})
    if not sources:
        print("❌ Ни один канал из sources.json не открылся. Проверь ссылки.")
        await client.disconnect()
        sys.exit(1)

    state = load_state()
    if reset:
        state["channels"] = {}
        save_state(state)
        log("--reset: прогресс очищен")

    log("Каналов: %d · опрос раз в %d c · история: %s" % (
        len(sources), cfg["poll_seconds"],
        "копирую" if cfg["include_history"] else "не копирую"))
    for s in sources:
        last = state["channels"].get(s["key"])
        log("  · %s — %s" % (
            s["title"],
            "последний виденный id %s" % last if last is not None else "новый источник"))

    try:
        while True:
            await poll_round(client, cfg, target, sources, state)
            if once:
                log("--once: один проход сделан, выхожу")
                break
            await asyncio.sleep(cfg["poll_seconds"])
    finally:
        save_state(state)
        await client.disconnect()


def cmd_run(reset=False, once=False):
    load_dotenv()
    require_credentials()
    try:
        asyncio.run(run_async(reset=reset, once=once))
    except KeyboardInterrupt:
        print()
        log("Остановлено (Ctrl+C). Прогресс сохранён в %s" % STATE_PATH)


# ───────────────────────────────── main ─────────────────────────────────────

USAGE = """Использование:
  python events/forwarder.py login [--save]         войти и получить строку сессии
  python events/forwarder.py run [--reset] [--once] запустить парсер каналов
"""


def main(argv):
    cmd = argv[0] if argv else "run"
    flags = argv[1:]
    if cmd == "login":
        cmd_login(save="--save" in flags)
    elif cmd == "run":
        cmd_run(reset="--reset" in flags, once="--once" in flags)
    elif cmd in ("-h", "--help", "help"):
        print(USAGE)
    else:
        print("❌ Неизвестная команда: %s\n" % cmd)
        print(USAGE)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        print()
        log("Остановлено (Ctrl+C).")
