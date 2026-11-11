# Установка и запуск — пошагово

Инструкция для человека, который просто хочет запустить сервис и посмотреть.
Один раз настраиваем — дальше запуск занимает 10 секунд.

Что получится: локальная карта Севастополя на `http://localhost:8080`.
Два пеших маршрута — «быстрый» и «живой» (через парки, набережные, кафе,
историю). Всё считается на твоём компьютере, чужие серверы не участвуют.

---

## Что понадобится

| | |
|---|---|
| Операционная система | Windows 10/11, macOS или Linux |
| Свободное место | ~6 ГБ (образы + данные + тайлы + граф) |
| Оперативная память | 6 ГБ и больше (сборка тайлов — самый прожорливый шаг) |
| Интернет | нужен только при первой подготовке, дальше всё офлайн |
| Время | первый запуск 10–20 минут, потом 10 секунд |

Дальше выбери **один** вариант:

* [Вариант A — Docker Desktop](#вариант-a--docker-desktop-windows-и-macos-рекомендуется)
* [Вариант B — Podman Desktop (аналог Docker, если Docker не ставится)](#вариант-b--podman-desktop-если-docker-desktop-не-ставится)
* [Вариант C — Docker без Docker Desktop (внутри WSL2)](#вариант-c--docker-без-docker-desktop-внутри-wsl2-windows)
* [Вариант D — совсем без контейнеров (Java + Node + Python)](#вариант-d--совсем-без-контейнеров-долго-но-без-docker)

---

## Где взять файлы

Репозиторий: **https://github.com/Yurich-citycode/SevastopolAIbot**

Папка сервиса в репозитории:
**https://github.com/Yurich-citycode/SevastopolAIbot/tree/arena/8d598d96-sevastopolaibot/alive-maps-service**

Скачать архивом (проще всего):

```
https://github.com/Yurich-citycode/SevastopolAIbot/archive/refs/tags/alive-maps-service-v1.4.zip
```

Распакуй — внутри будет папка `alive-maps-service`. Дальше все команды
выполняются **из неё**.

Если умеешь git:

```bash
git clone https://github.com/Yurich-citycode/SevastopolAIbot.git
cd SevastopolAIbot/alive-maps-service
```

---

## Вариант A — Docker Desktop (Windows и macOS). Рекомендуется

### A1. Установить Docker Desktop

1. Скачать: https://www.docker.com/products/docker-desktop/
2. Запустить установщик, согласиться со всем по умолчанию.
   *Windows попросит включить WSL2 — согласись, потом перезагрузись.*
3. После перезагрузки запустить **Docker Desktop**.
4. Дождаться, пока в левом нижнем углу не появится зелёное
   **Engine running**. Это может занять 1–2 минуты.

### A2. Проверить, что Docker работает

Открой **PowerShell** (Win+X → «Терминал») и введи:

```powershell
docker info
```

Должен быть длинный вывод про `Server Version`, `Operating System` и т.п.
Если написано `error during connect` — Docker Desktop не запущен.
Если написано `'docker' is not recognized` — не установлен или нужен
перезапуск после установки.

### A3. Запустить сервис

Открой папку `alive-maps-service` и дважды щёлкни **`start.bat`**.

Откроется чёрное окно, в нём будет примерно такое:

```
Sevastopol Alive Maps - локальная карта с живыми маршрутами

> Проверяю Docker
  [ok] Docker работает

> Данные OpenStreetMap для Севастополя (~39 МБ)
  ... качается ...
  [ok] скачано

> Живые зоны: парки, кафе, набережные, история
  ... собирается ...
  [ok] собрано

> Шрифты для подписей на карте
  [ok] уже есть

> Тайлы карты (Planetiler, 3-10 минут на первый раз)
  ... идёт сборка ...
  [ok] тайлы собраны

> Поднимаю сервисы
  [ok] контейнеры запущены

> Жду GraphHopper (первый раз - импорт графа, 1-3 минуты)
  ... ещё жду (30 с)
  [ok] сервис готов

-> http://localhost:8080
```

Браузер откроется сам. Если не открылся — зайди вручную на
**http://localhost:8080**.

> Первый запуск идёт долго именно из-за тайлов и импорта графа.
> Это нормально: не закрывай окно, оно само скажет, когда готово.

### A4. Что делать в интерфейсе

1. Клик по карте — точка **A**. Второй клик — точка **B**.
2. Нажми **«Посчитать оба сразу»**.
3. Слева появятся два маршрута: время, расстояние и через что прошёл
   «живой». На карте живой — сплошная лаймовая линия, быстрый — пунктир.
4. Кнопка **«зоны»** на карте показывает, что именно считается жизнью
   (парки, вода, кафе, история).
5. Ползунок «сила живых зон» усиливает или ослабляет крюки.

Есть 4 готовых пресета (Вокзал → Приморский и т.д.) — на них проще всего
убедиться, что всё работает.

### A5. Как выключить и включить снова

```powershell
# выключить
docker compose down

# включить снова (быстро, всё уже собрано)
docker compose up -d
```

---

## Вариант B — Podman Desktop (если Docker Desktop не ставится)

Podman — полноценный аналог Docker от Red Hat, без лицензионных
ограничений Docker Desktop. Скачивается и ставится как обычная программа.

### B1. Установка

1. Скачать **Podman Desktop**: https://podman-desktop.io/downloads
2. Установить, запустить.
3. На главном экране нажать **Initialize** (создать виртуальную машину
   с движком) — на Windows это займёт пару минут.
4. Дождаться статуса **Running**.

### B2. Проверка

```powershell
podman version
podman compose version
```

`podman compose version` должен ответить версией. Если пишет, что compose
не найден — установи в Podman Desktop расширение **Compose** (раздел
Extensions) или отдельно `docker-compose` через `pip install docker-compose`.

### B3. Запуск

В папке сервиса:

```powershell
podman compose --profile build run --rm tools sh /scripts/01-fetch-pbf.sh
podman compose --profile build run --rm tools python /scripts/02-build-zones.py /data/sevastopol.osm.pbf -o /data/zones.geojson
podman compose --profile build run --rm tools sh /scripts/03-fetch-fonts.sh
podman compose --profile build run --rm planetiler
podman compose up -d --build
```

Или короче: `start.bat` сам найдёт podman, если Docker нет
(скрипт ищет `docker compose`, потом `podman compose`).

### B4. Что может отличаться

* команды те же, только `docker` → `podman`;
* на Windows Podman работает через WSL2 — если WSL2 не работает,
  он не заработает так же, как и Docker Desktop (см. вариант C, шаг 1);
* данные, тайлы и конфиги идентичны, ничего переделывать не надо.

---

## Вариант C — Docker без Docker Desktop (внутри WSL2, Windows)

Подходит, если Docker Desktop не устанавливается: лицензия, антивирус,
корпоративные политики. Внутри WSL2 стоит обычный Linux-**Docker Engine**,
и это ровно тот же Docker, только без графической оболочки.

### C1. Включить WSL2

В PowerShell **от администратора**:

```powershell
wsl --install
```

Перезагрузись. После перезагрузки откроется Ubuntu (или запусти `wsl`),
задай логин и пароль.

Проверка в PowerShell:

```powershell
wsl --status
```

### C2. Поставить Docker Engine внутри Ubuntu

В окне Ubuntu:

```bash
sudo apt update && sudo apt install -y curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
docker info
```

Последняя команда должна показать `Server Version` без `sudo`.

### C3. Запуск из WSL

Папку сервиса видно из WSL как `/mnt/c/Users/…/alive-maps-service`:

```bash
cd /mnt/c/Users/ИМЯ/Downloads/alive-maps-service
bash start.sh
```

Дальше — как в варианте A: браузер на Windows откроет
`http://localhost:8080` (WSL2 пробрасывает порт сам).

> Медленно, если проект лежит на диске `C:` — файлы идут через прослойку.
> Если раздражает, скопируй папку внутрь WSL: `cp -r /mnt/c/... ~/alive-maps`.

---

## Вариант D — совсем без контейнеров (долго, но без Docker)

Работает, но требует поставить три вещи и руками поправить пути в конфигах.
Выбирай, только если контейнеры недоступны принципиально.

### D1. Что установить

| Зачем | Что | Ссылка |
|---|---|---|
| GraphHopper, Planetiler | Java 21 (Temurin) | https://adoptium.net/ |
| TileServer GL | Node.js 20 LTS | https://nodejs.org/ |
| бэкенд и зоны | Python 3.12 | https://www.python.org/downloads/ |

Проверка в PowerShell:

```powershell
java -version
node -v
npm -v
python --version
```

### D2. Данные и зоны

```powershell
curl.exe -L -o data/sevastopol.osm.pbf https://download.geofabrik.de/russia/crimean-fed-district-latest.osm.pbf
python -m pip install osmium shapely
python scripts/02-build-zones.py data/sevastopol.osm.pbf -o data/zones.geojson
```

### D3. Шрифты

```powershell
curl.exe -L -o fonts.zip https://github.com/openmaptiles/fonts/releases/download/v2.0/v2.0.zip
tar -xf fonts.zip -C data/fonts --strip-components=1
```

### D4. Тайлы (Planetiler)

```powershell
curl.exe -L -o planetiler.jar https://github.com/onthegomap/planetiler/releases/download/v0.10.2/planetiler.jar
java -Xmx4g -jar planetiler.jar --osm-path=data/sevastopol.osm.pbf --output=data/sevastopol.mbtiles --maxzoom=15 --bounds=33.30,44.28,33.85,44.78 --download --force
```

### D5. Поправить пути в конфигах

В контейнерах всё лежит в `/data`, на Windows этот путь надо заменить на
локальный. В двух файлах:

* `tiles/config.json` — три пути `"/data"` → `"C:/путь/до/alive-maps-service/data"`
* `graphhopper/config.yml` — `/data/sevastopol.osm.pbf` и `/data/graph-cache`

### D6. Запустить четыре процесса (каждый в своём окне)

```powershell
# 1) тайлы + шрифты
npm install -g tileserver-gl
tileserver-gl --config tiles/config.json --port 8081

# 2) роутер (в отдельном окне)
curl.exe -L -o graphhopper.jar https://github.com/graphhopper/graphhopper/releases/download/11.1/graphhopper-web-11.1.jar
java -Xmx2g -jar graphhopper.jar server graphhopper/config.yml

# 3) бэкенд (в третьем окне)
cd backend
pip install -r requirements.txt
$env:GH_URL="http://localhost:8989"; $env:TS_URL="http://localhost:8081"; $env:ZONES_FILE="$PWD/../data/zones.geojson"; $env:STYLE_FILE="$PWD/../tiles/style.json"
uvicorn app.main:app --port 8080
```

Открыть http://localhost:8080.

> Этот вариант в песочнице не проверялся: у него больше ручных шагов и
> правок путей. Если Docker недоступен, **вариант C** обычно проще.

---

## Проверка, что всё поднялось

Открой в браузере:

```
http://localhost:8080/health         → {"ok": true, "zones": 87}
http://localhost:8080/api/health     → состояние GraphHopper
http://localhost:8080/api/config     → сколько зон загружено
```

Внизу панели интерфейса есть строка статуса, например:

```
зон: 87 · GraphHopper живой · тайлы на месте
```

Если там «GraphHopper не отвечает» — он ещё импортирует граф (первый
запуск) либо упал: `docker compose logs graphhopper`.

---

## Частые проблемы

| Симптом | Причина | Что делать |
|---|---|---|
| `'docker' не является внутренней командой` | Docker не установлен или нет перезагрузки | установить, перезагрузиться |
| `error during connect` / `Engine stopped` | Docker Desktop не запущен | запустить, дождаться «Engine running» |
| `docker compose up` падает на `pull access denied` | нет интернета или недоступен Docker Hub | проверить сеть/VPN |
| Сборка тайлов падает по памяти | мало RAM для Planetiler | в `.env` поставить `PLANETILER_MEMORY=2g`, закрыть браузер |
| Порт 8080 занят | что-то уже слушает 8080 | в `.env` поставить `PORT=8090`, в браузере `localhost:8090` |
| Карта пустая, без улиц | нет тайлов | `make tiles` (или шаг D4), проверить `data/sevastopol.mbtiles` |
| Карта без подписей | нет шрифтов | `make fonts`, затем `docker compose restart tileserver` |
| `alive` не отличается от `fast` | зоны не собраны или ползунок на 0 | `make zones`, проверить `/api/config` |
| Долго «Жду GraphHopper» | импорт графа на слабом диске | подождать до 10 минут, смотреть `docker compose logs -f graphhopper` |

Логи всех сервисов: `docker compose logs -f`
(в Podman: `podman compose logs -f`).

Остановить: `docker compose down`. Данные остаются в папке `data/`.

---

## Ссылки

| Что | Адрес |
|---|---|
| Репозиторий | https://github.com/Yurich-citycode/SevastopolAIbot |
| Папка сервиса | https://github.com/Yurich-citycode/SevastopolAIbot/tree/arena/8d598d96-sevastopolaibot/alive-maps-service |
| README сервиса (архитектура, API) | https://github.com/Yurich-citycode/SevastopolAIbot/blob/arena/8d598d96-sevastopolaibot/alive-maps-service/README.md |
| Эта инструкция | https://github.com/Yurich-citycode/SevastopolAIbot/blob/arena/8d598d96-sevastopolaibot/alive-maps-service/SETUP.md |
| Архив для скачивания | https://github.com/Yurich-citycode/SevastopolAIbot/archive/refs/tags/alive-maps-service-v1.4.zip |
| Одиночный HTML-демо (без установки) | https://cdn.jsdelivr.net/gh/Yurich-citycode/SevastopolAIbot@alive-maps-v0.5/alive-maps.html |
