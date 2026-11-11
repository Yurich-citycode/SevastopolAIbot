"""Настройки сервиса: всё через переменные окружения, дефолты — для docker compose."""

import os


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


# GraphHopper — движок маршрутов
GH_URL = _env("GH_URL", "http://localhost:8989")
GH_PROFILE = _env("GH_PROFILE", "foot")

# TileServer GL — наши тайлы и шрифты
TS_URL = _env("TS_URL", "http://localhost:8081")
TS_SOURCE = _env("TS_SOURCE", "sevastopol")

# Файлы
DATA_DIR = _env("DATA_DIR", "/data")
ZONES_FILE = _env("ZONES_FILE", os.path.join(DATA_DIR, "zones.geojson"))
# мои точки из базы (делает tools/export_pois.py)
POIS_FILE = _env("POIS_FILE", os.path.join(DATA_DIR, "pois.geojson"))
STYLE_FILE = _env("STYLE_FILE", "/tiles/style.json")

# Кэш готовых ответов (секунды); 0 — выключить
CACHE_TTL = int(_env("CACHE_TTL", "900"))

# Границы Севастополя — для проверки входных координат и подсказок фронтенду
BBOX = (33.30, 44.28, 33.85, 44.78)  # min_lon, min_lat, max_lon, max_lat
CENTER = (33.5225, 44.6134)
