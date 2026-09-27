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

# ── 13. Экономика City Passport: ранги, грант, verified XP ──────────────

print("== 13. Экономика City Passport ==")
from datetime import datetime, timedelta  # noqa: E402

bot.PASSPORTS.clear()
bot.REFERRALS.clear()
bot.ANALYTICS_ROWS.clear()

# 13.1 calculate_level по порогам рангов (не √-формула)
check("calculate_level(99) = 0", bot.calculate_level(99) == 0, f"было {bot.calculate_level(99)}")
check("calculate_level(100) = 1", bot.calculate_level(100) == 1, f"было {bot.calculate_level(100)}")
check("calculate_level(800) = 3", bot.calculate_level(800) == 3, f"было {bot.calculate_level(800)}")
check("calculate_level(7000) = 6", bot.calculate_level(7000) == 6, f"было {bot.calculate_level(7000)}")
check("get_rank и level согласованы на порогах",
      bot.get_rank(99) == "Гость города" and bot.get_rank(100) == "Житель"
      and bot.get_rank(799) == "Исследователь" and bot.get_rank(800) == "Проводник"
      and bot.get_rank(3999) == "Амбассадор" and bot.get_rank(6999) == "Легенда города"
      and bot.get_rank(7000) == "City Code")

# 13.2 переход 6999 → 7000+: грант открыт, но членство молча не включено
grant_user = FakeUser(id=700001, username="grantee", full_name="Грант Тест")
bot.award_activity_xp(grant_user, "BTN_FOOD")  # создаёт паспорт
gp = bot.PASSPORTS[700001]
gp["xp"] = 6999
gp["complimentary_granted"] = False
gp["complimentary_claimed"] = False
gained = bot.award_activity_xp(grant_user, "BTN_LOCATIONS")  # +3 → пересекли 7000
check("начисление пересекло 7000", gained == 3 and gp["xp"] >= 7000)
check("complimentary_granted = True", gp["complimentary_granted"] is True)
check("complimentary_claimed = False (не молча)", gp["complimentary_claimed"] is False)
check("статус ещё GUEST", gp["status"] == "GUEST")
check("granted_at проставлен", bool(gp["complimentary_granted_at"]))

# 13.3 claim включает MEMBER на 180 дней ±1
ok, msg_text = bot.claim_citycode_grant(grant_user)
until = datetime.fromisoformat(gp["member_until"])
expected = datetime.now() + timedelta(days=180)
check("claim прошёл", ok, msg_text)
check("статус MEMBER, source=xp_grant", gp["status"] == "MEMBER" and gp["member_source"] == "xp_grant")
check("member_until = +180 дней ±1", abs((until - expected).days) <= 1, f"было {gp['member_until']}")
check("is_member_active = True", bot.is_member_active(700001))

# 13.4 повторный claim — отказ
ok2, msg2 = bot.claim_citycode_grant(grant_user)
check("повторный claim — отказ", not ok2 and "уже" in msg2)
gp["xp"] = 500
gp["xp"] = 8000
check("грант не выдаётся повторно после падения/роста XP",
      not bot.maybe_unlock_citycode_grant(700001))

# 13.5 уже MEMBER по оплате: claim добавляет 180 дней, оплату не сбрасывает
paid_user = FakeUser(id=700002, username="payer", full_name="Оплативший")
bot.create_passport_if_not_exists(paid_user)
pp = bot.PASSPORTS[700002]
paid_until = datetime.now() + timedelta(days=30)
pp.update(status="MEMBER", member_source="paid", member_until=paid_until.isoformat(),
          complimentary_granted=True, complimentary_claimed=False)
ok3, _ = bot.claim_citycode_grant(paid_user)
new_until = datetime.fromisoformat(pp["member_until"])
check("claim у оплаченного MEMBER прошёл", ok3)
check("срок удлинился ровно на 180 дней", abs((new_until - paid_until).days - 180) <= 1,
      f"было {pp['member_until']}")
check("source стал mixed (оплата не потеряна)", pp["member_source"] == "mixed")

# 13.6 членство ≠ ранг: оплата не требует 7000 XP, ранг не продаётся
low_user = FakeUser(id=700003, username="lowxp", full_name="Житель Оплатил")
bot.create_passport_if_not_exists(low_user)
bot.PASSPORTS[700003]["xp"] = 150
bot.set_member(700003, 30, "paid")
check("Житель может быть MEMBER (оплата)", bot.PASSPORTS[700003]["status"] == "MEMBER")
check("ранг при этом остался Житель", bot.get_rank(bot.PASSPORTS[700003]["xp"]) == "Житель")

# 13.7 expire_memberships: срок вышел → GUEST, ранг не трогаем
bot.PASSPORTS[700003]["member_until"] = (datetime.now() - timedelta(days=1)).isoformat()
bot.expire_memberships()
check("истёкший MEMBER вернулся в GUEST", bot.PASSPORTS[700003]["status"] == "GUEST")
check("XP после истечения не изменился", bot.PASSPORTS[700003]["xp"] == 150)

# 13.8 реферал-бонус +40 НЕ даётся, если активность только меню
referrer = FakeUser(id=700010, username="refer", full_name="Реферер")
bot.create_passport_if_not_exists(referrer)
ref_xp_before = bot.PASSPORTS[700010]["xp"]
lazy_id = 700011
ref_date = datetime.now() - timedelta(days=8)
bot.REFERRALS[lazy_id] = {"referrer": 700010, "date": ref_date.isoformat(), "bonus_given": False}
for day in range(3):  # три дня, но только кнопка меню
    ts = (ref_date + timedelta(days=day, hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    bot.ANALYTICS_ROWS.append({"date": ts, "user_id": lazy_id, "username": "", "action": "BTN_MAIN_MENU"})
asyncio.run(bot.check_referral_bonuses())
check("бонус не выдан за одно лишь меню",
      bot.PASSPORTS[700010]["xp"] == ref_xp_before and not bot.REFERRALS[lazy_id]["bonus_given"])

# два дня реальной активности — всё ещё мало (нужно 3 разных дня)
few_id = 700012
bot.REFERRALS[few_id] = {"referrer": 700010, "date": ref_date.isoformat(), "bonus_given": False}
for day in range(2):
    ts = (ref_date + timedelta(days=day, hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    bot.ANALYTICS_ROWS.append({"date": ts, "user_id": few_id, "username": "", "action": "BTN_FOOD"})
asyncio.run(bot.check_referral_bonuses())
check("бонус не выдан за активность в 2 дня", not bot.REFERRALS[few_id]["bonus_given"])

# живой реферал: 3 разных дня, не только меню → +40
alive_id = 700013
bot.REFERRALS[alive_id] = {"referrer": 700010, "date": ref_date.isoformat(), "bonus_given": False}
for day in range(3):
    ts = (ref_date + timedelta(days=day, hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    bot.ANALYTICS_ROWS.append({"date": ts, "user_id": alive_id, "username": "", "action": "BTN_ROUTES"})
asyncio.run(bot.check_referral_bonuses())
check("живой реферал: бонус +40 выдан",
      bot.REFERRALS[alive_id]["bonus_given"]
      and bot.PASSPORTS[700010]["xp"] == ref_xp_before + bot.REFERRAL_BONUS_XP)

# 13.9 migrate старого паспорта {"xp": 10} не падает и дополняет схему
old = bot.migrate_passport({"xp": 10})
check("migrate {'xp':10}: xp остался 10", old["xp"] == 10)
check("migrate: статус GUEST и поля гранта на месте",
      old["status"] == "GUEST" and old["complimentary_granted"] is False
      and old["member_until"] is None and old["xp_log"] == [] and old["xp_revoked"] == [])
with open(bot.STATE_FILE, "w", encoding="utf-8") as f:
    f.write('{"passports": {"31337": {"xp": 10}}, "referrals": {}, "analytics": []}')
bot.PASSPORTS.clear()
bot.load_state()
check("load_state дописывает дефолты старому паспорту",
      bot.PASSPORTS[31337]["xp"] == 10 and bot.PASSPORTS[31337]["status"] == "GUEST"
      and bot.PASSPORTS[31337]["partner_nodes"] == [])

# 13.10 verified XP: свои лимиты, вне дневного лимита кнопок
vu = FakeUser(id=700020, username="ver", full_name="Верифицированный")
bot.create_passport_if_not_exists(vu)
vp = bot.PASSPORTS[700020]
base_xp = vp["xp"]
check("PLACE_ACCEPTED = +40 и счётчик мест", bot.award_verified_xp(vu, "PLACE_ACCEPTED", actor="admin") == 40
      and vp["accepted_places"] == 1)
check("ROUTE_ACCEPTED = +70", bot.award_verified_xp(vu, "ROUTE_ACCEPTED", actor="admin") == 70)
r1 = bot.award_verified_xp(vu, "REVIEW_ACCEPTED", actor="admin")
r2 = bot.award_verified_xp(vu, "REVIEW_ACCEPTED", actor="admin")
r3 = bot.award_verified_xp(vu, "REVIEW_ACCEPTED", actor="admin")
check("REVIEW_ACCEPTED: max 2/день", (r1, r2, r3) == (10, 10, 0))
check("CLUB_APPLY: только 1 раз",
      bot.award_verified_xp(vu, "CLUB_APPLY") == 20 and bot.award_verified_xp(vu, "CLUB_APPLY") == 0
      and bool(vp["club_applied_at"]))
c1 = bot.award_verified_xp(vu, "EVENT_CHECKIN", actor="admin", meta={"event_id": "EV1"})
c2 = bot.award_verified_xp(vu, "EVENT_CHECKIN", actor="admin", meta={"event_id": "EV1"})
check("EVENT_CHECKIN: 1/событие", (c1, c2) == (60, 0) and len(vp["checkins"]) == 1)
n1 = bot.award_verified_xp(vu, "PARTNER_NODE_CONNECTED", actor="admin", meta={"node_id": "N1"})
n2 = bot.award_verified_xp(vu, "PARTNER_NODE_CONNECTED", actor="admin", meta={"node_id": "N1"})
n3 = bot.award_verified_xp(vu, "PARTNER_NODE_30D", actor="admin", meta={"node_id": "N1"})
check("узел: 1 раз на точку, 30d сразу не дают", (n1, n2, n3) == (200, 0, 0))
check("ЦФА без actor=admin — 0", bot.award_verified_xp(vu, "CFA_ISSUED") == 0)
check("ЦФА от админа начисляется", bot.award_verified_xp(vu, "CFA_CALL", actor="admin") == 30)
check("verified XP не пишется в дневной лимит кнопок", bot.xp_today(700020) == 0)
check("xp_log ведётся и не пуст", len(vp["xp_log"]) > 0)
expected_xp = base_xp + 40 + 70 + 10 + 10 + 20 + 60 + 200 + 30
check("итоговый XP сходится", vp["xp"] == expected_xp, f"было {vp['xp']}, ждали {expected_xp}")

# 13.11 revoke_xp: снятие с записью причины
bot.revoke_xp(700020, 100, "фарм саджестов")
check("revoke_xp снял 100", vp["xp"] == expected_xp - 100)
check("запись в xp_revoked", vp["xp_revoked"][-1]["reason"] == "фарм саджестов"
      and vp["xp_revoked"][-1]["amount"] == 100)

# 13.12 темп года: авто-кнопки не раздуты, потолок дня < 40
auto_max = sum(v for v in bot.XP_ACTIVITY_REWARDS.values())
check("авто-потолок дня с саджестом = 22 (< 40)", auto_max == 22, f"было {auto_max}")
no_suggest = auto_max - bot.XP_ACTIVITY_REWARDS["SUGGEST_PLACE"]
year_clicks = no_suggest * 365 + 10
check("чистые клики за год не добивают 7000 (≈8–12 мес с UGC)",
      6000 <= year_clicks < 7000, f"было {year_clicks}")

# 13.13 UI паспорта: ранг из сетки, статус, кнопка гранта, реф-ссылка
ui_user = FakeUser(id=700030, username="uier", full_name="Интерфейс")
bot.create_passport_if_not_exists(ui_user)
up = bot.PASSPORTS[700030]
up["xp"] = 6999
up["complimentary_granted"] = True
up["complimentary_claimed"] = False
text, markup = bot.build_passport_view(700030)
btns = kb_texts(markup)[0] if markup else []
check("паспорт: ранг по сетке (Легенда города на 6999)", "Легенда города" in text)
check("паспорт: level выровнен с рангом (5)", "Level: 5" in text)
check("паспорт: статус показан", "Статус: GUEST" in text)
check("паспорт: кнопка активации 6 месяцев", any("Активировать 6 месяцев City Code" in b for b in btns))
check("паспорт: текст награды гранта", "Это ключ за работу с городом" in text)
check("паспорт: реф-ссылка с Жителя", bot.get_ref_link(700030) in text)
up["xp"] = 50
text2, markup2 = bot.build_passport_view(700030)
check("до 100 XP реф-ссылки нет", bot.get_ref_link(700030) not in text2)


# ── Итог ─────────────────────────────────────────────────────────────────
print(f"\nИТОГ: {PASS} прошло, {FAIL} упало")
sys.exit(1 if FAIL else 0)
