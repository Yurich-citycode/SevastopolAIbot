# SECURITY — токены, секреты, состояние

Коротко: **в репозитории секретов нет и быть не должно.** Бот читает настройки
из переменных окружения (`os.getenv`), а `.env` — только локальное удобство.
Файл `.env` в `.gitignore`, `.dockerignore` и не попадает в образ контейнера.

| Переменная | Секрет? | Где обязательна |
|---|---|---|
| `TG_TOKEN` | 🔴 да | всегда (без неё бот не стартует, код выхода 2) |
| `ADMIN_ID` | 🟡 нет, но личное | для `/admin` и пересылки заявок с формы |
| `SPREADSHEET_ID` | 🟢 нет | таблица и так открыта «по ссылке» |
| `NEWS_CHANNEL_URL`, `SUGGEST_FORM_URL` | 🟢 нет | есть значения по умолчанию |
| `REFRESH_SECONDS`, `STATE_FILE` | 🟢 нет | есть значения по умолчанию |
| `ENV_FILE` | 🟢 нет | необязательно: путь к своему файлу настроек |

`BOT_TOKEN` поддерживается как синоним `TG_TOKEN` (удобно при переносе с
платформ, где переменная называется `BOT_TOKEN`); приоритет у `TG_TOKEN`.
Реальные переменные окружения **всегда** важнее содержимого `.env`
(`python-dotenv` вызывается без `override`), поэтому Docker/systemd/CI
перекрывают файл.

---

## 1. Локально: файл `.env` с правами 600

```bash
cp .env.example .env
nano .env                # вписать TG_TOKEN и ADMIN_ID
chmod 600 .env           # читать может только владелец
```

Проверка:

```bash
ls -l .env               # -rw------- 1 user user ...
git check-ignore -v .env # .gitignore:...  → файл игнорируется
git status --short       # .env в списке не появляется
```

При старте бот сам смотрит на права `.env` (рядом со скриптом и в текущей
директории), файла из `ENV_FILE` и `bot_state.json` — и пишет в лог
предупреждение, если файл читается кем-то кроме владельца:

```
2026-09-25 12:00:00 WARNING /opt/bot/.env: права 644 — рекомендую chmod 600
```

`bot_state.json` (XP-паспорта, рефералы, аналитика) сохраняется атомарно —
запись идёт в `bot_state.json.tmp` и затем `os.replace()`, поэтому падение
посреди записи не оставляет битый файл. После записи бот выставляет права 600.

---

## 2. Никогда не коммить

- `.env`, `*.json.tmp`, `bot_state.json` — в `.gitignore`.
- Не вписывай токен строкой в код, в ноутбук, в `docker-compose.yml`,
  в `wrangler.toml`, в GitHub Actions workflow.
- В Colab используй **Secrets** (🔑 слева) или `getpass` — не ячейку с токеном:
  `notebooks/SevastopolAI_bot.ipynb` спрашивает токен при запуске и ничего
  не сохраняет в файл ноутбука.
- Перед коммитом: `git diff --cached | grep -iE "token|secret|[0-9]{8,10}:AA"`.

Проверка рабочей копии на засветку:

```bash
grep -rEn "[0-9]{8,10}:AA[0-9A-Za-z_-]{30}" . --exclude-dir=.git --exclude-dir=.venv
```

---

## 3. Ротация и отзыв токена

1. @BotFather → `/mybots` → твой бот → **API Token** → **Revoke**
   (старый токен умирает сразу, новый выдаётся на месте).
2. Обнови значение во всех местах, где бот запущен:
   - локально — `.env`;
   - Docker — `docker rm -f` контейнер и `docker run -e TG_TOKEN=<новый>`;
   - systemd — `EnvironmentFile` → `sudo systemctl restart sevastopol-ai-bot`;
   - Cloudflare Worker — `npx wrangler secret put BOT_TOKEN`;
   - Railway/Render/Fly — переменная в панели → redeploy.
3. Проверь, что бот поднялся: в логах `🚀 Бот запущен`.
   Ошибка 401 = токен неверен/отозван (бот печатает понятную плашку).

**Если токен уже утёк в git-историю**, удаления файла из рабочей копии
недостаточно — история хранит старую версию:

```bash
# 1) обязательно отозвать токен (см. выше) — это главное
# 2) вычистить историю (переписывает коммиты — нужен force-push и
#    договорённость с остальными, кто работает с репозиторием)
pip install git-filter-repo
git filter-repo --path notebooks/SevastopolAI_bot.ipynb --invert-paths
git push --force origin main
# 3) на GitHub: Settings → Danger Zone → или поддержка, чтобы сбросить кэш вьюх
```

> ⚠️ В этом репозитории в коммите `12eb550`, файл
> `notebooks/SevastopolAI_bot.ipynb`, токен бота был вписан строкой
> «временно для теста в Colab». Из рабочей копии он убран (ячейка теперь
> спрашивает токен через `getpass`/Colab Secrets), но в git-истории он
> остался. **Считай токен скомпрометированным: @BotFather → /mybots →
> API Token → Revoke.** Подробности — `AUDIT_REPORT.md`.

---

## 4. Docker: секреты через `-e` / `--env-file`, состояние в volume

```bash
docker build -t sevastopol-ai-bot .

# вариант A: переменные в команде (остаются в shell history — для теста)
docker run -d --name sevastopol-ai-bot --restart unless-stopped \
  -e TG_TOKEN=123456789:AAABBBCCC \
  -e ADMIN_ID=123456789 \
  -e STATE_FILE=/data/bot_state.json \
  -v sevastopol-state:/data \
  sevastopol-ai-bot

# вариант B (рекомендуется): файл вне репозитория, права 600
sudo install -m 600 /dev/null /etc/sevastopol-ai-bot.env
sudo nano /etc/sevastopol-ai-bot.env      # TG_TOKEN=... ADMIN_ID=... STATE_FILE=/data/bot_state.json
docker run -d --name sevastopol-ai-bot --restart unless-stopped \
  --env-file /etc/sevastopol-ai-bot.env \
  -v sevastopol-state:/data \
  sevastopol-ai-bot

```

Docker Secrets (Swarm / Engine 25+): секрет должен содержать **готовый
env-файл** (строки `KEY=VALUE`), тогда бот прочитает его через `ENV_FILE`:

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

Volume `sevastopol-state` обязателен, если нужны XP-паспорта и статистика
между пересозданиями контейнера: без него `bot_state.json` живёт внутри
контейнера и теряется. Перенос состояния на новый сервер:

```bash
docker run --rm -v sevastopol-state:/data -v "$PWD":/backup alpine \
  cp /data/bot_state.json /backup/     # забрать со старого
docker cp bot_state.json <container>:/data/   # положить на новый
```

Логи: `docker logs -f sevastopol-ai-bot`. Токен в логи не печатается.

---

## 5. systemd: `EnvironmentFile`

Секреты — в отдельном файле вне репозитория, не в юните:

```bash
sudo install -m 600 /dev/null /etc/sevastopol-ai-bot.env
sudo nano /etc/sevastopol-ai-bot.env
```

`/etc/sevastopol-ai-bot.env`:

```
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
их видит, `.env` в репозитории не нужен. Ротация: правка файла →
`systemctl restart sevastopol-ai-bot`.

---

## 6. GitHub Secrets / Actions

Repository → Settings → Secrets and variables → Actions → **New repository secret**:
`TG_TOKEN`, `ADMIN_ID`. В workflow — только через `${{ secrets.TG_TOKEN }}`:

```yaml
- name: Run bot
  env:
    TG_TOKEN: ${{ secrets.TG_TOKEN }}
    ADMIN_ID: ${{ secrets.ADMIN_ID }}
  run: python sevastopolaibot.py
```

Секреты не печатаются в логах GitHub (маскируются `***`) и не доступны
fork-ам в PR. Никогда не делай `echo "$TG_TOKEN"` и не клади их в артефакты.

---

## 7. Vault / Doppler / SOPS — внешний менеджер секретов

Боту всё равно, откуда пришли переменные: ему хватает `os.getenv()`.
Значит, любой менеджер, умеющий инжектить окружение в процесс, подходит
без единой строчки хардкода и без `.env` в репозитории.

**HashiCorp Vault (Agent / envconsul):**

```bash
# секрет в KV v2
vault kv put secret/sevastopol-ai-bot TG_TOKEN=123456789:AAA... ADMIN_ID=123456789

# запуск через envconsul — переменные подставятся сами
envconsul -pristine -secret=secret/sevastopol-ai-bot \
  -upcase -once python sevastopolaibot.py

# либо Vault Agent с template в /run/secrets/bot.env + EnvironmentFile=
```

**Doppler:**

```bash
doppler setup -p sevastopol-ai-bot -c prd
doppler run -- python sevastopolaibot.py     # локально
# в Docker: doppler run --config prd -- docker run --rm -e TG_TOKEN ...
# в systemd: ExecStart=/usr/local/bin/doppler run -- python -u sevastopolaibot.py
```

**SOPS + age (шифрованный файл прямо в git — единственный случай, когда
«секрет в репозитории» допустим):**

```bash
sops --encrypt --in-place .env.enc            # шифруем, коммитим .env.enc
sops exec-file .env.enc 'cp {} /run/secrets/bot.env && chmod 600 /run/secrets/bot.env'
ENV_FILE=/run/secrets/bot.env python sevastopolaibot.py
```

**1Password / AWS / GCP:** `op run --env-file=.env.tpl -- python sevastopolaibot.py`,
`aws secretsmanager get-secret-value` → `export`, `gcloud secrets versions access`.
Схема одна: менеджер отдаёт переменные → `os.getenv()` их читает.

---

## 8. Railway / Render / Fly.io / PythonAnywhere

Панель → Environment/Variables → добавить `TG_TOKEN` и `ADMIN_ID` → redeploy.
Команда запуска: `python sevastopolaibot.py`. Файл `.env` на этих платформах
не нужен (и не должен коммититься).

- **Render**: Settings → Environment → Add; диски — для `STATE_FILE`
  (иначе состояние теряется при каждом деплое).
- **Railway**: Variables → New Variable; Volume примонтировать и указать
  `STATE_FILE=/data/bot_state.json`.
- **Fly.io**: `fly secrets set TG_TOKEN=... ADMIN_ID=...` (хранятся в Vault
  Fly и подставляются в окружение); volume — `fly volumes create state`.

---

## 9. Cloudflare Worker (форма предложений)

Токен основного бота для `worker/index.js` — **секрет Worker'а**, в коде и в
`wrangler.toml` его нет:

```bash
cd worker
npx wrangler login
npx wrangler secret put BOT_TOKEN      # токен бота от @BotFather
npx wrangler secret put ADMIN_ID       # кому слать заявки
npx wrangler secret list               # имена секретов (значения не показываются)
npx wrangler deploy
```

Или в Dashboard: Worker → Settings → Variables and Secrets → Add → тип **Secret**
→ Deploy. Без обоих значений Worker отвечает `server_not_configured` (500) и
ничего никуда не шлёт. Ротация: `/revoke` у @BotFather → `wrangler secret put
BOT_TOKEN` → `wrangler deploy`.

---

## 10. Что ещё учесть

- **Google-таблица** — источник данных. Доступ «Все, у кого есть ссылка →
  Читатель»: значит, её содержимое публично. Не вноси туда персональные данные
  пользователей и не считай `SPREADSHEET_ID` секретом.
- **Заявки с формы** содержат контакты пользователей (`@username`, телефон) и
  пересылаются в личку `ADMIN_ID`. Храни `bot_state.json` с правами 600 и не
  коммить его.
- **Логи**: бот пишет в лог имя/username и действие (аналитика). Токен,
  координаты пользователей и содержимое `.env` в логи не попадают. Если
  собираешь логи в внешний сервис — помни, что там будут username пользователей.
- **Один токен — один процесс.** Два бота с одним токеном конфликтуют
  (`409 Conflict: terminated by other getUpdates request`).
- **Зависимости**: `pip install -r requirements.txt` и периодически
  `pip list --outdated`; aiogram закреплён мажорной версией `>=3.7,<4`.
