"""Мои собственные точки на карте: кафе, пляжи, музеи, смотровые.

Отличие от «живых зон» (zones.py): зоны приходят из OpenStreetMap и есть у всех,
а эти точки — из моей базы, с моими названиями и моими оценками. Поэтому
маршрут, который проходит мимо «Кофе в Окнах» или моего пляжа, получает
надбавку, которой нет ни у кого другого.

Файл готовит tools/export_pois.py из «Sevastopol AI База.xlsx».
Формат — обычный GeoJSON с Point-фичами:

    {"type": "Feature", "properties": {"name": "...", "kind": "cafe",
     "weight": 1.3}, "geometry": {...}}
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from shapely.geometry import LineString, Point, mapping, shape

from .zones import KIND_RU

# радиус, в котором точка делает улицу «живой» (метры)
RADIUS_M: dict[str, float] = {
    "cafe": 55,
    "historic": 70,
    "waterfront": 140,
    "park": 160,
    "lively": 60,
}

# как называть мои точки в объяснении маршрута
OWN_KIND_RU: dict[str, str] = {
    "cafe": "моё кафе",
    "historic": "моё место",
    "waterfront": "мой вид",
    "park": "моя прогулка",
    "lively": "моя находка",
}

# больше полигонов GraphHopper за один запрос не переварит
MAX_AREAS = 140

METERS_PER_DEG = 111_000.0


class Pois:
    """Загруженные POI + операции: areas для GraphHopper и объяснение маршрута."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mtime: float = 0.0
        self._items: list[dict[str, Any]] = []
        self._error: str | None = None

    # ---------- загрузка ----------

    def reload(self, path: str) -> None:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            with self._lock:
                self._items = []
                self._error = f"нет файла {path} (собери: python tools/export_pois.py)"
                self._mtime = 0.0
            return

        with self._lock:
            if mtime == self._mtime:
                return
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError) as exc:
                self._items = []
                self._error = f"не читается {path}: {exc}"
                self._mtime = mtime
                return

            items: list[dict[str, Any]] = []
            for feat in data.get("features", []):
                geom = feat.get("geometry") or {}
                props = feat.get("properties") or {}
                if geom.get("type") != "Point":
                    continue
                try:
                    point = shape(geom)
                except Exception:  # noqa: BLE001 — битую точку просто пропускаем
                    continue
                if point.is_empty:
                    continue
                kind = str(props.get("kind") or "cafe")
                try:
                    weight = float(props.get("weight") or 1.2)
                except (TypeError, ValueError):
                    weight = 1.2
                items.append({
                    "name": props.get("name"),
                    "kind": kind,
                    "category": props.get("category"),
                    "weight": max(1.0, min(weight, 2.0)),
                    "point": point,
                })

            self._items = items
            self._error = None
            self._mtime = mtime

    # ---------- состояние ----------

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def count(self) -> int:
        return len(self._items)

    def by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in self._items:
            out[item["kind"]] = out.get(item["kind"], 0) + 1
        return out

    def geojson(self) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "name": item["name"],
                        "kind": item["kind"],
                        "kind_ru": OWN_KIND_RU.get(item["kind"], item["kind"]),
                        "category": item["category"],
                        "weight": item["weight"],
                    },
                    "geometry": mapping(item["point"]),
                }
                for item in self._items
            ],
        }

    # ---------- Custom Model ----------

    def areas_and_rules(
        self, strength: float = 1.0, max_areas: int = MAX_AREAS
    ) -> tuple[dict, list[dict]]:
        """Круги вокруг моих точек + правила приоритета.

        Круги маленькие (55–160 м), поэтому они не «съедают» маршрут целиком,
        а просто делают ближайшую улицу чуть приятнее.
        """
        if not self._items:
            return {"type": "FeatureCollection", "features": []}, []

        # сначала самые «сильные» точки: их и в лимит влезет больше
        items = sorted(
            self._items,
            key=lambda item: (item["weight"], RADIUS_M.get(item["kind"], 60)),
            reverse=True,
        )[:max_areas]

        features: list[dict] = []
        rules: list[dict] = []
        for idx, item in enumerate(items):
            radius_deg = RADIUS_M.get(item["kind"], 60) / METERS_PER_DEG
            circle = item["point"].buffer(radius_deg, quad_segs=8)
            area_id = f"own_{idx}"
            multiply = 1.0 + (item["weight"] - 1.0) * strength
            features.append({
                "type": "Feature",
                "id": area_id,
                "properties": {},
                "geometry": mapping(circle),
            })
            rules.append({"if": f"in_{area_id}", "multiply_by": f"{multiply:.2f}"})

        return {"type": "FeatureCollection", "features": features}, rules

    # ---------- объяснение маршрута ----------

    def explain(self, coordinates: list[list[float]], buffer_deg: float = 0.00055) -> list[dict]:
        """Мои точки рядом с маршрутом: «мимо “Кофе в Окнах”»."""
        if len(coordinates) < 2 or not self._items:
            return []
        line = LineString([(float(x), float(y)) for x, y in coordinates])
        corridor = line.buffer(buffer_deg)

        found: list[dict] = []
        for item in self._items:
            if not corridor.contains(item["point"]):
                continue
            distance_deg = line.distance(item["point"])
            found.append({
                "kind": item["kind"],
                "kind_ru": OWN_KIND_RU.get(item["kind"], item["kind"]),
                "name": item["name"],
                "meters": 0,
                "distance_m": round(distance_deg * METERS_PER_DEG),
                "own": True,
            })

        found.sort(key=lambda item: item["distance_m"])
        return found[:6]


def kind_ru(kind: str) -> str:
    """Подпись типа точки для интерфейса."""
    return OWN_KIND_RU.get(kind) or KIND_RU.get(kind, kind)


POIS = Pois()
