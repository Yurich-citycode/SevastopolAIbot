#!/usr/bin/env python3
"""Экспорт моей базы в POI для живой карты.

Берёт «Sevastopol AI База.xlsx» (листы «Где поесть» и «Локации»), вытаскивает
название, категорию и координаты и кладёт рядом с сервисом в
data/pois.geojson. Дальше сервис сам подмешивает эти точки в «живость»:
маршрут охотнее идёт мимо моих кофеен, пляжей и музеев, а не мимо
безымянных кафе из OSM.

Запуск (на машине, где лежит база, Docker не нужен):

    python tools/export_pois.py
    python tools/export_pois.py --xlsx "путь/к/базе.xlsx" --out data/pois.geojson
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    sys.exit("нужен pandas: python -m pip install pandas openpyxl")

# во что превращается категория из таблицы
KIND_BY_CATEGORY: dict[str, str] = {
    # «Где поесть»
    "Кофе": "cafe",
    "Кондитерские": "cafe",
    "Рестораны": "cafe",
    "Кафе": "cafe",
    "Пекарни": "cafe",
    "Доставки": "cafe",
    # «Локации»
    "Пляжи": "waterfront",
    "Смотровые": "waterfront",
    "Закаты": "waterfront",
    "Достопримечательности": "historic",
    "Музеи": "historic",
    "Прогулки": "park",
    "Hidden Gems": "lively",
}

# насколько сильно тянуть маршрут к такой точке (1.0 — не тянуть)
WEIGHT_BY_KIND: dict[str, float] = {
    "cafe": 1.30,
    "waterfront": 1.60,
    "historic": 1.45,
    "park": 1.55,
    "lively": 1.20,
}

# листы базы: (лист, есть ли колонка «Адрес»)
SHEETS = ("Где поесть", "Локации")


def parse_coords(value) -> tuple[float, float] | None:
    """«44.610761, 33.542573» → (lat, lon)."""
    if value is None:
        return None
    text = str(value).replace(";", ",").strip()
    if "," not in text:
        return None
    left, right = text.split(",", 1)
    try:
        lat = float(left.strip().replace(",", "."))
        lon = float(right.strip().replace(",", "."))
    except ValueError:
        return None
    # на всякий случай: в базе порядок «широта, долгота»
    if not (30 < lon < 40 and 43 < lat < 46):
        return None
    return lat, lon


def collect(xlsx: Path) -> list[dict]:
    pois: list[dict] = []
    seen: set[tuple[str, float, float]] = set()

    for sheet in SHEETS:
        try:
            df = pd.read_excel(xlsx, sheet_name=sheet)
        except ValueError:
            print(f"  пропускаю лист «{sheet}» — его нет", file=sys.stderr)
            continue

        for _, row in df.iterrows():
            name = str(row.get("Название") or "").strip()
            category = str(row.get("Категория") or "").strip()
            if not name or name.lower() == "nan":
                continue
            coords = parse_coords(row.get("Координаты"))
            if not coords:
                continue
            lat, lon = coords

            kind = KIND_BY_CATEGORY.get(category)
            if not kind:
                continue

            key = (name.lower(), round(lat, 5), round(lon, 5))
            if key in seen:
                continue
            seen.add(key)

            pois.append({
                "name": name,
                "kind": kind,
                "category": category,
                "sheet": sheet,
                "weight": WEIGHT_BY_KIND.get(kind, 1.2),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
            })

    return pois


def to_geojson(pois: list[dict]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": poi["name"],
                    "kind": poi["kind"],
                    "category": poi["category"],
                    "sheet": poi["sheet"],
                    "weight": poi["weight"],
                    "source": "base",
                },
                "geometry": {"type": "Point", "coordinates": [poi["lon"], poi["lat"]]},
            }
            for poi in pois
        ],
    }


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="база → data/pois.geojson")
    parser.add_argument("--xlsx", default=str(root / "Sevastopol AI База.xlsx"))
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "data" / "pois.geojson"),
    )
    args = parser.parse_args()

    xlsx = Path(args.xlsx)
    if not xlsx.exists():
        sys.exit(f"нет файла базы: {xlsx}")

    pois = collect(xlsx)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(to_geojson(pois), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    by_kind: dict[str, int] = {}
    for poi in pois:
        by_kind[poi["kind"]] = by_kind.get(poi["kind"], 0) + 1
    print(f"готово: {len(pois)} точек → {out}")
    for kind, count in sorted(by_kind.items(), key=lambda p: -p[1]):
        print(f"  {kind}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
