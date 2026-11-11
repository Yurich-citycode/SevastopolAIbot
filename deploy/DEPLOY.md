# Запуск на сервере

Короткая инструкция: купить VPS, поднять бота и карту, включить мини-апп.
Всё, что дальше — команды по порядку, ничего редактировать в коде не нужно.

## Что нужно

| Требование | Зачем |
|---|---|
| VPS на Ubuntu 22.04 / 24.04 | бот и карта живут рядом |
| 4 vCPU, 8 ГБ RAM, 60 ГБ диска | сборка тайлов и импорт графа требуют памяти |
| Docker + docker compose | ставится одной командой |
| Токен от @BotFather и свой Telegram ID | без них бот не стартует |

Дешевле 4 ГБ брать не стоит: Planetiler и GraphHopper съедают память при сборке.

## 1. Подготовка сервера

```bash
ssh root@IP_СЕРВЕРА
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
```

Проверка: `docker run --rm hello-world` печатает приветствие.

## 2. Код и настройки

```bash
git clone https://github.com/Yurich-citycode/SevastopolAIbot.git
cd SevastopolAIbot
python3 tools/setup_env.py      # спросит токен и Telegram ID, создаст .env
```

Мастера нет или хотите руками — `cp .env.example .env` и вписать `TG_TOKEN` и
`ADMIN_ID`. Файл `.env` в git не попадает.

## 3. Запуск одной командой

```bash
bash deploy/server.sh
```

Что произойдёт:

1. проверит Docker и `.env`;
2. скачает данные OSM, соберёт зоны, шрифты и тайлы (**первый раз 15–25 минут**);
3. поднимет карту и дождётся, пока GraphHopper импортирует граф;
4. поднимет бота контейнером с автоперезапуском.

В конце увидите:

```
Готово
  карта:  http://localhost:8080
  бот:    пиши ему в Telegram — кнопка «🗺 Живая карта»
```

Если данные карты уже собраны — `bash deploy/server.sh --fast` (поднимает за
минуту, ничего не пересобирает).

## 4. Проверка

```bash
curl -s localhost:8080/api/health
```

Должно быть `"ok":true` и `"graphhopper":{"ok":true}`.

В Telegram у бота: кнопка **«🗺 Живая карта»** → `зон: … · моих мест: … · роутер готов`.
Команда `/route Фиолент` → картинка с двумя маршрутами.

## 5. Мини-апп (карта внутри Telegram)

Telegram открывает только https, поэтому нужен адрес. Два варианта:

**Быстро, без домена** — туннель Cloudflare:

```bash
bash alive-maps-service/tools/map_tunnel.sh
```

Скрипт выдаст `https://что-то.trycloudflare.com` и сам впишет его в `.env`.
Дальше перезапустить бота и в @BotFather сделать `/setmenubutton` с этим адресом.
Минус: адрес живёт, пока запущен туннель.

**Постоянно** — свой домен на этот же сервер: Caddy или nginx как reverse proxy
на `localhost:8080`, сертификат выпускается автоматически. В `.env`:
`ALIVE_MAP_PUBLIC=https://map.ваш-домен.ру`, перезапустить бота, тот же адрес в
`/setmenubutton`.

## 6. Обслуживание

```bash
git pull                                   # обновить код
bash deploy/server.sh --fast               # перезапустить после обновления

docker compose -f deploy/docker-compose.server.yml logs -f     # логи бота
docker compose -f alive-maps-service/docker-compose.yml logs -f graphhopper

docker compose -f deploy/docker-compose.server.yml down        # остановить бота
docker compose -f alive-maps-service/docker-compose.yml down   # остановить карту
```

Паспорта и статистика бота лежат в `deploy/bot-state/` — переживают пересборку.
Данные карты — в `alive-maps-service/data/` (около 2 ГБ).

## Если что-то не так

| Симптом | Что делать |
|---|---|
| `docker: command not found` | `curl -fsSL https://get.docker.com | sh` |
| `permission denied` на docker | `usermod -aG docker $USER && newgrp docker` |
| скрипт падает на сборке тайлов | мало памяти: нужен VPS с 8 ГБ или соберите данные локально и перенесите папку `data` |
| карта отвечает, маршруты нет | GraphHopper ещё импортирует: `docker compose -f alive-maps-service/docker-compose.yml logs -f graphhopper` |
| бот молчит | `docker compose -f deploy/docker-compose.server.yml logs --tail=50` |
| бот пишет «сервис не отвечает» | карта не поднялась: `curl localhost:8080/health` |

## Что занимает место

| Что | Размер |
|---|---|
| данные OSM и тайлы (`alive-maps-service/data`) | ~1.5–2 ГБ |
| образы Docker | ~1.5 ГБ |
| состояние бота (`deploy/bot-state`) | мегабайты |
