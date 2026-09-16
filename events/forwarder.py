#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Форвардер постов каналов — ОТДЕЛЬНЫЙ сервис, не часть основного бота.

Следит за каналами из events/sources.json и в реальном времени копирует их
посты (текст / фото / видео / альбомы, с сохранением форматирования и caption)
в личный чат владельца, добавляя ссылку на оригинал.

Токен ВТОРОГО бота (не основного!) берётся из переменной окружения
FORWARDER_BOT_TOKEN или из файла .env рядом с sources.json.
В коде и в git никаких секретов нет.

Команды:
    python events/forwarder.py setup    # определить id целевого чата (1 раз)
    python events/forwarder.py run      # запустить копирование (Ctrl+C — стоп)
    python events/forwarder.py run --reset   # начать с новых постов, без истории

Подробная инструкция — events/README.md.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "sources.json")
STATE_PATH = os.path.join(BASE_DIR, "forwarder_state.json")

API = "https://api.telegram.org/bot{token}/{method}"

# Пауза между альбомными частями обычно < 1 c; сколько ждём «хвост» группы
ALBUM_FLUSH_SECONDS = 2.0
# Таймаут long polling — небольшой, чтобы раз в пару секунд освобождать
# цикл и сбрасывать накопившиеся альбомы
POLL_TIMEOUT = 3


# ──────────────────────────── окружение и конфиг ────────────────────────────

def load_dotenv():
    """Читает .env рядом с sources.json (не обязателен). Секреты — только сюда."""
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(path):
        # .env может лежать в корне репозитория (как у основного бота)
        path = os.path.join(os.path.dirname(BASE_DIR), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("target_chat_id", 0)
    cfg.setdefault("channels", [])
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")


def get_token():
    token = os.getenv("FORWARDER_BOT_TOKEN", "").strip()
    if not token:
        print("❌ Не задан токен второго бота.")
        print("   Задай переменную окружения FORWARDER_BOT_TOKEN или файл events/.env")
        print("   со строкой  FORWARDER_BOT_TOKEN=123456789:AAA...")
        sys.exit(1)
    return token


def target_chat_id(cfg):
    raw = os.getenv("FORWARDER_TARGET_CHAT_ID", "").strip()
    if raw:
        return int(raw)
    return int(cfg.get("target_chat_id") or 0)


# ─────────────────────────────── Bot API ────────────────────────────────────

def api(token, method, retries=3, **params):
    """Вызов Telegram Bot API. При 429 ждёт retry_after и повторяет."""
    url = API.format(token=token, method=method)
    data = json.dumps(params).encode("utf-8")
    last_err = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=POLL_TIMEOUT + 30) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            if not out.get("ok"):
                raise RuntimeError(out.get("description", "unknown error"))
            return out["result"]
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                desc = json.loads(body).get("description", body)
            except Exception:
                desc = body
            if e.code == 429:
                try:
                    wait = float(json.loads(body).get("parameters", {}).get("retry_after", 3))
                except Exception:
                    wait = 3
                time.sleep(min(wait + 1, 30))
                last_err = RuntimeError(desc)
                continue
            raise RuntimeError(desc)
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise last_err


MEDIA_KEYS = (
    "photo", "video", "animation", "audio", "voice", "video_note",
    "document", "sticker", "dice", "poll", "location", "venue", "contact",
)


def is_text_only(post):
    return not post.get("media_group_id") and not any(post.get(k) for k in MEDIA_KEYS)


def post_link(chat, message_id):
    """Публичная ссылка на пост: t.me/name/123 или t.me/c/内部/123."""
    if chat.get("username"):
        return "https://t.me/{}/{}".format(chat["username"], message_id)
    cid = str(chat["id"])
    internal = cid[4:] if cid.startswith("-100") else cid.lstrip("-")
    return "https://t.me/c/{}/{}".format(internal, message_id)


def send_text(token, chat_id, text, entities=None):
    params = {
        "chat_id": chat_id,
        "text": text[:4096],
        "disable_web_page_preview": False,
    }
    if entities:
        params["entities"] = entities
    return api(token, "sendMessage", **params)


def send_link_reply(token, chat_id, reply_to, url):
    return api(
        token,
        "sendMessage",
        chat_id=chat_id,
        text="🔗 " + url,
        reply_parameters={"message_id": reply_to, "allow_sending_without_reply": True},
        disable_web_page_preview=True,
    )


def copy_single(token, target, chat, post):
    """Один пост (текстовый или медиа) → целевой чат + ссылка на оригинал."""
    link = post_link(chat, post["message_id"])
    if is_text_only(post):
        text = post.get("text") or ""
        tail = "\n\n🔗 " + link
        if len(text) + len(tail) <= 4096:
            send_text(token, target, text + tail, post.get("entities"))
        else:
            send_text(token, target, text, post.get("entities"))
            send_link_reply(token, target, post["message_id"], link)
        return
    # медиа (фото/видео/документ/кружок/голосовое…) — copy_message сохранит
    # фото/видео и caption один в один
    try:
        copied = api(
            token, "copyMessage",
            chat_id=target, from_chat_id=chat["id"], message_id=post["message_id"],
        )
        send_link_reply(token, target, copied["message_id"], link)
    except Exception as e:
        print("   ⚠️ copyMessage не сработал (%s), пробую forward…", e)
        try:
            fwd = api(
                token, "forwardMessage",
                chat_id=target, from_chat_id=chat["id"], message_id=post["message_id"],
            )
            send_link_reply(token, target, fwd["message_id"], link)
        except Exception as e2:
            print("   ⚠️ и forward не сработал (%s); шлю текстом." % e2)
            text = post.get("caption") or post.get("text") or "(медиа без описания)"
            send_text(token, target, text + "\n\n🔗 " + link,
                      post.get("caption_entities") or post.get("entities"))


def flush_album(token, target, group):
    """Альбом: копируем все части подряд, ссылку — одной строкой в конце."""
    msgs = sorted(group["msgs"], key=lambda m: m["message_id"])
    chat = group["chat"]
    link = post_link(chat, msgs[0]["message_id"])
    last_copied = None
    for post in msgs:
        try:
            copied = api(
                token, "copyMessage",
                chat_id=target, from_chat_id=chat["id"], message_id=post["message_id"],
            )
            last_copied = copied["message_id"]
        except Exception as e:
            print("   ⚠️ часть альбома не скопировалась: %s" % e)
    if last_copied:
        try:
            send_link_reply(token, target, last_copied, link)
        except Exception as e:
            print("   ⚠️ не отправилась ссылка на альбом: %s" % e)


# ─────────────────────────── источники и стейт ──────────────────────────────

def norm_source(s):
    """@name | t.me/name | https://t.me/name/123 | -100123… → имя или id."""
    s = str(s).strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "@"):
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix):]
    s = s.split("/")[0].split("?")[0].strip()
    return s


def resolve_sources(token, cfg):
    """Список источников → множество id чатов (и user-имена на случай смены id)."""
    ids, names = set(), set()
    for raw in cfg["channels"]:
        src = norm_source(raw)
        if not src:
            continue
        if src.lstrip("-").isdigit():
            ids.add(int(src))
            continue
        names.add(src.lower())
        try:
            info = api(token, "getChat", chat_id="@" + src)
            ids.add(info["id"])
        except Exception as e:
            print("⚠️ Не удалось получить id канала %s (%s)." % (src, e))
            print("   Бот должен быть админом канала. Пока сопоставляю по имени.")
    return ids, names


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_PATH)


def log(msg):
    print(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg, flush=True)


# ────────────────────────────────── setup ───────────────────────────────────

def cmd_setup(token):
    """Определяем id целевого чата: владелец пишет боту что угодно в личку."""
    me = api(token, "getMe")
    log("Бот: @%s (%s)" % (me["username"], me.get("first_name", "")))
    print()
    print("1) Открой в Telegram чат с ботом @%s" % me["username"])
    print("2) Нажми Start (или напиши любое сообщение).")
    print("   Жду сообщение… (Ctrl+C — выход)")
    print()
    while True:
        updates = api(
            token, "getUpdates", timeout=25, allowed_updates=["message"]
        )
        for upd in updates:
            msg = upd.get("message") or {}
            chat = msg.get("chat") or {}
            if chat.get("type") != "private":
                continue
            user = msg.get("from") or {}
            log("Сообщение от: id=%s  username=@%s  name=%s" % (
                chat["id"], user.get("username", "—"),
                " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x),
            ))
            if "--save" in sys.argv:
                cfg = load_config()
                cfg["target_chat_id"] = chat["id"]
                save_config(cfg)
                log("✓ Сохранил target_chat_id=%s в %s" % (chat["id"], CONFIG_PATH))
            else:
                log("Добавь этот id в events/sources.json → \"target_chat_id\",")
                log("или задай переменную окружения FORWARDER_TARGET_CHAT_ID=%s" % chat["id"])
            print()
            log("Дальше: python events/forwarder.py run")
            return


# ─────────────────────────────────── run ────────────────────────────────────

def cmd_run(token):
    cfg = load_config()
    target = target_chat_id(cfg)
    if not target:
        print("❌ Не задан целевой чат. Сначала запусти:  python events/forwarder.py setup --save")
        sys.exit(1)
    if not cfg["channels"]:
        print("❌ Пустой список каналов в %s. Добавь хотя бы один: \"channels\": [\"@имя_канала\"]" % CONFIG_PATH)
        sys.exit(1)

    src_ids, src_names = resolve_sources(token, cfg)
    me = api(token, "getMe")
    log("Форвардер запущен: @%s → личка %s" % (me["username"], target))
    log("Каналов в списке: %d" % len(cfg["channels"]))

    # проверка, что бот может писать в целевой чат
    try:
        api(token, "sendChatAction", chat_id=target, action="typing")
    except Exception:
        print("⚠️ Пока не могу писать в чат %s. Открой чат с ботом и нажми /start," % target)
        print("   потом перезапусти. (Пока просто продолжаю.)")

    state = load_state()
    if "--reset" in sys.argv:
        state.pop("offset", None)
    offset = state.get("offset")

    albums = {}  # (chat_id, media_group_id) -> {"chat":…, "msgs":[…], "ts":…}

    while True:
        try:
            updates = api(
                token, "getUpdates",
                offset=offset, timeout=POLL_TIMEOUT, limit=100,
                allowed_updates=["channel_post"],
            )
        except Exception as e:
            log("⚠️ Сеть/API: %s — повтор через 5 c" % e)
            time.sleep(5)
            continue

        for upd in updates:
            offset = upd["update_id"] + 1
            post = upd.get("channel_post")
            if not post:
                continue
            chat = post.get("chat") or {}
            if chat["id"] not in src_ids and (chat.get("username") or "").lower() not in src_names:
                continue  # канал не из списка — игнорируем

            title = chat.get("title") or ("@" + chat.get("username", "?"))
            gid = post.get("media_group_id")
            if gid:
                key = (chat["id"], gid)
                if key not in albums:
                    albums[key] = {"chat": chat, "msgs": [], "ts": time.time()}
                albums[key]["msgs"].append(post)
                albums[key]["ts"] = time.time()
                log("📚 Альбом %s/… из «%s» — коплю части" % (title, post.get("media_group_id", "")[:6]))
            else:
                log("📨 Пост %d из «%s» → копирую" % (post["message_id"], title))
                try:
                    copy_single(token, target, chat, post)
                except Exception as e:
                    log("⚠️ Не удалось скопировать пост: %s" % e)

        # сбрасываем альбомы, у которых части больше не приходят
        now = time.time()
        for key in [k for k, g in albums.items() if now - g["ts"] > ALBUM_FLUSH_SECONDS]:
            group = albums.pop(key)
            log("📚 Альбом из «%s» (%d шт.) → копирую целиком" % (
                group["chat"].get("title") or "@" + (group["chat"].get("username") or "?"),
                len(group["msgs"]),
            ))
            try:
                flush_album(token, target, group)
            except Exception as e:
                log("⚠️ Не удалось скопировать альбом: %s" % e)

        if offset is not None:
            state["offset"] = offset
            save_state(state)


# ─────────────────────────────────── main ───────────────────────────────────

def main():
    load_dotenv()
    token = get_token()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "setup":
        cmd_setup(token)
    elif cmd == "run":
        cmd_run(token)
    else:
        print("Использование: python events/forwarder.py [setup|run] [--save] [--reset]")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        log("Остановлено (Ctrl+C).")
