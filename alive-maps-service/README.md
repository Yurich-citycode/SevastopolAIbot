# Sevastopol Alive Maps — локальный сервис «живых» маршрутов

Пешие маршруты по Севастополю, которые оптимизируются не только по времени, но и
по «живости»: парки, набережные, кафе, историческая архитектура. Всё считается на
своей машине — свои тайлы, свой роутер, свои данные OpenStreetMap. Никаких Google,
Mapbox, ключей и внешних карт.

```
Alive Maps  ──►  fast   : 12 мин · 950 м
                 alive  : 15 мин · 1 320 м   через Приморский бульвар,
                                              мимо кафе «CoffeeBro», по набережной
```

---

## Запуск

> Подробная пошаговая инструкция, в том числе **если Docker не ставится**
> (Podman, WSL2, вариант без контейнеров): **[SETUP.md](SETUP.md)**

Нужен только **Docker Desktop** (Windows/macOS) или Docker Engine (Linux).
Больше ничего ставить не надо: данные, зоны, шрифты и тайлы готовятся
в контейнерах.

### Windows

1. Поставь [Docker Desktop](https://www.docker.com/products/docker-desktop/),
   перезагрузись, запусти его и дождись статуса **Engine running**.
2. Скачай папку `alive-maps-service` целиком (или `git clone` репозитория).
3. Двойной клик по **`start.bat`**.

### macOS / Linux / WSL

```bash
cd alive-maps-service
bash start.sh
```

### Что делает start.sh / start.bat

1. проверяет, что Docker установлен и запущен;
2. скачивает OSM-данные Севастополя (~39 МБ);
3. собирает «живые зоны» (парки, кафе, набережные, история);
4. качает шрифты для подписей;
5. собирает тайлы Planetiler (3–10 минут);
6. поднимает контейнеры и ждёт готовности GraphHopper (1–3 минуты);
7. открывает http://localhost:8080.

Повторный запуск ничего не перекачивает и поднимает стек за секунды.
Остановить: `docker compose down` (данные останутся в `data/`).

### Шаги по отдельности

Если хочется контролировать процесс или запускать частями:

```bash
make data      # скачать OSM
make zones     # собрать живые зоны
make fonts     # шрифты
make tiles     # тайлы (Planetiler)
make up        # поднять стек
make logs      # смотреть логи
make down      # остановить
```

Всё то же самое напрямую, без `make`:

```bash
docker compose --profile build run --rm tools sh /scripts/01-fetch-pbf.sh
docker compose --profile build run --rm tools python /scripts/02-build-zones.py \
    /data/sevastopol.osm.pbf -o /data/zones.geojson
docker compose --profile build run --rm tools sh /scripts/03-fetch-fonts.sh
docker compose --profile build run --rm planetiler
docker compose up -d --build
```

### Сколько ждать и сколько нужно

| | |
|---|---|
| Первый запуск | 10–20 минут (скачивание + тайлы + импорт графа) |
| Повторный запуск | 5–15 секунд |
| Диск | ~2 ГБ на данные/тайлы/граф + образы Docker |
| RAM | 6 ГБ (GraphHopper 2 ГБ + Planetiler 4 ГБ при сборке тайлов) |

## Что поднимается

| Сервис | Порт | Зачем |
|---|---|---|
| **backend** (FastAPI) | `8080` | фронтенд, `/api/*`, прокси тайлов |
| **graphhopper** | внутри `8989` | пеший роутинг + Custom Model + areas |
| **tileserver** (TileServer GL) | `8081` (для отладки) | раздаёт `sevastopol.mbtiles` и шрифты |
| **planetiler** | — | одноразовая сборка тайлов (`make tiles`) |

Данные лежат в одном общем каталоге `data/` — его видят все три сервиса:

```
data/
├── sevastopol.osm.pbf     # OSM-данные (скачивает make data)
├── zones.geojson          # живые зоны (собирает make zones)
├── sevastopol.mbtiles     # тайлы (собирает make tiles)
├── fonts/                 # шрифты подписей (make fonts)
└── graph-cache/           # граф GraphHopper (создаёт сам при импорте)
```

---

## Как это работает

```
        ┌──────────── Клик по карте (MapLibre GL) ────────────┐
        │                                                     │
        ▼                                                     │
  POST /api/route {start, end, mode}                           │
        │                                                     │
        ▼                                                     │
  FastAPI: для mode=alive собирает custom_model                │
   ├── правила по тегам OSM (тротуар/дорожка > шоссе)          │
   └── areas: полигоны «живых зон» + множитель приоритета      │
        │                                                     │
        ▼                                                     │
  GraphHopper /route (гибкий режим, ch.disable)                │
        │                                                     │
        ▼                                                     │
  GeoJSON маршрута + время/дистанция + бонусы → браузер ───────┘
```

**Быстрый маршрут** — обычный пеший запрос без custom model: минимум времени.
**Живой маршрут** — тот же движок, но:

1. *Приоритеты по классу улицы*: `FOOTWAY`, `PEDESTRIAN`, `PATH` получают 1.1–1.2,
   `PRIMARY` — 0.35, `MOTORWAY` — 0. Для пешехода это уже заметно приятнее.
2. *Приоритеты по месту* (`areas`): если отрезок попадает внутрь полигона зоны,
   его приоритет умножается ещё раз:

   | зона | множитель |
   |---|---|
   | `park` — парки, скверы, бульвары | ×1.8 |
   | `waterfront` — полоса 60 м вдоль воды | ×1.7 |
   | `historic` — памятники и музеи (буфер 78 м) | ×1.6 |
   | `cafe` — кварталы с кафе и ресторанами | ×1.45 |
   | `lively` — театры, рынки, площади | ×1.3 |

3. `distance_influence: 40` — маршрут готов сделать крюк ради приятной улицы,
   но не бесконечный.

Zone-полигоны совпадают по типу с `in_<id>` в условиях custom model — это
штатный механизм GraphHopper, а не самодельный велосипед.

Если GraphHopper не принимает `areas` (например, другая версия), бэкенд
автоматически повторяет запрос только с правилами по улицам, а в ответе
появляется `"degraded": true` — сервис продолжает работать.

---

## Мои точки и бот

Живые зоны берутся из OpenStreetMap, а мои места — из базы бота
(«Sevastopol AI База.xlsx»): кофе, кафе, пляжи, музеи, смотровые.

```bash
make pois        # база → data/pois.geojson (нужен pandas на машине)
```

Сервис сам подхватывает файл: рисует точки на карте (чип «мои места»),
даёт маршруту надбавку за проход рядом и называет их в объяснении.

Как это подключено к боту, где включается мини-апп и какие есть настройки —
[INTEGRATION.md](INTEGRATION.md).

## API

Все ответы — JSON, CORS открыт, авторизации нет (локальный сервис).

```http
POST /api/route
{ "start": [33.5955, 44.5955], "end": [33.5238, 44.6170], "mode": "alive", "strength": 1.0 }
```

```json
{
  "mode": "alive",
  "geojson": { "type": "Feature", "geometry": { "type": "LineString", "coordinates": [[33.59,44.59], …] } },
  "distance_m": 1320,
  "time_s": 900,
  "time_min": 15.0,
  "degraded": false,
  "bonuses": [
    { "kind": "park", "kind_ru": "парк", "name": "Приморский бульвар", "meters": 340 },
    { "kind": "cafe", "kind_ru": "улица с кафе", "name": "CoffeeBro", "meters": 0 }
  ],
  "cached": false
}
```

| Метод | Что делает |
|---|---|
| `POST /api/route` | один маршрут (`mode`: `fast` \| `alive`, `strength` 0…3) |
| `POST /api/compare` | оба сразу + блок `delta` (разница по времени и метрам) |
| `GET /api/pois` | мои точки из базы (GeoJSON) |
| `GET /api/compare.png?from=lat,lon&to=lat,lon` | та же пара маршрутов картинкой — для бота |
| `GET /api/zones` | GeoJSON живых зон (фронтенд рисует по кнопке «зоны») |
| `GET /api/config` | центр карты, bbox, состояние GraphHopper и тайлов |
| `GET /api/health` | здоровье сервиса |
| `GET /style.json` | стиль MapLibre (наш, тёмный) |
| `GET /tiles/{z}/{x}/{y}.pbf` | прокси к TileServer GL |
| `GET /fonts/…` | прокси шрифтов |

Проверка через curl:

```bash
curl -s localhost:8080/api/compare \
  -H 'content-type: application/json' \
  -d '{"start":[33.5955,44.5955],"end":[33.5238,44.6170]}' | python3 -m json.tool | head -30
```

---

## Настройка «живости»

Всё меняется без пересборки тайлов и без переимпорта графа:

* **Веса зон** — `backend/app/zones.py`, словарь `KIND_BONUS`.
  Например, сделать историю важнее кафе: `"historic": 1.9, "cafe": 1.3`.
* **Правила улиц** — `backend/app/gh.py`, список `BASE_PRIORITY`.
* **Крюк** — `ALIVE_DISTANCE_INFLUENCE` там же (меньше значение → маршрут охотнее гуляет).
* **Ползунок в интерфейсе** (`strength`) усиливает/ослабляет все зоны сразу;
  `0` — живой маршрут совпадёт с быстрым, `2` — максимум крюков.
* **Сами зоны** — `data/zones.geojson`. Это обычный GeoJSON: можно руками
  добавить полигон любимого дворика или, наоборот, удалить шумный рынок
  и перезапустить бэкенд (`docker compose restart backend`).

Пересобрать зоны из OSM заново: `make zones`.
Радиусы буферов — константы `BUFFER_CAFE`, `BUFFER_HIST`, `BUFFER_WATER`
в начале `scripts/02-build-zones.py`.

---

## Производительность

Ответ `/api/route` — десятки миллисекунд после прогрева, ответы кэшируются на
15 минут (`CACHE_TTL`). Если мало памяти — уменьшить `GH_MEMORY` и
`PLANETILER_MEMORY` в `.env` (планетилеру меньше 2 ГБ для города не хватит).

---

## Если что-то не работает

**Docker Desktop: «Engine stopped» / `docker info` падает**
Docker Desktop не запущен или не хватило WSL2. Открой Docker Desktop,
дождись статуса **Engine running**; на Windows включи WSL2
(`wsl --install` в PowerShell от администратора, потом перезагрузка).

**`GraphHopper: не найден файл данных /data/sevastopol.osm.pbf`**
Не выполнен `make data`. Файл должен лежать в `./data/`.

**Карта серая/пустая, домены тайлов в логах**
Не собран `sevastopol.mbtiles`: `make tiles`. Проверь, что файл появился
в `data/` и что `docker compose logs tileserver` не ругается на него.

**Нет подписей улиц**
Не скачаны шрифты: `make fonts` и `docker compose restart tileserver`.
Без шрифтов карта рисуется, просто без текста.

**`alive` маршрут не отличается от `fast`**
1. Ползунок «сила живых зон» на нуле.
2. Зоны не собраны (`GET /api/config` покажет `"zones": {"count": 0}`) → `make zones`.
3. В ответе `"degraded": true` — GraphHopper не принял `areas`. Посмотри
   `docker compose logs graphhopper`: там будет причина (обычно несовпадение
   версии и синтаксиса custom model). Сервис при этом продолжает считать
   по правилам улиц.

**`502 GraphHopper недоступен`**
Контейнер ещё импортирует граф (первый запуск) или упал: `make logs`.
Готовность видна по `curl localhost:8080/api/health`.

**Ошибка про `graph.encoded_values` при импорте**
Версия GraphHopper не знает какое-то значение из `graphhopper/config.yml`.
В сообщении будет список допустимых — удали лишнее и пересобери граф:
`rm -rf data/graph-cache && docker compose up -d graphhopper`.

---

## Чего здесь пока нет

Честный список, чтобы не было сюрпризов:

* **Геокодер** (поиск «Приморский бульвар» вместо клика) — в планах через Photon
  на тех же данных. Сейчас точки ставятся кликом или пресетами.
* **Время суток и погода** («сейчас темно — веди по светлым улицам»).
* **Кэш маршрутов на диске** — сейчас он в памяти процесса (15 минут).
* **Тесты в Docker** — см. ниже.

## Что проверено

Песочница, в которой писался код, без Docker, поэтому:

* проверены все конфиги (`make check`: JSON стиля и TileServer, YAML compose и GraphHopper);
* сборка зон прогнана на реальном формате OSM (синтетический `.osm` с парком,
  бухтой, кафе и памятником) — полигоны, объединение буферов и подписи работают;
* API прогнан через `fastapi.testclient` с подменённым GraphHopper:
  `compare`, `route`, `strength=0`, валидация координат, отдача стиля и статики —
  см. `scripts/04-smoke-test.py` (`make smoke`).

Сам `docker compose up` в песочнице не запускался — образы тянутся с Docker Hub
и GHCR, а сборка GraphHopper требует доступа к GitHub Releases.

---

## Стек и лицензии

* **Данные**: © OpenStreetMap contributors, ODbL 1.0.
* **Тайлы**: [Planetiler](https://github.com/onthegomap/planetiler) (Apache 2.0) +
  [TileServer GL](https://github.com/maptiler/tileserver-gl) (BSD-3).
* **Роутинг**: [GraphHopper](https://www.graphhopper.com/) 11.x (Apache 2.0).
* **Карта**: [MapLibre GL JS](https://maplibre.org/) 4.7.1 (BSD-3), лежит локально
  в `backend/app/static/vendor/` — интернет в браузере не нужен.
* **Стиль**: наш собственный `tiles/style.json` под схему OpenMapTiles.

Всё, что делает сервис, работает офлайн, кроме двух одноразовых шагов:
скачивания PBF (`make data`) и шрифтов (`make fonts`).
