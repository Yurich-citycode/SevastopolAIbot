# -*- coding: utf-8 -*-
"""Тесты бота на реальных данных из "Sevastopol AI База.xlsx" — без сети и без Telegram.

Запуск:  .venv/bin/python tests/test_carousels.py
"""

import asyncio
import os
import sys
import tempfile

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

TEST_ADMIN_ID = "100500"
TEST_TOKEN = "123456789:TESTONLY-not-a-real-token"
os.environ["ADMIN_ID"] = TEST_ADMIN_ID
os.environ["TG_TOKEN"] = TEST_TOKEN

import sevastopolaibot as bot  # noqa: E402

_tmp_state = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
bot.STATE_FILE = _tmp_state.name
bot.PASSPORTS.clear()
bot.REFERRALS.clear()
bot.ANALYTICS_ROWS.clear()

XLSX = os.path.join(ROOT, "Sevastopol AI База.xlsx")

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {extra}")


# ── Мок-объекты под aiogram ──────────────────────────────────────────────

class FakeUser:
    def __init__(self, id=42, username="tester", full_name="Tester"):
        self.id = id
        self.username = username
        self.full_name = full_name


class FakeMessage:
    def __init__(self, photo=None, text=None, location=None):
        self.photo = photo
        self.text = text
        self.location = location
        self.from_user = FakeUser()
        self.sent = []
        self.deleted = 0

    async def delete(self):
        self.deleted += 1

    async def answer(self, text=None, reply_markup=None, parse_mode=None, **kw):
        self.sent.append(("answer", {"text": text, "markup": reply_markup}))

    async def answer_photo(self, photo=None, caption=None, reply_markup=None, parse_mode=None, **kw):
        self.sent.append(("answer_photo", {"photo": photo, "caption": caption, "markup": reply_markup}))

    async def edit_text(self, text=None, reply_markup=None, parse_mode=None, **kw):
        self.sent.append(("edit_text", {"text": text, "markup": reply_markup}))

    async def edit_media(self, media=None, reply_markup=None, **kw):
        self.sent.append(("edit_media", {"media": media, "markup": reply_markup}))

    async def copy_to(self, chat_id, **kw):
        self.sent.append(("copy_to", {"chat_id": chat_id}))

    def last_text(self):
        for kind, data in reversed(self.sent):
            if kind in ("answer", "answer_photo", "edit_text"):
                return data.get("text") or data.get("caption") or ""
        return ""

    def last_markup(self):
        for kind, data in reversed(self.sent):
            if kind in ("answer", "answer_photo", "edit_text", "edit_media"):
                return data.get("markup")
        return None


class FakeCall:
    def __init__(self, data, user=None):
        self.data = data
        self.from_user = user or FakeUser()
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False, **kw):
        self.answers.append((text, show_alert))


class FakeState:
    def __init__(self):
        self.data = {}
        self.state = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kw):
        self.data.update(kw)

    async def clear(self):
        self.data = {}
        self.state = None

    async def set_state(self, s):
        self.state = s


def kb_texts(markup):
    """Все подписи кнопок + callback_data/markup-ссылки из InlineKeyboardMarkup."""
    texts, callbacks, urls = [], [], []
    if markup is None:
        return texts, callbacks, urls
    for row in markup.inline_keyboard:
        for b in row:
            texts.append(b.text)
            if b.callback_data:
                callbacks.append(b.callback_data)
            if b.url:
                urls.append(b.url)
    return texts, callbacks, urls


# ── 1. Загружаем кэш из реального xlsx ───────────────────────────────────

def load_cache():
    xf = pd.ExcelFile(XLSX)
    for key in ("Где поесть", "Локации", "Маршруты", "События"):
        df = pd.read_excel(xf, sheet_name=key).fillna("")
        rows = bot.valid_rows(df.to_dict(orient="records"), require_date=(key == "События"))
        bot.TABLE_CACHE[key] = rows


print("== 1. База из xlsx ==")
load_cache()
food = bot.TABLE_CACHE["Где поесть"]
locs = bot.TABLE_CACHE["Локации"]
routes = bot.TABLE_CACHE["Маршруты"]
events = bot.TABLE_CACHE["События"]
check(f"«Где поесть»: данные есть ({len(food)} строк)", len(food) > 0)
check(f"«Локации»: данные есть ({len(locs)} строк)", len(locs) > 0)
check(f"«Маршруты»: данные есть ({len(routes)} строк)", len(routes) > 0)
check(f"«События»: данные есть ({len(events)} строк)", len(events) > 0)
check("в базе нет строк без названия", all(bot.pick(r, "Название") for r in food + locs + routes + events))
check(
    "в каждой категории еды есть заведения",
    all(bot.get_places_from_sheet(cat) for cat in bot.FOOD_CATEGORIES),
    str([cat for cat in bot.FOOD_CATEGORIES if not bot.get_places_from_sheet(cat)]),
)
check(
    "у каждой локации заполнены категория и описание",
    all(bot.pick(r, "Категория") and bot.pick(r, "Описание") for r in locs),
    str([bot.pick(r, "Название") for r in locs if not (bot.pick(r, "Категория") and bot.pick(r, "Описание"))]),
)
check(
    "у каждого маршрута заполнены длина и сложность",
    all(bot.pick(r, "Длина/Время") and bot.pick(r, "Сложность") for r in routes),
)


def route_buttons_mismatch():
    for i, route in enumerate(routes):
        key = bot.pick(route, "Категория") or "Пешие"
        _text, markup, _photo = bot.create_route_carousel(routes, i, key)
        texts, _callbacks, _urls = kb_texts(markup)
        has_map = bool(bot.clean_url(bot.pick(route, "Ссылка на карту")))
        has_coords = bool(bot.pick(route, "Координаты"))
        if has_map != any("Открыть карту маршрута" in t for t in texts):
            return f"{bot.pick(route, 'Название')}: кнопка карты"
        if has_coords != any("Съестное рядом" in t for t in texts):
            return f"{bot.pick(route, 'Название')}: кнопка «Съестное рядом»"
    return ""


check("кнопки маршрутов совпадают с данными", not route_buttons_mismatch(), route_buttons_mismatch())

# ── 2. Карусель еды: все 6 категорий ─────────────────────────────────────

print("== 2. Карусель еды (категории из таблицы) ==")
for cat_key, cat_name in bot.CAT_MAP.items():
    places = bot.get_places_from_sheet(cat_name)
    if not places:
        check(f"еда/{cat_name}: есть данные", False, "пусто")
        continue
    text, markup, photo = bot.create_carousel_card(places, 0, cat_key)
    texts, callbacks, urls = kb_texts(markup)
    name = bot.pick(places[0], "Название", default="Без названия")
    check(
        f"еда/{cat_name} ({len(places)} мест): карточка",
        f"<b>{name}</b>" in text and f"🔹 1 / {len(places)} 🔹" in texts,
    )
    check(
        f"еда/{cat_name}: кнопки 🎲 и навигация",
        any(t.startswith("🎲") for t in texts)
        and any(c.startswith(f"page_{cat_key}_") for c in callbacks),
    )

# ── 3. Карусель локаций: все категории из меню ───────────────────────────

print("== 3. Карусель локаций ==")
LOC_CATS = ["Пляжи", "Смотровые", "Закаты", "Hidden Gems", "Прогулки", "Достопримечательности", "Музеи"]
for cat in LOC_CATS:
    found = [r for r in locs if cat.lower() in str(r.get("Категория", "")).lower()]
    if not found:
        check(f"локации/{cat}: есть данные", False, "пусто")
        continue
    text, markup, photo = bot.create_location_carousel(found, 0, cat)
    texts, callbacks, urls = kb_texts(markup)
    name = bot.pick(found[0], "Название", default="Без названия")
    check(
        f"локации/{cat} ({len(found)}): карточка",
        f"<b>{name}</b>" in text and f"🔹 1 / {len(found)} 🔹" in texts,
    )
    check(f"локации/{cat}: кнопка 🎲", any(t.startswith("🎲") for t in texts))
    has_coords = any("," in bot.pick(r, "Координаты") for r in found)
    check(
        f"локации/{cat}: «Съестное рядом»",
        (any("Съестное рядом" in t for t in texts) == has_coords),
    )

# ── 4. Карусель маршрутов ────────────────────────────────────────────────

print("== 4. Карусель маршрутов ==")
RT_CATS = ["Пешие", "Велосипед", "Авто", "Вода"]
for cat in RT_CATS:
    found = [r for r in routes if cat.lower() in str(r.get("Категория", "")).lower()]
    if not found:
        check(f"маршруты/{cat}: есть данные", False, "пусто")
        continue
    text, markup, photo = bot.create_route_carousel(found, 0, cat)
    texts, callbacks, urls = kb_texts(markup)
    check(
        f"маршруты/{cat} ({len(found)}): карточка",
        f"🔹 1 / {len(found)} 🔹" in texts and any(t.startswith("🎲") for t in texts),
    )

# ── 5. Парсинг callback_data (в т.ч. с пробелами) ────────────────────────

print("== 5. Парсинг колбэков ==")
check(
    "loc_page_Hidden Gems_4",
    bot.parse_cat_index("loc_page_Hidden Gems_4") == ("Hidden Gems", 4),
)
check(
    "foodnear_loc_Пляжи_3",
    bot.parse_foodnear("foodnear_loc_Пляжи_3") == ("loc", "Пляжи", 3),
)
check(
    "rnd-категория с пробелами",
    "rnd_loc_Hidden Gems"[len("rnd_"):].startswith("loc_")
    and "rnd_loc_Hidden Gems".replace("rnd_loc_", "") == "Hidden Gems",
)

# ── 6. События — ОДНИМ сообщением ────────────────────────────────────────

print("== 6. События одним сообщением ==")


def upcoming():
    from datetime import datetime

    today = datetime.now().date()
    res = []
    for r in events:
        d = bot.parse_event_date(r.get("Дата"))
        if d and d >= today:
            res.append((d, r))
    res.sort(key=lambda x: x[0])
    return res[:10]


up = upcoming()
check("есть ближайшие события", len(up) > 0)
if up:
    text, markup = bot.build_events_message(up)
    texts, callbacks, urls = kb_texts(markup)
    check("один текст, а не серия сообщений", isinstance(text, str) and text.startswith("📅"))
    first_name = bot.pick(up[0][1], "Название", default="")
    check("первое событие внутри текста", first_name in text)
    check("длина ≤ 4096 (лимит Telegram)", len(text) <= 4096, f"было {len(text)}")
    check("кнопка «В главное меню» в конце", texts[-1] == "⬅️ В главное меню" and callbacks[-1] == "main_menu")
    buy_events = [
        (d, r) for d, r in up if bot.clean_url(bot.pick(r, "Купить"))
    ]
    ticket_btns = [t for t in texts if t.startswith("🎟")]
    check(
        f"кнопки билетов: {len(ticket_btns)} на {len(buy_events)} событий с «Купить»",
        len(ticket_btns) == len(buy_events),
    )

# ── 7. Живые колбэки (мок-объекты) ───────────────────────────────────────

print("== 7. Колбэки: 🎲, «Съестное рядом» + возврат, меню ==")


async def test_callbacks():
    # 7.1 🎲 в еде (свежий стейт → весь лист категории)
    st = FakeState()
    call = FakeCall("rnd_coffee")
    await bot._route_callback(call, st)
    t, c, u = kb_texts(call.message.last_markup())
    coffee_names = {bot.pick(r, "Название", default="") for r in bot.get_places_from_sheet("Кофе")}
    got = call.message.last_text()
    rand_ok = any(f"<b>{n}</b>" in got for n in coffee_names if n)
    check("rnd_coffee: случайное место из категории Кофе", rand_ok)
    check("rnd_coffee: на карточке есть кнопка 🎲", any(x.startswith("🎲") for x in t))

    # 7.2 🎲 в локации с пробелом в категории
    st = FakeState()
    call = FakeCall("rnd_loc_Hidden Gems")
    await bot._route_callback(call, st)
    gems = [r for r in locs if "hidden gems" in str(r.get("Категория", "")).lower()]
    gem_names = {bot.pick(r, "Название", default="") for r in gems}
    got = call.message.last_text()
    check("rnd_loc_Hidden Gems: случайная локация из Hidden Gems", any(f"<b>{n}</b>" in got for n in gem_names if n))

    # 7.3 «Съестное рядом» + возврат на ту же карточку
    st = FakeState()
    call = FakeCall("locselect_Пляжи")
    await bot._route_callback(call, st)
    beach_places = st.data.get("loc_places", [])
    idx = next(
        (i for i, r in enumerate(beach_places) if "," in bot.pick(r, "Координаты")),
        None,
    )
    check("пляж с координатами найден", idx is not None)
    if idx is not None:
        original_name = bot.pick(beach_places[idx], "Название", default="")
        call2 = FakeCall(f"foodnear_loc_Пляжи_{idx}")
        await bot._route_callback(call2, st)
        nearfood_text = call2.message.last_text()
        check("nearfood: карточка с расстоянием", "Расстояние до вас" in nearfood_text)
        check("nearfood: состояние запомнило исходную карточку",
              st.data.get("nearfood_category") == "Пляжи" and st.data.get("nearfood_index") == idx
              and st.data.get("nearfood_type") == "loc")
        check("nearfood: на карточке еды есть 🔙 Назад",
              any(c == "nearfood_back" for c in kb_texts(call2.message.last_markup())[1]))
        call3 = FakeCall("nearfood_back")
        await bot._route_callback(call3, st)
        back_text = call3.message.last_text()
        check("nearfood_back: вернулись на ТОТ ЖЕ пляж", f"<b>{original_name}</b>" in back_text)
        check("nearfood_back: номер страницы прежний",
              f"🔹 {idx + 1} / {len(beach_places)} 🔹" in kb_texts(call3.message.last_markup())[0])

    # 7.4 nearfood_back без состояния → меню (старое поведение)
    st2 = FakeState()
    call4 = FakeCall("nearfood_back")
    await bot._route_callback(call4, st2)
    check("nearfood_back (пустой стейт): фолбэк на меню локаций",
          any("Выбери интересующую категорию локаций" in (d.get("text") or d.get("caption") or "")
              for _, d in call4.message.sent))

    # 7.5 rnd_nearfood работает по filtered_places из стейта
    st3 = FakeState()
    st3.data.update(filtered_places=beach_places[:3], current_category="nearfood")
    call5 = FakeCall("rnd_nearfood")
    await bot._route_callback(call5, st3)
    beach_names = {bot.pick(r, "Название", default="") for r in beach_places[:3]}
    got = call5.message.last_text()
    check("rnd_nearfood: случайное из списка «рядом»", any(f"<b>{n}</b>" in got for n in beach_names if n))

    # 7.6 Главное меню: кнопки «Новости города» и «Предложить место»
    st4 = FakeState()
    call6 = FakeCall("main_menu")
    await bot._route_callback(call6, st4)
    t, c, u = kb_texts(call6.message.last_markup())
    check("меню: «📰 Новости города» со ссылкой на канал",
          "📰 Новости города" in t and bot.NEWS_CHANNEL_URL in u)
    check("меню: ссылка на канал = t.me/Sevastopol_AI",
          bot.NEWS_CHANNEL_URL == "https://t.me/Sevastopol_AI")
    check("меню: «✍️ Предложить место» — URL-кнопка на форму",
          "✍️ Предложить место" in t and bot.SUGGEST_FORM_URL in u)

    st5 = FakeState()
    call7 = FakeCall("suggest_place")
    await bot._route_callback(call7, st5)
    check("suggest_place: подсказка со ссылкой на форму",
          any("Форма предложений" in (d.get("text") or "") for _, d in call7.message.sent))
    t7, c7, u7 = kb_texts(call7.message.last_markup())
    check("suggest_place: инлайн-кнопка «Открыть форму»",
          bot.SUGGEST_FORM_URL in u7)

    msg = FakeMessage(text=bot.SUGGEST_WEB_PREFIX + " новое место\nТотальный, ул. Нахимова 2")
    msg.from_user = FakeUser(id=777, username="suga", full_name="Сюга")
    await bot.fallback_message(msg, st5)
    copied = [d for k, d in msg.sent if k == "copy_to"]
    check("веб-предложение переслано владельцу (ADMIN_ID)",
          len(copied) == 1 and copied[0]["chat_id"] == bot.ADMIN_ID)
    check("пользователю подтверждение", "Передала владельцу" in msg.last_text())
    check("за предложение дали +5 XP", bot.PASSPORTS[777]["xp"] >= 15)  # 10 (создание) + 5

    # 7.8 suggest_cancel (остаток старой клавиатуры): колбэк не роняет бот
    st6 = FakeState()
    st6.state = None
    call8 = FakeCall("suggest_cancel")
    await bot._route_callback(call8, st6)
    check("suggest_cancel: подсказка со ссылкой на форму",
          any(bot.SUGGEST_FORM_URL in (d.get("text") or "") for _, d in call8.message.sent))


asyncio.run(test_callbacks())

# ── 8. XP за активность ──────────────────────────────────────────────────

print("== 8. XP за активность ==")
user = FakeUser(id=12345, username="xpper", full_name="XP Per")
first = bot.award_activity_xp(user, "BTN_FOOD")
second = bot.award_activity_xp(user, "BTN_FOOD")
third = bot.award_activity_xp(user, "BTN_ROUTES")
check("первое действие дало +3", first == 3, f"было {first}")
check("повтор того же действия — 0 (раз в день)", second == 0, f"было {second}")
check("другое действие дало +3", third == 3, f"было {third}")
check("xp_today считает сумму за день", bot.xp_today(12345) == 6, f"было {bot.xp_today(12345)}")


async def test_passport_msg():
    msg = FakeMessage()
    msg.from_user = FakeUser(id=12345, username="xpper", full_name="XP Per")
    await bot.show_passport(msg)
    check("паспорт: строка «Сегодня за активность»", "Сегодня за активность: +6 XP" in msg.last_text())


asyncio.run(test_passport_msg())

# ── 9. Лимиты Telegram по всей базе ─────────────────────────────────────

print("== 9. Лимиты Telegram (текст 4096, подпись фото 1024, callback_data 64 байта) ==")


def all_callback_data(markup):
    for row in markup.inline_keyboard:
        for b in row:
            if b.callback_data:
                yield b.callback_data


bad_text, bad_caption, bad_cb = [], [], []
for row in food:
    text, markup, photo = bot.create_carousel_card([row], 0, "coffee")
    if len(text) > 4096:
        bad_text.append(bot.pick(row, "Название"))
    if photo and len(text) > 1024:
        bad_caption.append(bot.pick(row, "Название"))
    for cb in all_callback_data(markup):
        if len(cb.encode()) > 64:
            bad_cb.append(cb)

for row in locs:
    text, markup, photo = bot.create_location_carousel([row], 0, "Пляжи")
    if len(text) > 4096:
        bad_text.append(bot.pick(row, "Название"))
    if photo and len(text) > 1024:
        bad_caption.append(bot.pick(row, "Название"))
    for cb in all_callback_data(markup):
        if len(cb.encode()) > 64:
            bad_cb.append(cb)

for row in routes:
    text, markup, photo = bot.create_route_carousel([row], 0, "Пешие")
    if len(text) > 4096:
        bad_text.append(bot.pick(row, "Название"))
    if photo and len(text) > 1024:
        bad_caption.append(bot.pick(row, "Название"))
    for cb in all_callback_data(markup):
        if len(cb.encode()) > 64:
            bad_cb.append(cb)

check("текст карточек ≤ 4096 символов", not bad_text, str(bad_text[:3]))
check("подпись к фото ≤ 1024 символа", not bad_caption, str(bad_caption[:3]))
check("callback_data ≤ 64 байт", not bad_cb, str(bad_cb[:3]))

tg_photos = [bot.pick(r, "Ссылка на фото") for r in locs if "t.me" in bot.pick(r, "Ссылка на фото").lower()]
tg_used_as_photo = [
    r for r in tg_photos
    if bot.is_direct_image_url(bot.clean_url(r))
]
check(f"ссылки на посты t.me ({len(tg_photos)} шт.) не считаются фото", not tg_used_as_photo)

districts = sorted({str(p.get("Район", "")).strip() for p in food if str(p.get("Район", "")).strip()})
too_long = [d for d in districts if len(f"subdist_delivery_{d}".encode()) > 64]
check(f"районы ({len(districts)} шт.) влезают в callback_data", not too_long, str(too_long))

# ── 10. Загрузка состояния из «битого» bot_state.json ───────────────────

print("== 10. Устойчивость к битому состоянию ==")
with open(bot.STATE_FILE, "w", encoding="utf-8") as f:
    f.write(
        '{"passports": {"1": {"xp": "abc"}, "2": {"xp": 50, "name": "Ок"}},'
        ' "referrals": {"1": {"referrer": 2, "date": "2026-01-01", "bonus_given": false}},'
        ' "analytics": [{"action": "START", "user_id": 2}, "мусор", null]}'
    )
bot.PASSPORTS.clear()
bot.REFERRALS.clear()
bot.ANALYTICS_ROWS.clear()
bot.load_state()
check("паспорт без xp → 0", bot.PASSPORTS[1]["xp"] == 0)
check("паспорт с xp сохранился", bot.PASSPORTS[2]["xp"] == 50)
check("недостающие поля дополнены",
      bot.PASSPORTS[1]["name"] == "Гость" and bot.PASSPORTS[1]["passport_id"])
check("мусор в аналитике отброшен", len(bot.ANALYTICS_ROWS) == 1)

with open(bot.STATE_FILE, "w", encoding="utf-8") as f:
    f.write("{ это не json")
bot.PASSPORTS.clear()
bot.load_state()
check("битый json не роняет старт", bot.PASSPORTS == {})

bot.PASSPORTS[999] = {"name": "Тест", "username": "t", "xp": 10, "passport_id": "CC-000999"}
bot.save_state()
import json as _json
with open(bot.STATE_FILE, encoding="utf-8") as f:
    saved = _json.load(f)
check("save_state пишет валидный json", saved["passports"]["999"]["xp"] == 10)
check("save_state не оставляет временный файл", not os.path.exists(bot.STATE_FILE + ".tmp"))
bot.PASSPORTS.clear()
bot.load_state()
check("состояние переживает перезапуск", bot.PASSPORTS[999]["xp"] == 10)

# ── 10.5 Шапка с латинской «B» (так сейчас в живой Google-таблице) ───────

print("== 10.5 Латинская «B» в шапке таблицы ==")
latin_row = {
    "Категория": "Кофе",
    "Название": "Тест с латинской шапкой",
    "Адрес": "ул. Тестовая, 1",
    "Район": "Центр",
    "Координаты": "44.61, 33.52",
    "Bремя работы": "ежедневно 8:00–21:00",
    "Bконтакте": "https://vk.ru/test",
    "Сайт": "https://example.com",
}
t, mk, ph = bot.create_carousel_card([latin_row], 0, "coffee")
labels = kb_texts(mk)[0]
check("время работы читается из «Bремя работы»", "ежедневно 8:00–21:00" in t)
check("ВК читается из «Bконтакте»", any("ВКонтакте" in x for x in labels))
check("валидные строки с такой шапкой не отсеиваются",
      len(bot.valid_rows([latin_row])) == 1)

# ── 11. Совместимость с aiogram (kwargs, которые реально шлём) ───────────

print("== 11. Совместимость с aiogram ==")
import inspect

from aiogram.types import Message

AIAGRAM_CALLS = [
    ("answer", {"text", "reply_markup", "parse_mode"}),
    ("answer_photo", {"photo", "caption", "reply_markup", "parse_mode"}),
    ("edit_text", {"text", "reply_markup", "parse_mode"}),
    ("edit_media", {"media", "reply_markup"}),
    ("copy_to", {"chat_id"}),
    ("delete", set()),
]
for method, kwargs in AIAGRAM_CALLS:
    params = set(inspect.signature(getattr(Message, method)).parameters)
    missing = kwargs - params
    check(
        f"Message.{method}({', '.join(sorted(kwargs)) or '—'}) поддерживается",
        not missing,
        f"нет параметров: {sorted(missing)}",
    )

# ── 12. Конфигурация из ENV (python-dotenv, без хардкода секретов) ────────

print("== 12. Конфигурация из ENV ==")
import re as _re
import tempfile as _tempfile

check("TG_TOKEN берётся из ENV", bot.TG_TOKEN == TEST_TOKEN, f"было {bot.TG_TOKEN!r}")
check("ADMIN_ID взят из ENV", bot.ADMIN_ID == int(TEST_ADMIN_ID), f"было {bot.ADMIN_ID!r}")
check("ADMIN_ID из ENV: is_admin распознаёт владельца",
      bot.is_admin(int(TEST_ADMIN_ID)) and not bot.is_admin(int(TEST_ADMIN_ID) + 1))
check("REFRESH_SECONDS — целое из ENV/дефолта",
      isinstance(bot.REFRESH_SECONDS, int) and bot.REFRESH_SECONDS > 0)
check("STATE_FILE — строка", isinstance(bot.STATE_FILE, str) and bot.STATE_FILE)

os.environ["__AUDIT_BAD_INT__"] = "не число"
check("env_int: мусор → дефолт, без падения", bot.env_int("__AUDIT_BAD_INT__", 42) == 42)
os.environ["__AUDIT_EMPTY__"] = "   "
check("env_str: пустое значение → дефолт", bot.env_str("__AUDIT_EMPTY__", "fallback") == "fallback")
del os.environ["__AUDIT_BAD_INT__"], os.environ["__AUDIT_EMPTY__"]

with _tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as _f:
    _f.write("__AUDIT_FROM_FILE__=1\n__AUDIT_OVERRIDE__=from_file\n")
    _env_file = _f.name
os.environ["ENV_FILE"] = _env_file
os.environ["__AUDIT_OVERRIDE__"] = "from_env"
bot.load_env()
check("load_env читает файл из ENV_FILE", os.environ.get("__AUDIT_FROM_FILE__") == "1")
check("реальное окружение приоритетнее .env", os.environ["__AUDIT_OVERRIDE__"] == "from_env")
del os.environ["ENV_FILE"], os.environ["__AUDIT_FROM_FILE__"], os.environ["__AUDIT_OVERRIDE__"]
os.unlink(_env_file)

with open(os.path.join(ROOT, "sevastopolaibot.py"), encoding="utf-8") as f:
    _source = f.read()
check("в sevastopolaibot.py нет токена вида 123456789:AAA…",
      not _re.search(r"\d{8,10}:AA[0-9A-Za-z_-]{30}", _source))
check("в sevastopolaibot.py нет личного ADMIN_ID по умолчанию",
      "6106999216" not in _source)
check("python-dotenv подключён", "from dotenv import load_dotenv" in _source)

if os.name == "posix":
    os.chmod(bot.STATE_FILE, 0o644)
    bot.save_state()
    _mode = os.stat(bot.STATE_FILE).st_mode & 0o777
    check("bot_state.json сохраняется с правами 600", _mode == 0o600, f"было {oct(_mode)}")

# ── Итог ─────────────────────────────────────────────────────────────────
print(f"\nИТОГ: {PASS} прошло, {FAIL} упало")
sys.exit(1 if FAIL else 0)
