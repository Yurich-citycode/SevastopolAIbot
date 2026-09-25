# Микросервис заявок (Cloudflare Worker)

Принимает данные формы `suggest.html`, собирает аккуратное сообщение и
шлёт его в личку владельцу через Telegram Bot API.

- Работает на бесплатном плане Cloudflare Workers (100 000 запросов/день —
  с огромным запасом).
- В коде и в git секретов нет: `BOT_TOKEN` и `ADMIN_ID` задаются как
  переменные/секреты Worker'а. Без них POST вернёт `server_not_configured`.

---

## Деплой через браузер (10 минут, без установки чего-либо)

### Шаг 1. Вход
1. Открыть https://dash.cloudflare.com и войти в аккаунт.

### Шаг 2. Создать Worker
2. Слева в меню: **Compute (Workers) → Workers & Pages**.
3. Нажать **Create** → **Create Worker** → **Deploy** (дефолтный «Hello world»
   устраивает, имя можно оставить предложенное или вписать `sevastopol-suggest`
   — от имени получится адрес вида `https://sevastopol-suggest.<ваш-сабдомен>.workers.dev`).
4. После деплоя нажать **Edit code**.

### Шаг 3. Код
5. Удалить в редакторе всё, что там есть, вставить **весь код** из файла
   [`index.js`](index.js) этой папки и нажать **Deploy** (справа вверху).

### Шаг 4. Секреты: токен бота и кому слать заявки
6. Вернуться: **Compute (Workers) → Workers & Pages → sevastopol-suggest →
   Settings → Variables and Secrets**.
7. **Add** → тип **Secret**, две записи:
   - `BOT_TOKEN` — токен **основного** бота Sevastopol AI от @BotFather
     (тот же, что в `.env` бота, строка `TG_TOKEN`);
   - `ADMIN_ID` — твой Telegram ID (узнать: написать @userinfobot),
     тот же, что `ADMIN_ID` у бота.
8. Нажать **Deploy** внизу.

### Шаг 5. Проверка
9. Открыть в браузере `https://sevastopol-suggest.<ваш-сабдомен>.workers.dev` —
   должна появиться страница «✓ Сервис заявок Sevastopol AI работает».
10. Открыть форму https://yurich-citycode.github.io/SevastopolAIbot/suggest.html,
    заполнить, нажать «Отправить» → в личке у владельца должно прийти сообщение.
    Если прилетело — всё готово.

### Шаг 6. Подключить адрес к форме
11. Скопировать адрес Worker'а (например,
    `https://sevastopol-suggest.your-name.workers.dev`).
12. Открыть в репозитории `suggest.html`, найти строку:
    ```js
    var WORKER_URL = "__WORKER_URL__";
    ```
    и вставить адрес:
    ```js
    var WORKER_URL = "https://sevastopol-suggest.your-name.workers.dev";
    ```
    (править можно прямо на GitHub: открыть файл → карандаш → Commit).
    GitHub Pages обновится через минуту-две.

> Пока в `WORKER_URL` стоит заглушка, форма не ломается: она переключается
> в резервный режим и предлагает скопировать текст заявки в бота вручную.

---

## Деплой через wrangler (альтернатива для консоли)

```bash
cd worker
npx wrangler login
npx wrangler secret put BOT_TOKEN     # токен основного бота от @BotFather
npx wrangler secret put ADMIN_ID      # Telegram ID владельца (тот же, что у бота)
npx wrangler deploy
```

Секреты хранятся зашифрованными на стороне Cloudflare и не попадают ни в
`wrangler.toml`, ни в git. Проверить список (значения не показываются):
`npx wrangler secret list`. Ротация токена — повторный `wrangler secret put
BOT_TOKEN` после `/revoke` у @BotFather (см. корневой `SECURITY.md`).

---

## Что приходит владельцу

```
📝 Новое предложение места

🏷 Название: Кофейня «Кристалл»
📂 Категория: Кофе
📍 Адрес/район: ул. Пушкина, 4
💰 Цены: 250–500 ₽
📞 Телефон: +7 …
🔗 Ссылки: https://…
ℹ️ Описание: Лучший раф в городе
👤 Контакт: @username
```
