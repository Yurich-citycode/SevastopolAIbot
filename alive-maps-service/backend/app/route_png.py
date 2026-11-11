"""Картинка маршрутов для бота: два пути на схематичной карте.

Зачем это здесь, а не в боте: бот не должен тащить Pillow и знать про
проекции — он просто просит `/api/compare.png` и отправляет фото.

Фон рисуется из тех же «живых зон», что и маршруты: парки, вода, историческая
застройка. Получается не пустая сетка, а узнаваемый силуэт города — и по нему
видно, куда именно свернул живой маршрут.
"""

from __future__ import annotations

import io
import math
import os
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import shape

BG = (13, 16, 19)
GRID = (26, 31, 37)
FAST = (154, 164, 178)
ALIVE = (182, 243, 107)
ALIVE_DARK = (24, 34, 20)
TEXT = (232, 236, 241)
MUTED = (150, 160, 172)

# цвет заливки для типов зон
ZONE_FILL = {
    "park": (47, 107, 58),
    "waterfront": (31, 79, 122),
    "historic": (122, 90, 42),
    "cafe": (122, 63, 90),
    "lively": (74, 63, 122),
}

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:  # Pillow >= 10.1 умеет размер у дефолтного шрифта
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover — старый Pillow
        return ImageFont.load_default()


class Projection:
    """Web Mercator: переводит lon/lat в пиксели картинки."""

    def __init__(self, bounds: tuple[float, float, float, float], size: tuple[int, int],
                 pad: int = 28) -> None:
        min_lon, min_lat, max_lon, max_lat = bounds
        width, height = size

        def merc(lon: float, lat: float) -> tuple[float, float]:
            lat = max(min(lat, 85.0), -85.0)
            x = (lon + 180.0) / 360.0
            rad = math.radians(lat)
            y = (1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0
            return x, y

        x0, y0 = merc(min_lon, max_lat)
        x1, y1 = merc(max_lon, min_lat)
        span_x = max(x1 - x0, 1e-9)
        span_y = max(y1 - y0, 1e-9)

        usable_w = max(width - 2 * pad, 10)
        usable_h = max(height - 2 * pad, 10)
        self.scale = min(usable_w / span_x, usable_h / span_y)
        self.offset_x = (width - span_x * self.scale) / 2.0
        self.offset_y = (height - span_y * self.scale) / 2.0
        self.x0 = x0
        self.y0 = y0

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        lat = max(min(lat, 85.0), -85.0)
        x = (lon + 180.0) / 360.0
        rad = math.radians(lat)
        y = (1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0
        return (
            self.offset_x + (x - self.x0) * self.scale,
            self.offset_y + (y - self.y0) * self.scale,
        )


def _route_coords(payload: dict) -> list[list[float]]:
    geometry = (payload.get("geojson") or {}).get("geometry") or {}
    return geometry.get("coordinates") or []


def _bounds(routes: list[list[list[float]]]) -> tuple[float, float, float, float]:
    lons = [pt[0] for coords in routes for pt in coords]
    lats = [pt[1] for coords in routes for pt in coords]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)
    pad_x = max((max_lon - min_lon) * 0.12, 0.0012)
    pad_y = max((max_lat - min_lat) * 0.12, 0.0012)
    return min_lon - pad_x, min_lat - pad_y, max_lon + pad_x, max_lat + pad_y


def _dashed(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]],
            fill: tuple[int, int, int], width: int, dash: int = 14, gap: int = 10) -> None:
    """Пунктир: у Pillow нет готового, поэтому режем линию на отрезки."""
    left = dash
    drawing = True
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        seg = math.hypot(x2 - x1, y2 - y1)
        if seg == 0:
            continue
        pos = 0.0
        while pos < seg:
            step = min(left, seg - pos)
            t1, t2 = pos / seg, (pos + step) / seg
            if drawing:
                draw.line(
                    [(x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1),
                     (x1 + (x2 - x1) * t2, y1 + (y2 - y1) * t2)],
                    fill=fill, width=width,
                )
            pos += step
            left -= step
            if left <= 0:
                left = gap if drawing else dash
                drawing = not drawing


def _polygon_points(geom, project: Projection) -> list[tuple[float, float]]:
    if geom is None or geom.is_empty:
        return []
    try:
        exterior = geom.exterior
    except AttributeError:
        return []
    return [project(x, y) for x, y in exterior.coords]


def render_compare(
    fast: dict[str, Any],
    alive: dict[str, Any],
    zones_geojson: dict[str, Any] | None = None,
    pois_geojson: dict[str, Any] | None = None,
    size: tuple[int, int] = (1080, 810),
    title: str | None = None,
) -> bytes:
    """Собирает PNG: зоны, оба маршрута, точки старта и финиша, подписи."""
    fast_coords = _route_coords(fast)
    alive_coords = _route_coords(alive)
    if len(fast_coords) < 2 and len(alive_coords) < 2:
        raise ValueError("нечего рисовать: маршруты пустые")

    routes = [coords for coords in (fast_coords, alive_coords) if len(coords) >= 2]

    image = Image.new("RGB", size, BG)
    draw = ImageDraw.Draw(image, "RGBA")
    project = Projection(_bounds(routes), size)

    # лёгкая сетка, чтобы фон не был глухим
    for x in range(0, size[0], 60):
        draw.line([(x, 0), (x, size[1])], fill=GRID, width=1)
    for y in range(0, size[1], 60):
        draw.line([(0, y), (size[0], y)], fill=GRID, width=1)

    # зоны: парки, вода, историческая застройка
    for feature in (zones_geojson or {}).get("features", []):
        props = feature.get("properties") or {}
        color = ZONE_FILL.get(str(props.get("kind")))
        if not color:
            continue
        try:
            geom = shape(feature.get("geometry") or {})
        except Exception:  # noqa: BLE001
            continue
        parts = getattr(geom, "geoms", [geom])
        for part in parts:
            points = _polygon_points(part, project)
            if len(points) >= 3:
                draw.polygon(points, fill=color + (110,))

    # мои точки
    for feature in (pois_geojson or {}).get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        lon, lat = geom["coordinates"][:2]
        x, y = project(lon, lat)
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(232, 236, 241, 210))

    # быстрый — пунктиром, живой — сплошной
    if len(fast_coords) >= 2:
        _dashed(draw, [project(x, y) for x, y in fast_coords], fill=FAST, width=5)
    if len(alive_coords) >= 2:
        points = [project(x, y) for x, y in alive_coords]
        draw.line(points, fill=ALIVE_DARK, width=11, joint="curve")
        draw.line(points, fill=ALIVE, width=6, joint="curve")

    # старт и финиш
    start = (fast_coords or alive_coords)[0]
    end = (fast_coords or alive_coords)[-1]
    for (lon, lat), letter, fill in ((start, "A", (255, 255, 255)), (end, "B", ALIVE)):
        x, y = project(lon, lat)
        draw.ellipse([x - 13, y - 13, x + 13, y + 13], fill=(13, 16, 19, 255),
                     outline=fill, width=3)
        font = _font(15)
        text_w = draw.textlength(letter, font=font)
        draw.text((x - text_w / 2, y - 9), letter, fill=fill, font=font)

    # подписи
    font_title = _font(26)
    font_row = _font(21)
    font_small = _font(16)

    if title:
        draw.text((26, 22), title, fill=TEXT, font=font_title)

    def fmt(payload: dict) -> str:
        minutes = round(float(payload.get("time_s") or 0) / 60)
        km = float(payload.get("distance_m") or 0) / 1000.0
        return f"{minutes} мин · {km:.1f} км"

    lines = [
        ("быстрый", FAST, fmt(fast)),
        ("живой", ALIVE, fmt(alive)),
    ]

    box_h = 30 + len(lines) * 30
    box = [(24, size[1] - box_h - 22), (330, size[1] - 22)]
    draw.rectangle(box, fill=(13, 16, 19, 220), outline=(60, 68, 78, 255), width=1)
    y = box[0][1] + 12
    for label, color, value in lines:
        if label == "быстрый":
            _dashed(draw, [(40, y + 10), (66, y + 10)], fill=color, width=4, dash=6, gap=5)
        else:
            draw.line([(40, y + 10), (66, y + 10)], fill=color, width=4)
        draw.text((76, y), f"{label}: {value}", fill=TEXT, font=font_row)
        y += 30

    draw.text((size[0] - 210, size[1] - 40), "Sevastopol AI", fill=MUTED, font=font_small)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
