"""«Живые зоны»: GeoJSON-полигоны, которые делают улицу приятнее.

Зоны готовит scripts/02-build-zones.py из OSM: парки, набережные, кафе,
историческая архитектура. Здесь мы:
  * читаем файл зон (и перечитываем, если он изменился);
  * превращаем его в `areas` для Custom Model GraphHopper (там допустимы только Polygon);
  * умеем объяснить готовый маршрут: через какие зоны он прошёл и сколько метров.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import unary_union

# во сколько раз зона повышает приоритет улицы (1.0 = без изменений)
KIND_BONUS: dict[str, float] = {
    "park": 1.80,        # парки, скверы, бульвары
    "waterfront": 1.70,  # набережные, море, бухты
    "historic": 1.60,    # памятники, музеи, старая архитектура
    "cafe": 1.45,        # улицы с кафе и ресторанами
    "lively": 1.30,      # прочая городская жизнь: рынки, театры, площади
}

KIND_RU: dict[str, str] = {
    "park": "парк",
    "waterfront": "набережная",
    "historic": "историческое место",
    "cafe": "улица с кафе",
    "lively": "людное место",
}

# сколько полигонов максимум отдаём GraphHopper в одном запросе
MAX_AREAS = 220


class Zones:
    """Загруженный набор зон + операции над ним."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mtime: float = 0.0
        self._features: list[dict[str, Any]] = []   # только Polygon
        self._shapes: list[tuple[Any, str, str | None]] = []  # (geometry, kind, name)
        self._pois: list[dict[str, Any]] = []       # именованные точки для объяснений
        self._error: str | None = None

    # ---------- загрузка ----------

    def reload(self, path: str) -> None:
        """Читает файл зон. Разбивает MultiPolygon на отдельные Polygon."""
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            with self._lock:
                self._features, self._shapes, self._pois = [], [], []
                self._error = f"нет файла {path}"
                self._mtime = 0.0
            return

        with self._lock:
            if mtime == self._mtime:
                return
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError) as exc:
                self._features, self._shapes, self._pois = [], [], []
                self._error = f"не читается {path}: {exc}"
                self._mtime = mtime
                return

            features: list[dict[str, Any]] = []
            shapes: list[tuple[Any, str, str | None]] = []
            for feat in data.get("features", []):
                geom = feat.get("geometry") or {}
                props = feat.get("properties") or {}
                kind = str(props.get("kind") or "lively")
                name = props.get("name")
                try:
                    shp = shape(geom)
                except Exception:  # noqa: BLE001 — битую геометрию просто пропускаем
                    continue
                if shp.is_empty:
                    continue
                if shp.geom_type == "MultiPolygon":
                    parts = list(shp.geoms)
                elif shp.geom_type == "Polygon":
                    parts = [shp]
                else:
                    continue
                for part in parts:
                    if part.area <= 0:
                        continue
                    features.append({
                        "type": "Feature",
                        "properties": {"kind": kind, "name": name},
                        "geometry": mapping(part),
                    })
                    shapes.append((part, kind, name))

            pois: list[dict[str, Any]] = []
            for item in data.get("pois", []):
                try:
                    pois.append({
                        "kind": str(item.get("kind") or "lively"),
                        "name": item.get("name"),
                        "point": Point(float(item["lon"]), float(item["lat"])),
                    })
                except (KeyError, TypeError, ValueError):
                    continue

            self._features = features
            self._shapes = shapes
            self._pois = pois
            self._error = None
            self._mtime = mtime

    # ---------- состояние ----------

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def count(self) -> int:
        return len(self._features)

    def by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for feat in self._features:
            kind = feat["properties"]["kind"]
            out[kind] = out.get(kind, 0) + 1
        return out

    def geojson(self) -> dict[str, Any]:
        return {"type": "FeatureCollection", "features": self._features}

    # ---------- Custom Model ----------

    def areas_and_rules(self, strength: float = 1.0, max_areas: int = MAX_AREAS) -> tuple[dict, list[dict]]:
        """Возвращает (FeatureCollection для custom_model.areas, правила priority).

        GraphHopper принимает в areas только Polygon, поэтому мультиполигоны
        заранее разбиты на части, а id выглядят как `park_7` / `cafe_3`.
        Ссылка на зону в условиях — `in_<id>`.

        Слоты делим по типам зон поровну: иначе большие парки вытеснили бы
        все кафе, и «живой» маршрут перестал бы заходить в городскую жизнь.
        """
        by_kind: dict[str, list[tuple[float, dict]]] = {}
        for feat in self._features:
            kind = feat["properties"]["kind"]
            area = shape(feat["geometry"]).area
            by_kind.setdefault(kind, []).append((area, feat))

        if not by_kind:
            return {"type": "FeatureCollection", "features": []}, []

        per_kind = max(15, max_areas // len(by_kind))

        features: list[dict] = []
        rules: list[dict] = []
        for kind in sorted(by_kind, key=lambda k: -KIND_BONUS.get(k, 1.2)):
            items = sorted(by_kind[kind], key=lambda pair: pair[0], reverse=True)[:per_kind]
            bonus = KIND_BONUS.get(kind, 1.2)
            multiply = 1.0 + (bonus - 1.0) * strength
            for idx, (_, feat) in enumerate(items):
                area_id = f"{kind}_{idx}"
                features.append({
                    "type": "Feature",
                    "id": area_id,
                    "properties": {},
                    "geometry": feat["geometry"],
                })
                rules.append({"if": f"in_{area_id}", "multiply_by": f"{multiply:.2f}"})

        return {"type": "FeatureCollection", "features": features}, rules

    # ---------- объяснение маршрута ----------

    def explain(self, coordinates: list[list[float]], buffer_deg: float = 0.00023) -> list[dict]:
        """Что хорошего на маршруте: список пройденных зон с длиной в метрах."""
        if len(coordinates) < 2:
            return []
        line = LineString([(float(x), float(y)) for x, y in coordinates])
        corridor = line.buffer(buffer_deg)

        found: list[dict] = []
        for shp, kind, name in self._shapes:
            if not shp.intersects(corridor):
                continue
            part = line.intersection(shp.buffer(buffer_deg))
            meters = 0.0
            if not part.is_empty:
                # длина в градусах → примерно метры (на широте Севастополя 1° ≈ 111 км)
                meters = part.length * 111_000
            if meters < 20 and kind not in ("park", "waterfront"):
                continue
            found.append({
                "kind": kind,
                "kind_ru": KIND_RU.get(kind, kind),
                "name": name,
                "meters": round(meters),
            })

        # именованные точки рядом: «прошёл мимо кафе X»
        near = line.buffer(buffer_deg * 2)
        named: list[dict] = []
        for poi in self._pois:
            if near.contains(poi["point"]):
                named.append({
                    "kind": poi["kind"],
                    "kind_ru": KIND_RU.get(poi["kind"], poi["kind"]),
                    "name": poi["name"],
                    "meters": 0,
                })
        found = named[:8] + found

        # сначала крупные парки/набережные, потом всё остальное
        found.sort(key=lambda item: (item["kind"] not in ("park", "waterfront"), -item["meters"]))

        # убираем повторы одинаковых названий
        seen: set[tuple[str, str | None]] = set()
        unique: list[dict] = []
        for item in found:
            key = (item["kind"], item["name"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique[:12]


def merge_nearby(polygons: list[Any], tolerance: float = 0.00002) -> list[Any]:
    """Склеивает пересекающиеся буферы (используется в scripts/02-build-zones.py)."""
    if not polygons:
        return []
    merged = unary_union([poly.buffer(tolerance) for poly in polygons])
    return list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]


ZONES = Zones()
