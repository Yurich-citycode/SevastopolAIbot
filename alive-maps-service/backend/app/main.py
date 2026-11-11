"""FastAPI-прослойка Sevastopol Alive Maps.

Что делает:
  * отдаёт фронтенд (один html + вендоренный MapLibre);
  * проксирует локальные тайлы и шрифты из TileServer GL, чтобы браузер
    обращался только к одному хосту (никаких CORS и «внешних» доменов);
  * считает маршруты: fast — штатный пеший, alive — с живыми зонами;
  * объясняет живой маршрут: через какие парки/набережные он прошёл.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import gh
from .config import (
    BBOX, CACHE_TTL, CENTER, GH_PROFILE, POIS_FILE, STYLE_FILE, TS_SOURCE, TS_URL, ZONES_FILE,
)
from .pois import POIS
from .route_png import render_compare
from .zones import KIND_BONUS, ZONES

STATIC_DIR = Path(__file__).parent / "static"

# ---------- кэш ответов ----------
_cache: dict[str, tuple[float, dict]] = {}


def _cache_get(key: str) -> dict | None:
    if CACHE_TTL <= 0:
        return None
    item = _cache.get(key)
    if not item:
        return None
    stamp, payload = item
    if time.time() - stamp > CACHE_TTL:
        _cache.pop(key, None)
        return None
    return payload


def _cache_put(key: str, payload: dict) -> None:
    if CACHE_TTL <= 0:
        return
    if len(_cache) > 500:          # не растём бесконечно
        _cache.clear()
    _cache[key] = (time.time(), payload)


# ---------- приложение ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    ZONES.reload(ZONES_FILE)
    POIS.reload(POIS_FILE)
    app.state.client = httpx.AsyncClient()
    yield
    await app.state.client.aclose()


app = FastAPI(title="Sevastopol Alive Maps", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Point2(BaseModel):
    start: list[float] = Field(..., min_length=2, max_length=2, description="[lon, lat]")
    end: list[float] = Field(..., min_length=2, max_length=2, description="[lon, lat]")


class RouteRequest(Point2):
    mode: Literal["fast", "alive"] = "alive"
    # 0 — живые зоны выключены, 2 — усиленные; влияет на «крюк» маршрута
    strength: float = Field(1.0, ge=0.0, le=3.0)


def _check_point(name: str, point: list[float]) -> list[float]:
    try:
        lon, lat = float(point[0]), float(point[1])
    except (TypeError, ValueError, IndexError) as exc:
        raise HTTPException(400, f"{name}: координаты должны быть [lon, lat]") from exc
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise HTTPException(400, f"{name}: координаты вне допустимых значений")
    min_lon, min_lat, max_lon, max_lat = BBOX
    if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
        raise HTTPException(400, f"{name}: точка вне карты Севастополя")
    return [round(lon, 6), round(lat, 6)]


def _cache_key(start: list[float], end: list[float], mode: str, strength: float) -> str:
    return f"{mode}|{start[0]:.5f},{start[1]:.5f}|{end[0]:.5f},{end[1]:.5f}|{strength:.2f}"


def _areas_and_rules(strength: float) -> tuple[dict | None, list[dict]]:
    """Зоны OSM + мои точки в одном наборе areas для GraphHopper."""
    features: list[dict] = []
    rules: list[dict] = []

    zones_areas, zones_rules = ZONES.areas_and_rules(strength=strength)
    features.extend(zones_areas.get("features") or [])
    rules.extend(zones_rules)

    own_areas, own_rules = POIS.areas_and_rules(strength=strength)
    features.extend(own_areas.get("features") or [])
    rules.extend(own_rules)

    if not features:
        return None, []
    return {"type": "FeatureCollection", "features": features}, rules


def _explain(coordinates: list[list[float]]) -> list[dict]:
    """Сначала мои точки (их немного и они именные), потом зоны OSM."""
    own = POIS.explain(coordinates)
    zones = ZONES.explain(coordinates)
    merged: list[dict] = []
    seen: set[tuple] = set()
    for item in own + zones:
        key = (item.get("kind"), item.get("name"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged[:12]


async def _compute(request: Request, start: list[float], end: list[float], mode: str, strength: float) -> dict:
    key = _cache_key(start, end, mode, strength)
    cached = _cache_get(key)
    if cached:
        return {**cached, "cached": True}

    areas, rules = (None, [])
    if mode == "alive" and strength > 0:
        areas, rules = _areas_and_rules(strength)

    try:
        result = await gh.route(
            request.app.state.client, start, end, mode,
            areas=areas, rules=rules, strength=strength,
        )
    except gh.GHError as exc:
        raise HTTPException(502, str(exc)) from exc

    payload = result.as_dict()

    if mode == "alive":
        payload["bonuses"] = _explain(result.coordinates)

    _cache_put(key, payload)
    return {**payload, "cached": False}


@app.post("/api/route")
async def api_route(req: RouteRequest, request: Request) -> JSONResponse:
    start = _check_point("старт", req.start)
    end = _check_point("финиш", req.end)
    payload = await _compute(request, start, end, req.mode, req.strength)
    return JSONResponse(payload)


@app.post("/api/compare")
async def api_compare(req: Point2, request: Request) -> JSONResponse:
    """Оба маршрута сразу + разница — это то, что показывает интерфейс."""
    start = _check_point("старт", req.start)
    end = _check_point("финиш", req.end)

    fast = await _compute(request, start, end, "fast", 0.0)
    alive = await _compute(request, start, end, "alive", 1.0)

    delta_s = alive["time_s"] - fast["time_s"]
    delta_m = alive["distance_m"] - fast["distance_m"]
    return JSONResponse({
        "fast": fast,
        "alive": alive,
        "delta": {
            "time_s": round(delta_s),
            "time_min": round(delta_s / 60, 1),
            "distance_m": round(delta_m),
            "same_route": abs(delta_m) < 15,
        },
    })


@app.get("/api/pois")
async def api_pois() -> JSONResponse:
    """Мои точки из базы — то, что отличает карту от обычной OSM."""
    return JSONResponse(POIS.geojson())


@app.get("/api/zones")
async def api_zones() -> JSONResponse:
    return JSONResponse(ZONES.geojson())


@app.get("/api/config")
async def api_config(request: Request) -> JSONResponse:
    """Всё, что нужно фронтенду на старте."""
    gh_status = await gh.health(request.app.state.client)
    tiles_ok = False
    try:
        resp = await request.app.state.client.get(f"{TS_URL}/health", timeout=4.0)
        tiles_ok = resp.status_code < 400
    except httpx.HTTPError:
        pass

    return JSONResponse({
        "center": list(CENTER),
        "bbox": list(BBOX),
        "profile": GH_PROFILE,
        "own": {
            "count": POIS.count,
            "by_kind": POIS.by_kind(),
            "error": POIS.error,
        },
        "zones": {
            "count": ZONES.count,
            "by_kind": ZONES.by_kind(),
            "bonus": KIND_BONUS,
            "error": ZONES.error,
        },
        "graphhopper": gh_status,
        "tiles_ok": tiles_ok,
    })


@app.get("/api/compare.png")
async def api_compare_png(request: Request, from_: str = Query("", alias="from"),
                          to: str = "", title: str = "") -> Response:
    """Та же пара маршрутов, но картинкой — для бота.

    Координаты в query: from=lat,lon&to=lat,lon (как их присылает Telegram).
    """
    try:
        start_lat, start_lon = _parse_latlon(from_, "from")
        end_lat, end_lon = _parse_latlon(to, "to")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    start = _check_point("старт", [start_lon, start_lat])
    end = _check_point("финиш", [end_lon, end_lat])

    fast = await _compute(request, start, end, "fast", 0.0)
    alive = await _compute(request, start, end, "alive", 1.0)

    try:
        png = render_compare(
            fast, alive,
            zones_geojson=ZONES.geojson(),
            pois_geojson=POIS.geojson(),
            title=title or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return Response(
        png,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Route-Minutes": f"{round(fast['time_s'] / 60)}/{round(alive['time_s'] / 60)}",
        },
    )


def _parse_latlon(value: str, name: str) -> tuple[float, float]:
    """«44.61,33.52» → (lat, lon). Порядок именно такой, как в Telegram."""
    text = (value or "").replace(" ", "")
    if "," not in text:
        raise ValueError(f"{name}: нужен формат lat,lon")
    left, right = text.split(",", 1)
    try:
        lat, lon = float(left), float(right)
    except ValueError as exc:
        raise ValueError(f"{name}: координаты должны быть числами") from exc
    return lat, lon


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "zones": ZONES.count, "own": POIS.count}


@app.get("/api/health")
async def api_health(request: Request) -> dict:
    return {
        "ok": True,
        "zones": ZONES.count,
        "zones_error": ZONES.error,
        "own": POIS.count,
        "own_error": POIS.error,
        "graphhopper": await gh.health(request.app.state.client),
    }


# ---------- стиль и прокси тайлов ----------
@app.get("/style.json")
async def style() -> Response:
    path = Path(STYLE_FILE)
    if not path.exists():
        raise HTTPException(500, f"нет файла стиля {STYLE_FILE}")
    return Response(path.read_text(encoding="utf-8"), media_type="application/json")


@app.get("/tiles/{z}/{x}/{y}.pbf")
async def tiles(z: int, x: int, y: int, request: Request) -> Response:
    url = f"{TS_URL}/data/{TS_SOURCE}/{z}/{x}/{y}.pbf"
    try:
        resp = await request.app.state.client.get(url, timeout=15.0)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"TileServer недоступен: {exc}") from exc
    if resp.status_code != 200:
        return Response(status_code=resp.status_code)
    return Response(
        resp.content,
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/fonts/{path:path}")
async def fonts(path: str, request: Request) -> Response:
    try:
        resp = await request.app.state.client.get(f"{TS_URL}/fonts/{path}", timeout=15.0)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"шрифты недоступны: {exc}") from exc
    if resp.status_code != 200:
        return Response(status_code=resp.status_code)
    return Response(resp.content, media_type="application/x-protobuf",
                    headers={"Cache-Control": "public, max-age=86400"})


# ---------- фронтенд ----------
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
