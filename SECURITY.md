# SECURITY — как я храню токены, секреты и состояние

Коротко: **в моём репозитории секретов нет и быть не должно.** Бот читает настройки
из переменных окружения (`os.getenv`), а `.env` я использую только локально.
Файл `.env` добавлен в `.gitignore` и `.dockerignore`, поэтому не попадает ни в git, ни в образ контейнера.

| Переменная | Секрет? | Где обязательна |
|---|---|---|
| `TG_TOKEN` | 🔴 да | всегда (без неё бот не стартует, код выхода 2) |
| `ADMIN_ID` | 🟡 нет, но личное | для `/admin` и пересылки заявок с формы |
| `SPREADSHEET_ID` | 🟢 нет | таблица открыта на чтение «по ссылке» |
| `NEWS_CHANNEL_URL`, `SUGGEST_FORM_URL` | 🟢 нет | есть значения по умолчанию |
| `REFRESH_SECONDS`, `STATE_FILE` | 🟢 нет | есть значения по умолчанию |
| `ENV_FILE` | 🟢 нет | необязательно: путь к моему файлу настроек |

`BOT_TOKEN` поддерживается как синоним `TG_TOKEN` (удобно при переносе между
платформами); приоритет у `TG_TOKEN`. Реальные переменные окружения **всегда**
важнее содержимого `.env` (`python-dotenv` вызывается без `override`), поэтому
Docker, systemd и CI перекрывают файл.

---

## 1. Локально: файл `.env` с правами 600

```bash
cp .env.example .env
nano .env                # вписываю TG_TOKEN и ADMIN_ID
chmod 600 .env           # чтение только для владельца
```

Как я проверяю права и git-статус:

```bash
ls -l .env               # -rw------- 1 user user ...
git check-ignore -v .env # .gitignore:...  → файл игнорируется
git status --short       # .env в списке не появляется
```

При старте бот сам проверяет права `.env` (рядом со скриптом и в текущей
директории), файла из `ENV_FILE` и `bot_state.json` — и пишет в лог
предупреждение, если файл доступен кому-то кроме владельца:

```
2026-09-25 12:00:00 WARNING /opt/bot/.env: права 644 — рекомендую chmod 600
```

`bot_state.json` (XP-паспорта, рефералы, аналитика) сохраняется атомарно —
запись идёт в `bot_state.json.tmp` и затем `os.replace()`, поэтому сбой
посреди записи не оставляет битый файл. После записи бот сам выставляет права 600.

---

## 2. Что я никогда не коммичу в git

- `.env`, `*.json.tmp`, `bot_state.json`, `backups/` — в `.gitignore`.
- Я не вписываю токен строкой в код, в ноутбук, в `docker-compose.yml`,
  в `wrangler.toml` или в GitHub Actions workflow.
- В Colab я использую **Secrets** (🔑 слева) или `getpass` —
  `notebooks/SevastopolAI_bot.ipynb` спрашивает токен при запуске и ничего
  не сохраняет в файл ноутбука.
- Перед коммитом могу проверить индексацию: `git diff --cached | grep -iE "token|secret|[0-9]{8,10}:AA"`.

Проверка рабочей папки на случайную засветку токена:

```bash
grep -rEn "[0-9]{8,10}:AA[0-9A-Za-z_-]{30}" . --exclude-dir=.git --exclude-dir=.venv
```

---

## 3. Ротация и отзыв токена

1. Открываю @BotFather → `/mybots` → выбираю бота → **API Token** → **Revoke**
   (старый токен отключается сразу, новый выдаётся на месте).
2. Обновляю значение там, где у меня запущен бот:
   - локально — в `.env`;
   - Docker — пересоздаю контейнер или обновляю `/etc/sevastopol-ai-bot.env`;
   - systemd — правлю `/etc/sevastopol-ai-bot.env` → `sudo systemctl restart sevastopol-ai-bot`;
   - Cloudflare Worker — `npx wrangler secret put BOT_TOKEN`;
   - Railway/Render/Fly — обновляю переменную в панели → redeploy.
3. Проверяю по логам, что бот поднялся: `🚀 Бот запущен`.
   Ошибка 401 означает, что токен неверен или отозван.

Если секрет когда-либо попал в git-историю, я сразу отзываю его через @BotFather,
а при необходимости чищу историю через `git filter-repo`.

---

## 4. Docker: секреты через `-e` / `--env-file`, состояние в volume

```bash
docker build -t sevastopol-ai-bot .

# вариант A: переменные в команде (для быстрого теста)
docker run -d --name sevastopol-ai-bot --restart unless-stopped \
  -e TG_TOKEN=123456789:AAABBBCCC \
  -e ADMIN_ID=123456789 \
  -e STATE_FILE=/data/bot_state.json \
  -v sevastopol-state:/data \
  sevastopol-ai-bot

# вариант B (основной): файл вне репозитория с правами 600
sudo install -m 600 /dev/null /etc/sevastopol-ai-bot.env
sudo nano /etc/sevastopol-ai-bot.env      # TG_TOKEN=... ADMIN_ID=... STATE_FILE=/data/bot_state.json
docker run -d --name sevastopol-ai-bot --restart unless-stopped \
  --env-file /etc/sevastopol-ai-bot.env \
  -v sevastopol-state:/data \
  sevastopol-ai-bot
```

Docker Secrets (Swarm / Engine 25+): секрет хранит готовый env-файл
(строки `KEY=VALUE`), и бот читает его через `ENV_FILE`:

```bash
printf 'TG_TOKEN=123456789:AAABBBCCC\nADMIN_ID=123456789\n' | docker secret create sevastopol_bot_env -

docker service create --name sevastopol-ai-bot \
  --secret sevastopol_bot_env \
  -e ENV_FILE=/run/secrets/sevastopol_bot_env \
  -e STATE_FILE=/data/bot_state.json \
  --mount type=volume,source=sevastopol-state,target=/data \
  sevastopol-ai-bot

# одиночный контейнер (Docker Engine 25+):
docker run -d --secret sevastopol_bot_env \
  -e ENV_FILE=/run/secrets/sevastopol_bot_env sevastopol-ai-bot
```

Volume `sevastopol-state` сохраняет мои XP-паспорта и статистику
между пересозданиями контейнера. Перенос состояния на новый сервер:

```bash
docker run --rm -v sevastopol-state:/data -v "$PWD":/backup alpine \
  cp /data/bot_state.json /backup/     # забрать со старого
docker cp bot_state.json <container>:/data/   # положить на новый
```

Логи: `docker logs -f sevastopol-ai-bot`. Токен в логи не выводится.

---

## 5. systemd: `EnvironmentFile`

Мой скрипт `install.sh` настраивает всё автоматически: создаёт `/etc/sevastopol-ai-bot.env` с правами 600, запускает бота от отдельного системного пользователя без прав входа и ограничивает запись папкой `/var/lib/sevastopol-ai-bot`. Ниже — конфигурация, которую он создаёт.

Секреты лежат в отдельном файле вне репозитория:

```bash
sudo install -m 600 /dev/null /etc/sevastopol-ai-bot.env
sudo nano /etc/sevastopol-ai-bot.env
```

`/etc/sevastopol-ai-bot.env`:

```ini
TG_TOKEN=123456789:AAABBBCCC
ADMIN_ID=123456789
STATE_FILE=/var/lib/sevastopol-ai-bot/bot_state.json
```

`/etc/systemd/system/sevastopol-ai-bot.service`:

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
StateDirectory=sevastopol-ai-bot
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
journalctl -u sevastopol-ai-bot -f
```

`EnvironmentFile` подставляет значения как переменные окружения — `os.getenv()`
их видит, `.env` в папке кода не нужен. При ротации токена я правлю файл и
выполняю `sudo systemctl restart sevastopol-ai-bot`.

---

## 6. GitHub Secrets / Actions

Repository → Settings → Secrets and variables → Actions → **New repository secret**:
`TG_TOKEN`, `ADMIN_ID`. В workflow я передаю их только через `${{ secrets.TG_TOKEN }}`:

```yaml
- name: Run bot
  env:
    TG_TOKEN: ${{ secrets.TG_TOKEN }}
    ADMIN_ID: ${{ secrets.ADMIN_ID }}
  run: python sevastopolaibot.py
```

Секреты маскируются в логах GitHub (`***`) и не попадают в артефакты.

---

## 7. Vault / Doppler / SOPS — внешние менеджеры секретов

Боту достаточно переменных окружения через `os.getenv()`, поэтому подходит
любой менеджер секретов без правок кода.

**HashiCorp Vault (Agent / envconsul):**

```bash
vault kv put secret/sevastopol-ai-bot TG_TOKEN=123456789:AAA... ADMIN_ID=123456789

envconsul -pristine -secret=secret/sevastopol-ai-bot \
  -upcase -once python sevastopolaibot.py
```

**Doppler:**

```bash
doppler setup -p sevastopol-ai-bot -c prd
doppler run -- python sevastopolaibot.py
```

**SOPS + age (зашифрованный файл):**

```bash
sops --encrypt --in-place .env.enc
sops exec-file .env.enc 'cp {} /run/secrets/bot.env && chmod 600 /run/secrets/bot.env'
ENV_FILE=/run/secrets/bot.env python sevastopolaibot.py
```

**1Password / AWS / GCP:** `op run --env-file=.env.tpl -- python sevastopolaibot.py`,
`aws secretsmanager get-secret-value` → `export`, `gcloud secrets versions access`.

---

## 8. Railway / Render / Fly.io / PythonAnywhere

В панели платформы (Environment / Variables) я задаю `TG_TOKEN` и `ADMIN_ID`,
команда запуска — `python sevastopolaibot.py`.

- **Render**: Settings → Environment → Add; диск подключаю для `STATE_FILE`.
- **Railway**: Variables → New Variable; монтирую Volume и ставлю `STATE_FILE=/data/bot_state.json`.
- **Fly.io**: `fly secrets set TG_TOKEN=... ADMIN_ID=...` и `fly volumes create state`.

---

## 9. Cloudflare Worker (форма предложений)

Токен основного бота для `worker/index.js` хранится в секретах Worker'а, в коде и в
`wrangler.toml` его нет:

```bash
cd worker
npx wrangler login
npx wrangler secret put BOT_TOKEN      # токен бота от @BotFather
npx wrangler secret put ADMIN_ID       # мой Telegram ID для приёма заявок
npx wrangler secret list               # список имён секретов
npx wrangler deploy
```

Или через браузер: Worker → Settings → Variables and Secrets → Add → тип **Secret**
→ Deploy. Без обоих значений Worker возвращает `server_not_configured` (500).
При ротации токена я вызываю `/revoke` у @BotFather и обновляю секрет через `wrangler secret put BOT_TOKEN`.

---

## 10. Важные детали

- **Google-таблица** открыта по ссылке на чтение, поэтому я не храню в ней персональные данные пользователей.
- **Заявки с формы** содержат контакты отправителей (`@username`, телефон) и приходят мне в личку на `ADMIN_ID`. Файл `bot_state.json` я держу с правами 600.
- **Логи**: в лог пишутся действия пользователей для аналитики. Токен, координаты пользователей и содержимое `.env` в логи не попадают.
- **Один токен — один процесс.** Два параллельных процесса с одним токеном дают `409 Conflict: terminated by other getUpdates request`.
- **Зависимости**: ставлю через `pip install -r requirements.txt`; версия aiogram закреплена в пределах `>=3.7,<4`.
