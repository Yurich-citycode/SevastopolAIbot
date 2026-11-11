# Sevastopol Alive Maps — короткие команды.
# Всё делается через Docker: локальный Python/make не нужен (make — только удобство).
#
#   ./start.sh   (Windows: start.bat)  — то же самое одной командой

DC ?= docker compose
BUILD := $(DC) --profile build run --rm --build tools
DATA_DIR ?= data
PY ?= python3

.PHONY: help start data zones pois fonts tiles up down logs ps clean check smoke

help:
	@echo "Sevastopol Alive Maps"
	@echo ""
	@echo "  make start   всё сразу: данные → зоны → шрифты → тайлы → запуск"
	@echo "  make data    скачать OSM-данные Крыма/Севастополя (~39 МБ)"
	@echo "  make zones   собрать живые зоны (парки/кафе/набережные)"
	@echo "  make pois    мои точки из базы бота → data/pois.geojson"
	@echo "  make fonts   скачать шрифты для подписей"
	@echo "  make tiles   собрать тайлы (Planetiler, 3-10 мин)"
	@echo "  make up      поднять стек → http://localhost:8080"
	@echo "  make down    остановить"
	@echo "  make logs    логи"
	@echo "  make check   проверить конфиги без запуска"
	@echo "  make smoke   прогнать API тестом (без Docker)"

start:
	bash start.sh

# ---------- мои точки из базы бота (на машине, нужен pandas) ----------
pois:
	$(PY) tools/export_pois.py

# ---------- подготовка данных (в контейнере, локальный Python не нужен) ----------

data:
	@test -f $(DATA_DIR)/sevastopol.osm.pbf || $(BUILD) sh /scripts/01-fetch-pbf.sh

zones:
	$(BUILD) python /scripts/02-build-zones.py /data/sevastopol.osm.pbf -o /data/zones.geojson

fonts:
	@test -d $(DATA_DIR)/fonts || $(BUILD) sh /scripts/03-fetch-fonts.sh

tiles:
	@test -f $(DATA_DIR)/sevastopol.osm.pbf || (echo "сначала make data" && exit 1)
	$(DC) --profile build run --rm planetiler

# ---------- стек ----------

up:
	$(DC) up -d --build
	@echo "→ http://localhost:8080   (первый запуск: импорт графа 1-3 мин)"

down:
	$(DC) down

logs:
	$(DC) logs -f --tail=120

ps:
	$(DC) ps

clean:
	$(DC) down -v --remove-orphans

# ---------- проверки без Docker ----------

check:
	$(PY) -c "import yaml" 2>/dev/null || $(PY) -m pip install -q pyyaml
	$(PY) -c "import json;[json.load(open(f,encoding='utf-8')) for f in ['tiles/style.json','tiles/config.json']];print('json ok')"
	$(PY) -c "import yaml;yaml.safe_load(open('docker-compose.yml',encoding='utf-8'));yaml.safe_load(open('graphhopper/config.yml',encoding='utf-8'));print('yaml ok')"
	$(PY) -m compileall -q backend/app scripts && echo "python ok"

smoke:
	$(PY) -c "import fastapi, httpx, shapely" 2>/dev/null || $(PY) -m pip install -q fastapi httpx shapely
	$(PY) scripts/04-smoke-test.py
