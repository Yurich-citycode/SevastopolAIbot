# Sevastopol Alive Maps — короткие команды вместо длинных.
# Всё, что нужно: make data → make tiles → make up

DATA_DIR ?= data
PY ?= python3

.PHONY: help data zones fonts tiles up down logs ps clean check smoke

help:
	@echo "Sevastopol Alive Maps"
	@echo ""
	@echo "  make data    скачать OSM-данные Крыма/Севастополя (≈39 МБ)"
	@echo "  make zones   собрать живые зоны (парки/кафе/набережные) из PBF"
	@echo "  make fonts   скачать шрифты для подписей на карте"
	@echo "  make tiles   собрать тайлы через Planetiler (mbtiles)"
	@echo "  make up      поднять весь стек: http://localhost:8080"
	@echo "  make down    остановить"
	@echo "  make logs    логи всех сервисов"
	@echo "  make check   проверить конфиги и код без запуска"
	@echo "  make smoke   прогнать API через тестовый клиент (без Docker)"
	@echo ""
	@echo "  первый запуск:  make data zones fonts tiles && make up"

data:
	bash scripts/01-fetch-pbf.sh

zones:
	$(PY) -m pip install -q -r scripts/requirements.txt
	$(PY) scripts/02-build-zones.py $(DATA_DIR)/sevastopol.osm.pbf -o $(DATA_DIR)/zones.geojson

fonts:
	bash scripts/03-fetch-fonts.sh

tiles:
	@test -f $(DATA_DIR)/sevastopol.osm.pbf || (echo "сначала make data" && exit 1)
	docker compose run --rm planetiler

up:
	docker compose up --build -d
	@echo "→ http://localhost:8080"

down:
	docker compose down

logs:
	docker compose logs -f --tail=120

ps:
	docker compose ps

clean:
	docker compose down -v --remove-orphans

# быстрая проверка без Docker: json/yaml/py-синтаксис
check:
	$(PY) -c "import yaml" 2>/dev/null || $(PY) -m pip install -q pyyaml
	$(PY) -c "import json;[json.load(open(f,encoding='utf-8')) for f in ['tiles/style.json','tiles/config.json']];print('json ok')"
	$(PY) -c "import yaml;yaml.safe_load(open('docker-compose.yml',encoding='utf-8'));yaml.safe_load(open('graphhopper/config.yml',encoding='utf-8'));print('yaml ok')"
	$(PY) -m compileall -q backend/app scripts && echo "python ok"

# проверка API без Docker: подменяет GraphHopper заглушкой
smoke:
	$(PY) -c "import fastapi, httpx, shapely" 2>/dev/null || $(PY) -m pip install -q fastapi httpx shapely
	$(PY) scripts/04-smoke-test.py
