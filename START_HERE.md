# START_HERE — что делать с нуля

Инструкция для того, кто не программист. Всё, что нужно, — браузер и два «ключа»: **токен бота** и **твой Telegram ID**. Ниже — где их взять, три способа запустить бота и что делать, если что-то не работает.

---

## 1. Два значения, без которых не запустится

### TG_TOKEN — «паспорт» бота

1. Открой в Telegram **[@BotFather](https://t.me/BotFather)**.
2. Отправь `/mybots` → выбери своего бота (SevastopolAiBot).
3. Нажми **API Token** → скопируй строку вида `123456789:AAH…` целиком.
4. Если бота ещё нет: `/newbot` → имя → username (должен заканчиваться на `bot`).

Это секрет. Кто знает токен — тот управляет ботом. Никому не пересылай, в код и в git не вставляй.

### ADMIN_ID — это ты

1. Открой **[@userinfobot](https://t.me/userinfobot)** и нажми Start.
2. Бот ответит числом вида `6106999216` — это твой ID.
3. По нему бот пускает в `/admin` и пересылает тебе заявки с формы «Предложить место».

---

## 2. Три способа запустить

### Способ А — Google Colab (быстрее всего, но не 24/7)

1. Открой `notebooks/SevastopolAI_bot.ipynb` в этом репозитории → кнопка **Open in Colab**.
2. В Colab слева нажми 🔑 **Secrets** и добавь два секрета: `TG_TOKEN` и `ADMIN_ID` (или просто впиши их в поле в ячейке — она спросит токен скрытно).
3. Нажми ▶️ у единственной ячейки — в логах появится «Бот запущен».
4. Остановить — кнопка ■. Colab засыпает без активности, поэтому для работы круглосуточно нужен сервер (способ В).

### Способ Б — свой компьютер

Нужен Python 3.10 или новее (python.org, при установке на Windows отметь «Add Python to PATH»).

```bash
# 1. Скачай репозиторий: зелёная кнопка Code → Download ZIP → распакуй
# 2. Открой терминал в папке проекта (Windows: PowerShell, правый клик → «Открыть в терминале»)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python tools/setup_env.py          # спросит токен и ADMIN_ID, создаст .env, проверит токен
python sevastopolaibot.py          # запуск: пока окно открыто — бот работает
```

`tools/setup_env.py` — мастер настройки: токен вводится скрытно (на экране не появляется), `.env` создаётся с правами 600, а в конце мастер проверяет токен у Telegram и пишет `✅ Токен рабочий: @твой_бот`.

### Способ В — VPS с systemd (работает 24/7)

Нужен любой сервер с Ubuntu или Debian (например, Timeweb, Aeza, Hetzner) и доступ по SSH.

```bash
sudo apt update && sudo apt install -y python3-venv git
git clone https://github.com/Yurich-citycode/SevastopolAIbot.git /opt/sevastopol-ai-bot
cd /opt/sevastopol-ai-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tools/setup_env.py          # создаст /opt/sevastopol-ai-bot/.env

sudo install -m 600 /dev/null /etc/sevastopol-ai-bot.env
sudo nano /etc/sevastopol-ai-bot.env         # впиши две строки:
#   TG_TOKEN=...
#   ADMIN_ID=...
```

Затем служба `sudo nano /etc/systemd/system/sevastopol-ai-bot.service`:

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

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sevastopol-ai-bot
journalctl -u sevastopol-ai-bot -f      # логи в реальном времени, выход — Ctrl+C
```

---

## 3. Чек-лист: бот работает?

- [ ] `/start` — приходит главное меню, в первый раз создаётся паспорт и начисляются XP.
- [ ] 🍽 **Еда** → категория «Кофе» → карточка с адресом, фото и кнопками навигации.
- [ ] 📍 **Локации** → карточка → «🗺 Открыть карту» открывает Яндекс.Карты.
- [ ] 🗺 **Маршруты** → карточка → «🗺 Открыть карту маршрута» открывает маршрут, снизу «🍔 Съестное рядом».
- [ ] 📅 **События** — все ближайшие события одним сообщением, с датами и кнопками билетов.
- [ ] 🎲 **Случайное место** — присылает случайное заведение / локацию / маршрут.
- [ ] ✍️ **Предложить место** — форма открывается, заявка приходит тебе в личку от бота.
- [ ] `/admin` — статистика (только для твоего ADMIN_ID).

---

## 4. Что в логах → что делать

| Что видно | Что это значит | Что сделать |
|---|---|---|
| `TG_TOKEN не задан` (код 2) | в `.env` нет токена | `python tools/setup_env.py` |
| `Unauthorized` / `401` | токен неверный или отозван | @BotFather → `/mybots` → API Token → скопируй заново |
| `Promise resolution is still pending` / конфликт | запущено два бота одновременно | останови второй запуск (Colab + компьютер) |
| `Google вернул не XLSX` | таблица закрыта для чтения | Google-таблица → Доступ → «Все, у кого есть ссылка» → Читатель |
| `ADMIN_ID не задан` | пусто в `.env` | @userinfobot → ID → впиши в `.env` |
| `Cannot connect to host` | нет интернета / сервер его потерял | проверь сеть, потом перезапусти бота |
| События не показываются | все события в таблице уже прошли | добавь свежие (лист «События», блоки — в `FILL_PACK.md`) |
| Карточка без картинки | в «Ссылка на фото» пусто или ссылка на пост `t.me/...` | вставь прямой адрес картинки (`.jpg`/`.png`) |
| Бот молчит, логов нет | процесс не запущен | `sudo systemctl restart sevastopol-ai-bot` |

---

## 5. Форма «Предложить место»: Cloudflare Worker через браузер

Заявка с формы `suggest.html` (она же на GitHub Pages) уходит в Cloudflare Worker, а он пересылает её тебе в личку.

1. Зарегистрируйся на **dash.cloudflare.com** (бесплатно) и войди.
2. Слева **Workers & Pages** → **Create** → **Create Worker** → впиши имя, например `sevastopol-suggest` → **Deploy**.
3. Открой **Edit code** → удали заготовку → вставь содержимое файла `worker/index.js` из этого репозитория → **Deploy**.
4. **Settings → Variables and Secrets** → добавь два секрета (оба типа **Secret**):
   - `BOT_TOKEN` — тот же токен от @BotFather;
   - `ADMIN_ID` — твой ID из @userinfobot.
5. Скопируй адрес воркера (вида `https://sevastopol-suggest.имя.workers.dev`).
6. Открой в репозитории `suggest.html`, найди строку `WORKER_URL` и вставь адрес воркера, затем **Commit changes**.
7. Проверь: открой форму на GitHub Pages и отправь тестовую заявку — она должна прийти в личку.

Если воркер ещё не настроен, форма не сломается: она предложит скопировать текст заявки и вставить его прямо в бота — бот распознаёт префикс `✍️ ПРЕДЛОЖЕНИЕ:` и пересылает владельцу.

---

## 6. Пять правил безопасности

1. **Токен — только в секретах.** Никогда не вписывай его в код, в ячейку Colab, в переписку или на скриншот. Только `.env` с правами 600, `EnvironmentFile` systemd или секрет Cloudflare Worker.
2. **Засветился — сразу отзывай.** @BotFather → `/mybots` → API Token → **Revoke** — старый токен перестаёт работать, создаётся новый.
3. **`ADMIN_ID` — тоже личные данные.** Это твой аккаунт: по нему бот отдаёт статистику и присылает заявки. В коде его нет — только из окружения.
4. **Служебные файлы — только тебе.** `.env` и `bot_state.json` (паспорта, XP, статистика) держи с правами 600; бот уже сохраняет `bot_state.json` с правом «только владелец».
5. **Не коммить секреты.** `.env` и `bot_state.json` в `.gitignore` — не убирай их оттуда и не заливай в репозиторий. Если секрет случайно попал в git — считай его утёкшим: отзови и создай новый.

---

## 7. Что ещё полезно знать

- **База данных живёт в Google-таблице.** Бот читает её каждые `REFRESH_SECONDS` (по умолчанию 600 секунд) — перезапуск после правок не нужен. Проверить данные и вставить обновления: `FILL_PACK.md`.
- **События стареют.** Раз в пару недель заходи в лист «События» и обновляй даты; прошедшие события складывай в `Sevastopol AI Архив событий.xlsx`.
- **Проверка перед изменениями:** `python tests/test_carousels.py` (бот) и `python tools/check_base.py` (данные).
- **Секреты и ротация:** подробнее — в `SECURITY.md`. Подробности про запуск и архитектуру — в `README.md`.
