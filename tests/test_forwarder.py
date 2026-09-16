# -*- coding: utf-8 -*-
"""
Мини-тесты парсера каналов (events/forwarder.py) — БЕЗ сети и без подключения
к Telegram: проверяем чистые функции (нормализация ссылок, ссылки на посты,
группировка альбомов, обрезка entities, стейт) и логику копирования постов
на фейковом клиенте.

Запуск:  python tests/test_forwarder.py
Зависимости: только стандартная библиотека (telethon не нужен — объекты-заглушки).
"""

import asyncio
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "events"))

import forwarder as fw  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✅ %s" % name)
    else:
        FAIL += 1
        print("  ❌ %s %s" % (name, extra))


def eq(name, got, want):
    check(name, got == want, "→ получено %r, ожидалось %r" % (got, want))


# ─────────────────────────── заглушки вместо Telethon ───────────────────────

class Ent:
    """Аналог types.MessageEntityBold: нужны только offset/length/clone."""

    def __init__(self, offset, length):
        self.offset = offset
        self.length = length

    def clone(self):
        return Ent(self.offset, self.length)

    def __repr__(self):
        return "Ent(%d,%d)" % (self.offset, self.length)


class MessageMediaPhoto:  # имя класса важно: по нему определяется «это файл»
    pass


class MessageMediaWebPage:  # а это файлом отправить нельзя
    pass


class Msg:
    def __init__(self, id, text="", media=None, grouped_id=None,
                 entities=None, action=None):
        self.id = id
        self.message = text
        self.media = media
        self.grouped_id = grouped_id
        self.entities = entities
        self.action = action
        self.attributes = []
        self.peer_id = "peer"


class FakeClient:
    """Пишет все вызовы в self.calls; форвард можно «сломать»."""

    def __init__(self, forward_fails=False, feed=None):
        self.calls = []
        self.forward_fails = forward_fails
        self.feed = feed or []   # что вернёт get_messages (как Telethon: свежие первыми)

    async def forward_messages(self, target, messages, from_peer=None, **kw):
        if self.forward_fails:
            raise Exception("forwarding messages is disabled")
        self.calls.append(("forward", target, list(messages)))

    async def send_message(self, target, text, **kw):
        self.calls.append(("message", target, text, kw.get("formatting_entities")))

    async def send_file(self, target, file=None, **kw):
        self.calls.append(("file", target, kw.get("caption"),
                           kw.get("formatting_entities")))

    async def get_messages(self, entity, limit=None, **kw):
        return list(self.feed[:limit])


# ─────────────────────────── 1. нормализация ссылок ─────────────────────────

print("== 1. norm_source: ссылки на канал ==")
eq("https://t.me/name/123 → name", fw.norm_source("https://t.me/name/123"), "name")
eq("http://t.me/name → name", fw.norm_source("http://t.me/name"), "name")
eq("t.me/name/45 → name", fw.norm_source("t.me/name/45"), "name")
eq("@name → name", fw.norm_source("@name"), "name")
eq("name → name", fw.norm_source("name"), "name")
eq("пробелы и регистр домена", fw.norm_source("  HTTPS://T.ME/Name/7  "), "Name")
eq("предпросмотр t.me/s/name", fw.norm_source("https://t.me/s/name"), "name")
eq("telegram.me/name/7", fw.norm_source("https://telegram.me/name/7"), "name")
eq("telegram.dog/name", fw.norm_source("https://telegram.dog/name"), "name")
eq("приватный t.me/c/id/55", fw.norm_source("https://t.me/c/1234567890/55"),
   "-1001234567890")
eq("числовой id остаётся", fw.norm_source("-1001234567890"), "-1001234567890")
eq("query/якорь отбрасываются", fw.norm_source("https://t.me/name?comment=5#x"), "name")
eq("пустая строка", fw.norm_source(""), "")
eq("пригласительная ссылка t.me/+…", fw.norm_source("https://t.me/+AbCdEf"), "")
eq("None безопасно", fw.norm_source(None), "")
eq("мусор из слэшей", fw.norm_source("https://t.me///"), "")

print("== 2. post_link: ссылка на пост ==")
eq("публичный канал", fw.post_link("name", 42), "https://t.me/name/42")
eq("с @", fw.post_link("@name", 42), "https://t.me/name/42")
eq("приватный канал", fw.post_link("-1001234567890", 42),
   "https://t.me/c/1234567890/42")

# ─────────────────────── 3. группировка альбомов ────────────────────────────

print("== 3. group_new: альбомы одной группой ==")
msgs = [
    Msg(1, "одиночный"),
    Msg(2, "альбом 1", media=MessageMediaPhoto(), grouped_id=777),
    Msg(3, "альбом 2", media=MessageMediaPhoto(), grouped_id=777),
    Msg(4, "альбом 3", media=MessageMediaPhoto(), grouped_id=777),
    Msg(5, "снова одиночный"),
    Msg(6, "другой альбом", media=MessageMediaPhoto(), grouped_id=888),
]
groups = fw.group_new(msgs)
eq("групп получилось 4", len(groups), 4)
eq("порядок групп сохранён", [len(g) for g in groups], [1, 3, 1, 1])
eq("альбом 777 целиком", [m.id for m in groups[1]], [2, 3, 4])
eq("пустой список", fw.group_new([]), [])

# ────────────────────────── 4. обрезка entities ─────────────────────────────

print("== 4. clip_entities: смещения остаются валидными ==")
eq("None → None", fw.clip_entities(None, 10), None)
eq("пустой список → None", fw.clip_entities([], 10), None)
ents = [Ent(0, 5), Ent(8, 10), Ent(40, 3)]
got = fw.clip_entities(ents, 12)
eq("вышло 2 сущности", len(got), 2)
eq("первая не тронута", (got[0].offset, got[0].length), (0, 5))
eq("вторая обрезана по лимиту", (got[1].offset, got[1].length), (8, 4))
eq("та, что за лимитом, выброшена", len([e for e in got if e.offset >= 12]), 0)
check("исходный список не испорчен", ents[1].length == 10)

# ─────────────────────── 5. копирование: форвард-приоритет ──────────────────

print("== 5. copy_group: сначала форвард ==")
c = FakeClient(forward_fails=False)
asyncio.run(fw.copy_group(c, "me", "name", "entity", [Msg(11, "привет")], "Канал"))
eq("вызов один", len(c.calls), 1)
eq("это форвард", c.calls[0][0], "forward")
eq("id поста в форварде", c.calls[0][2], [11])

print("== 6. copy_group: запрет форвардов → ручная копия текста ==")
c = FakeClient(forward_fails=True)
ents = [Ent(0, 6)]
asyncio.run(fw.copy_group(c, "me", "name", "entity",
                          [Msg(12, "привет мир", entities=ents)], "Канал"))
eq("отправили текстом", c.calls[0][0], "message")
eq("текст + ссылка на оригинал", c.calls[0][2],
   "привет мир\n\n🔗 https://t.me/name/12")
eq("исходные entities переданы", c.calls[0][3], ents)

print("== 7. copy_group: медиа вручную — send_file со ссылкой в caption ==")
c = FakeClient(forward_fails=True)
asyncio.run(fw.copy_group(c, "me", "name", "entity",
                          [Msg(13, "подпись", media=MessageMediaPhoto())], "Канал"))
eq("вызван send_file", c.calls[0][0], "file")
eq("caption со ссылкой", c.calls[0][2], "подпись\n\n🔗 https://t.me/name/13")

print("== 8. copy_group: веб-превью — не файл, шлём текстом ==")
c = FakeClient(forward_fails=True)
asyncio.run(fw.copy_group(c, "me", "name", "entity",
                          [Msg(14, "ссылка", media=MessageMediaWebPage())], "Канал"))
eq("ушёл как текст", c.calls[0][0], "message")
check("ссылка на оригинал есть", c.calls[0][2].endswith("https://t.me/name/14"))

print("== 9. copy_group: альбом — ссылка одна, в конце ==")
c = FakeClient(forward_fails=True)
album = [
    Msg(20, "часть 1", media=MessageMediaPhoto(), grouped_id=555),
    Msg(21, "часть 2", media=MessageMediaPhoto(), grouped_id=555),
    Msg(22, "часть 3", media=MessageMediaPhoto(), grouped_id=555),
]
asyncio.run(fw.copy_group(c, "me", "name", "entity", album, "Канал"))
eq("три файла", len([x for x in c.calls if x[0] == "file"]), 3)
eq("без ссылки в первых двух", [x[2] for x in c.calls[:2]], ["часть 1", "часть 2"])
eq("ссылка только в последнем", c.calls[2][2], "часть 3\n\n🔗 https://t.me/name/20")

print("== 10. copy_group: альбом форвардится одним вызовом ==")
c = FakeClient(forward_fails=False)
asyncio.run(fw.copy_group(c, "me", "name", "entity", album, "Канал"))
eq("один форвард на весь альбом", len(c.calls), 1)
eq("все id в одном вызове", c.calls[0][2], [20, 21, 22])

# ────────────────────────────── 6. стейт и конфиг ───────────────────────────

print("== 11. стейт: атомарная запись и чтение ==")
tmpdir = tempfile.mkdtemp()
fw.STATE_PATH = os.path.join(tmpdir, "forwarder_state.json")
fw.save_state({"version": 2, "channels": {"name": 100}})
check("файл создан", os.path.exists(fw.STATE_PATH))
check("временный файл убран", not os.path.exists(fw.STATE_PATH + ".tmp"))
eq("прочитали то же", fw.load_state()["channels"]["name"], 100)
with open(fw.STATE_PATH, encoding="utf-8") as f:
    check("в стейте есть метка времени", "updated" in json.load(f))
with open(fw.STATE_PATH, "w", encoding="utf-8") as f:
    f.write("{ битый json")
eq("битый стейт → пустой", fw.load_state(), {"version": 2, "channels": {}})

print("== 12. конфиг: значения по умолчанию и нормализация каналов ==")
cfg_path = os.path.join(tmpdir, "sources.json")
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump({"target": "me",
               "channels": ["https://t.me/one/12", "@two", "t.me/three"],
               "poll_seconds": 12, "include_history": False}, f)
fw.CONFIG_PATH = cfg_path
cfg = fw.load_config()
eq("каналы нормализованы", cfg["channels"], ["one", "two", "three"])
eq("target по умолчанию", cfg["target"], "me")
eq("poll_seconds", cfg["poll_seconds"], 12)
eq("include_history", cfg["include_history"], False)
os.environ["FORWARDER_TARGET"] = "@saved_chat"
eq("FORWARDER_TARGET переопределяет sources.json", fw.load_config()["target"],
   "@saved_chat")
os.environ.pop("FORWARDER_TARGET", None)

with open(cfg_path, "w", encoding="utf-8") as f:
    f.write("{}")
cfg = fw.load_config()
eq("пустой конфиг → target me", cfg["target"], "me")
eq("пустой конфиг → poll 12", cfg["poll_seconds"], 12)
eq("пустой конфиг → каналов нет", cfg["channels"], [])

print("== 13. poll_channel: первый запуск — историю не льём ==")
fw.STATE_PATH = os.path.join(tmpdir, "forwarder_state.json")
if os.path.exists(fw.STATE_PATH):
    os.remove(fw.STATE_PATH)
feed = [Msg(30, "c"), Msg(29, "b"), Msg(28, "a")]      # как Telethon: свежие первыми
client = FakeClient(feed=feed)
state = fw.load_state()
src = {"key": "name", "entity": "entity", "title": "Канал"}
cfg = {"target": "me", "channels": ["name"], "poll_seconds": 12, "include_history": False}
copied = asyncio.run(fw.poll_channel(client, cfg, "me", src, state))
eq("ничего не скопировали", copied, 0)
eq("вызовов отправки не было", len(client.calls), 0)
eq("точка отсчёта = последний пост", state["channels"]["name"], 30)
eq("стейт записан на диск", fw.load_state()["channels"]["name"], 30)

print("== 14. poll_channel: копируются только новые посты ==")
client.feed = [Msg(32, "новый 2"), Msg(31, "новый 1")] + feed
copied = asyncio.run(fw.poll_channel(client, cfg, "me", src, state))
eq("скопировали 2 поста", copied, 2)
eq("оба — форвардом", [c[0] for c in client.calls], ["forward", "forward"])
eq("id в порядке возрастания", sorted(c[2][0] for c in client.calls), [31, 32])
eq("прогресс обновлён", state["channels"]["name"], 32)

print("== 15. poll_channel: повторный опрос — без дубликатов ==")
client.calls.clear()
copied = asyncio.run(fw.poll_channel(client, cfg, "me", src, state))
eq("новых нет", copied, 0)
eq("ничего не отправили", len(client.calls), 0)

print("== 16. poll_channel: служебные сообщения пропускаем ==")
client.calls.clear()
client.feed = [Msg(35, "пост"), Msg(34, "", action="ChatJoinByRequest"), Msg(33, "ещё")]
copied = asyncio.run(fw.poll_channel(client, cfg, "me", src, state))
eq("скопировали 2 из 3", copied, 2)
eq("служебное не отправляли", sorted(c[2][0] for c in client.calls), [33, 35])
eq("прогресс всё равно на 35", state["channels"]["name"], 35)

print("== 17. poll_channel: альбом одним форвардом ==")
client.calls.clear()
client.feed = [
    Msg(41, "часть 2", media=MessageMediaPhoto(), grouped_id=999),
    Msg(40, "часть 1", media=MessageMediaPhoto(), grouped_id=999),
    Msg(39, "обычный пост"),
]
copied = asyncio.run(fw.poll_channel(client, cfg, "me", src, state))
eq("новых 3", copied, 3)
eq("два вызова: пост + альбом", len(client.calls), 2)
eq("сначала одиночный", client.calls[0][2], [39])
eq("альбом целиком", client.calls[1][2], [40, 41])

print("== 18. poll_channel: include_history — копируем последние посты ==")
fw.STATE_PATH = os.path.join(tmpdir, "state_history.json")
client = FakeClient(feed=[Msg(52, "x"), Msg(51, "y"), Msg(50, "z")])
state = fw.load_state()
cfg_h = dict(cfg, include_history=True)
copied = asyncio.run(fw.poll_channel(client, cfg_h, "me", src, state))
eq("скопировали весь хвост", copied, 3)
eq("прогресс на последнем", state["channels"]["name"], 52)

print("== 19. перезапуск: стейт с диска, дубликатов нет ==")
client.calls.clear()
state2 = fw.load_state()
eq("прочитали прогресс", state2["channels"]["name"], 52)
copied = asyncio.run(fw.poll_channel(client, cfg_h, "me", src, state2))
eq("после перезапуска тишина", copied, 0)
eq("ничего не отправили", len(client.calls), 0)

print("== 20. poll_round: обход всех каналов, битый канал не роняет цикл ==")
fw.STATE_PATH = os.path.join(tmpdir, "state_round.json")


class BrokenClient(FakeClient):
    async def get_messages(self, entity, limit=None, **kw):
        if entity == "broken":
            raise Exception("channel not accessible")
        return await FakeClient.get_messages(self, entity, limit=limit, **kw)


client = BrokenClient(feed=[Msg(61, "пост")])
state = fw.load_state()
sources = [
    {"key": "name", "entity": "entity", "title": "Канал"},
    {"key": "broken", "entity": "broken", "title": "Битый"},
]
total = asyncio.run(fw.poll_round(client, cfg, "me", sources, state))
eq("первый проход — только точки отсчёта", total, 0)
eq("битый канал не записан в стейт", sorted(state["channels"]), ["name"])
eq("рабочий канал учтён", state["channels"]["name"], 61)

print()
print("ИТОГ: %d прошло, %d упало" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
