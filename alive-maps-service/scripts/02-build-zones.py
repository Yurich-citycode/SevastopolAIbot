#!/usr/bin/env python3
"""Собирает «живые зоны» Севастополя из OSM в data/zones.geojson.

Что считается жизнью:

    park        парки, скверы, бульвары, лесопарки          → полигоны как есть
    waterfront  полоса вдоль воды (море, бухты, набережные) → буфер береговой линии
    historic    памятники, музеи, крепости, руины           → буферы вокруг POI
    cafe        кафе, рестораны, бары, рынки                → объединённые буферы
    lively      аттракционы, театры, площади                → объединённые буферы

Полигоны идут в GraphHopper как `areas` (он принимает только Polygon),
а именованные точки — в блок `pois`, чтобы бэкенд мог объяснить маршрут
словами: «прошёл мимо кафе X».

Запуск:  python scripts/02-build-zones.py data/sevastopol.osm.pbf
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

BBOX = (33.30, 44.28, 33.85, 44.78)  # min_lon, min_lat, max_lon, max_lat

PARK_LEISURE = {
    "park", "garden", "nature_reserve", "common", "recreation_ground",
    "playground", "pitch", "stadium", "dog_park",
}
PARK_LANDUSE = {"recreation_ground", "forest", "grass", "village_green", "meadow", "orchard"}
WATER_NATURAL = {"water", "bay", "strait", "wetland"}
WATER_LANDUSE = {"reservoir", "basin"}

LIVELY_AMENITY = {
    "cafe", "restaurant", "bar", "pub", "fast_food", "food_court", "ice_cream",
    "biergarten", "marketplace", "theatre", "cinema", "arts_centre", "nightclub",
}
LIVELY_TOURISM = {"attraction", "museum", "gallery", "viewpoint", "zoo", "theme_park", "artwork"}
HISTORIC = {
    "monument", "memorial", "castle", "ruins", "archaeological_site", "fort",
    "citywalls", "tower", "battlefield", "memorial_plaque", "yes",
}

# радиусы влияния, в градусах (1° широты ≈ 111 км)
BUFFER_CAFE = 0.0010      # ~110 м — «улица, где есть жизнь»
BUFFER_HIST = 0.0007      # ~78 м
BUFFER_LIVELY = 0.0009
BUFFER_WATER = 0.00055    # ~60 м — полоса вдоль берега

MIN_AREA_DEG2 = 2.0e-8    # ~250 м², мельче — мусор

try:
    import osmium
    from shapely.geometry import Point, Polygon, box, mapping, shape
    from shapely.ops import unary_union
except ImportError as exc:  # pragma: no cover
    sys.exit(
        f"не хватает зависимостей: {exc}\n"
        "поставь их:  pip install -r scripts/requirements.txt"
    )


def log(msg: str) -> None:
    print(msg, flush=True)


class Collector:
    """Обходит OSM и раскладывает найденное по типам зон."""

    def __init__(self) -> None:
        self.polygons: dict[str, list[tuple[Polygon, str | None]]] = defaultdict(list)
        self.water: list[Polygon] = []
        self.pois: dict[str, list[dict]] = defaultdict(list)

    # ---------- узлы ----------
    def add_node(self, lon: float, lat: float, tags) -> None:
        if not (BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]):
            return
        name = tags.get("name") or tags.get("name:ru")
        amenity = tags.get("amenity")
        tourism = tags.get("tourism")
        historic = tags.get("historic")

        if amenity in LIVELY_AMENITY:
            kind = "cafe" if amenity in ("cafe", "restaurant", "bar", "pub", "fast_food",
                                         "food_court", "ice_cream", "biergarten") else "lively"
            self.pois[kind].append({"kind": kind, "name": name, "lon": lon, "lat": lat})
        elif tourism in LIVELY_TOURISM:
            kind = "historic" if tourism in ("museum", "gallery", "artwork") else "lively"
            self.pois[kind].append({"kind": kind, "name": name, "lon": lon, "lat": lat})
        elif historic in HISTORIC:
            self.pois["historic"].append({"kind": "historic", "name": name, "lon": lon, "lat": lat})

    # ---------- площади ----------
    def add_area(self, geometry, tags) -> None:
        leisure = tags.get("leisure")
        landuse = tags.get("landuse")
        natural = tags.get("natural")
        name = tags.get("name") or tags.get("name:ru")

        if leisure in PARK_LEISURE or landuse in PARK_LANDUSE or tags.get("place") == "square":
            self.polygons["park"].append((geometry, name))
        elif natural in WATER_NATURAL or landuse in WATER_LANDUSE or tags.get("waterway") == "riverbank":
            self.water.append(geometry)
        elif tags.get("man_made") == "pier" or leisure == "marina":
            self.polygons["waterfront"].append((geometry.buffer(BUFFER_WATER), name))


def read_osm(path: str) -> Collector:
    col = Collector()
    factory = osmium.geom.GeoJSONFactory()

    fp = osmium.FileProcessor(path).with_locations().with_areas()
    areas = nodes = 0

    for obj in fp:
        try:
            if isinstance(obj, osmium.osm.Node):
                loc = obj.location
                if loc.valid():
                    nodes += 1
                    col.add_node(loc.lon, loc.lat, obj.tags)
            elif isinstance(obj, osmium.osm.Area):
                geojson = factory.create_multipolygon(obj)
                if not geojson:
                    continue
                geom = shape(json.loads(geojson))
                if geom.is_empty or geom.area <= 0:
                    continue
                areas += 1
                col.add_area(geom, obj.tags)
        except Exception:  # noqa: BLE001 — битые объекты OSM не должны ломать сборку
            continue

    log(f"  прочитано: {nodes} узлов, {areas} площадей")
    return col


def finalize(col: Collector) -> dict:
    """Склеивает буферы, режет по bbox и собирает FeatureCollection."""
    clip = box(*BBOX)
    features: list[dict] = []

    def push(kind: str, geom, name: str | None) -> None:
        if geom.is_empty:
            return
        geom = geom.intersection(clip)
        if geom.is_empty:
            return
        parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        for part in parts:
            if part.geom_type != "Polygon" or part.area < MIN_AREA_DEG2:
                continue
            simplified = part.simplify(0.00002, preserve_topology=True)
            if simplified.is_empty or simplified.geom_type != "Polygon":
                continue
            features.append({
                "type": "Feature",
                "properties": {"kind": kind, "name": name},
                "geometry": mapping(simplified),
            })

    # парки — по отдельности, чтобы сохранить названия
    for geom, name in col.polygons.get("park", []):
        push("park", geom, name)
    log(f"  парки: {sum(1 for f in features if f['properties']['kind'] == 'park')}")

    # кафе/история/людные места — объединённые буферы вокруг POI
    buffers = {
        "cafe": (BUFFER_CAFE, "cafe"),
        "historic": (BUFFER_HIST, "historic"),
        "lively": (BUFFER_LIVELY, "lively"),
    }
    for kind, (radius, poi_kind) in buffers.items():
        geoms = [Point(p["lon"], p["lat"]).buffer(radius) for p in col.pois.get(poi_kind, [])]
        if not geoms:
            continue
        merged = unary_union(geoms)
        before = len(features)
        push(kind, merged, None)
        log(f"  {kind}: {len(col.pois[poi_kind])} точек → {len(features) - before} полигонов")

    # вода: полоса вдоль береговой линии
    if col.water:
        shore = unary_union(col.water).boundary.buffer(BUFFER_WATER)
        before = len(features)
        push("waterfront", shore, None)
        log(f"  waterfront: полоса вдоль воды → {len(features) - before} полигонов")
    for geom, name in col.polygons.get("waterfront", []):
        push("waterfront", geom, name)

    pois: list[dict] = []
    for kind, items in col.pois.items():
        for item in items:
            if item["name"]:
                pois.append(item)

    result = {
        "type": "FeatureCollection",
        "metadata": {
            "bbox": list(BBOX),
            "generated_from": os.path.basename(sys.argv[1]) if len(sys.argv) > 1 else "osm",
            "kinds": sorted({f["properties"]["kind"] for f in features}),
            "count": len(features),
        },
        "features": features,
        "pois": pois,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Собирает живые зоны Севастополя из OSM")
    parser.add_argument("pbf", nargs="?", default="data/sevastopol.osm.pbf")
    parser.add_argument("-o", "--out", default="data/zones.geojson")
    args = parser.parse_args()

    if not os.path.exists(args.pbf):
        sys.exit(f"нет файла данных {args.pbf} — сначала: make data")

    log(f"→ читаю {args.pbf}")
    col = read_osm(args.pbf)
    log("→ собираю полигоны")
    data = finalize(col)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)

    by_kind: dict[str, int] = defaultdict(int)
    for feat in data["features"]:
        by_kind[feat["properties"]["kind"]] += 1

    log(f"✓ {args.out}: {len(data['features'])} полигонов, {len(data['pois'])} подписанных точек")
    log("  " + ", ".join(f"{k}: {v}" for k, v in sorted(by_kind.items())))
    log("  дальше: make tiles && docker compose up --build")


if __name__ == "__main__":
    main()
