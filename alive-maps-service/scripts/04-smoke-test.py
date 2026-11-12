#!/usr/bin/env python3
"""Быстрая проверка сервиса БЕЗ Docker и без сети.

Подменяет GraphHopper заглушкой и прогоняет весь путь запроса:
конфиг → зоны → compare → route → валидация → стиль → статика.

Запуск (из корня сервиса):
    pip install -r scripts/requirements.txt fastapi httpx
    python scripts/04-smoke-test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

# синтетические зоны: парк, кафе, набережная — рядом с тестовым маршрутом
ZONES = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"kind": "park", "name": "Тестовый сквер"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[33.5185, 44.6095], [33.5205, 44.6095],
                                 [33.5205, 44.6105], [33.5185, 44.6105], [33.5185, 44.6095]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"kind": "waterfront", "name": None},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[33.5215, 44.6098], [33.5228, 44.6098],
                                 [33.5228, 44.6102], [33.5215, 44.6102], [33.5215, 44.6098]]],
            },
        },
    ],
    "pois": [{"kind": "cafe", "name": "Кофейня «Тест»", "lon": 33.5210, "lat": 44.6100}],
}

# мои точки из «базы»: одна прямо на маршруте, одна далеко
MY_POIS = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"name": "Моя кофейня", "kind": "cafe", "category": "Кофе",
                           "weight": 1.3},
            "geometry": {"type": "Point", "coordinates": [33.5198, 44.6100]},
        },
        {
            "type": "Feature",
            "properties": {"name": "Мой музей", "kind": "historic", "category": "Музеи",
                           "weight": 1.45},
            "geometry": {"type": "Point", "coordinates": [33.5300, 44.6120]},
        },
    ],
}

tmp = Path(tempfile.mkdtemp(prefix="alive-smoke-"))
zones_file = tmp / "zones.geojson"
zones_file.write_text(json.dumps(ZONES), encoding="utf-8")
pois_file = tmp / "pois.geojson"
pois_file.write_text(json.dumps(MY_POIS, ensure_ascii=False), encoding="utf-8")

os.environ["ZONES_FILE"] = str(zones_file)
os.environ["POIS_FILE"] = str(pois_file)
os.environ["STYLE_FILE"] = str(ROOT / "tiles" / "style.json")
os.environ["CACHE_TTL"] = "0"

failures: list[str] = []
calls: list[dict] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    mark = "✓" if condition else "✗"
    print(f"  {mark} {name:<42} {detail}")
    if not condition:
        failures.append(name)


def main() -> int:
    from fastapi.testclient import TestClient

    from app import gh
    from app.main import app

    async def fake_route(client, start, end, mode, areas=None, rules=None, strength=1.0):
        calls.append({"mode": mode, "areas": len((areas or {}).get("features", [])),
                      "rules": len(rules or [])})
        mid = [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2]
        fast = mode == "fast"
        return gh.Route(mode=mode, coordinates=[start, mid, end],
                        distance_m=1000 if fast else 1240,
                        time_s=600 if fast else 668)

    gh.route = fake_route  # подмена движка

    with TestClient(app) as client:
        print("здоровье и конфиг")
        check("GET /health", client.get("/health").status_code == 200)
        cfg = client.get("/api/config").json()
        check("центр карты", cfg["center"] == [33.5225, 44.6134], cfg["center"])
        check("зоны загружены", cfg["zones"]["count"] == 2, cfg["zones"]["by_kind"])
        check("мои точки загружены", cfg["own"]["count"] == 2, cfg["own"]["by_kind"])

        print("маршруты")
        req = {"start": [33.5170, 44.6100], "end": [33.5235, 44.6100]}
        resp = client.post("/api/compare", json=req)
        check("POST /api/compare", resp.status_code == 200, resp.status_code)
        data = resp.json()
        check("fast — геометрия LineString",
              data["fast"]["geojson"]["geometry"]["type"] == "LineString")
        check("fast без custom model", calls[0]["areas"] == 0, calls[0])
        check("alive с areas (2 зоны + 2 мои)", calls[1]["areas"] == 4, calls[1])
        check("bonus — парк с названием",
              any(b.get("name") == "Тестовый сквер" for b in data["alive"]["bonuses"]),
              [b.get("name") for b in data["alive"]["bonuses"]])
        check("bonus — кафе рядом", any(b.get("kind") == "cafe" for b in data["alive"]["bonuses"]))
        check("delta посчитан", data["delta"]["distance_m"] == 240, data["delta"])
        check("три варианта маршрута", {"fast", "alive", "most_alive"} <= set(data), list(data)[:6])
        check("балл живости 0..100",
              all(0 <= data[k]["score"]["score"] <= 100 for k in ("fast", "alive", "most_alive")),
              {k: data[k]["score"]["score"] for k in ("fast", "alive", "most_alive")})
        check("живой не хуже быстрого по баллу",
              data["alive"]["score"]["score"] >= data["fast"]["score"]["score"])
        check("разбивка по категориям",
              any(item["key"] == "park" and item["percent"] > 0 for item in data["alive"]["score"]["breakdown"]),
              data["alive"]["score"]["breakdown"])
        check("живой уложился в +15%", data["alive"]["time_s"] <= data["fast"]["time_s"] * 1.15 + 180,
              data["delta"]["time_min"])
        check("delta_most посчитан", "time_min" in data["delta_most"])
        check("моя точка в объяснении",
              any(b.get("own") for b in data["alive"]["bonuses"]),
              [b.get("name") for b in data["alive"]["bonuses"]])

        print("режимы и валидация")
        zero = client.post("/api/route", json={**req, "mode": "alive", "strength": 0})
        check("strength=0 → без зон", zero.status_code == 200 and calls[-1]["areas"] == 0, calls[-1])
        out = client.post("/api/route", json={"start": [10.0, 10.0], "end": [33.52, 44.61],
                                              "mode": "alive"})
        check("точка вне карты → 400", out.status_code == 400, out.json().get("detail"))

        print("стиль, зоны, статика")
        style = client.get("/style.json")
        check("GET /style.json", style.status_code == 200 and "layers" in style.json())
        check("GET /api/zones", len(client.get("/api/zones").json()["features"]) == 2)
        pois = client.get("/api/pois").json()
        check("GET /api/pois", len(pois["features"]) == 2)
        png = client.get("/api/compare.png",
                         params={"from": "44.6090,33.5185", "to": "44.6105,33.5215"})
        check("GET /api/compare.png", png.status_code == 200
              and png.content.startswith(b"\x89PNG"), f"{len(png.content)} байт")
        bad = client.get("/api/compare.png", params={"from": "ой", "to": "44.6,33.5"})
        check("png: кривые координаты → 400", bad.status_code == 400)
        index = client.get("/")
        check("index.html", index.status_code == 200 and "maplibre-gl.js" in index.text)
        check("вендоренный MapLibre", client.get("/static/vendor/maplibre-gl.js").status_code == 200)

    print()
    if failures:
        print(f"✗ провалено: {len(failures)} — {', '.join(failures)}")
        return 1
    print("✓ всё зелёное: конфиг, зоны, мои точки, маршруты, картинка, статика")
    return 0


if __name__ == "__main__":
    sys.exit(main())
