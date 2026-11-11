"""Клиент GraphHopper + сборка Custom Model для «живого» маршрута.

Идея простая и вся держится на двух вещах:

1. Правила по тегам OSM (priority): тротуары, дорожки в парках и пешеходные
   улицы приятнее, чем магистрали и обочины. Это работает всегда.
2. Правила по геометрии (areas): если улица попадает внутрь полигона
   «живой зоны» (парк, набережная, квартал с кафе), её приоритет умножается
   ещё раз. Именно это заставляет маршрут заходить в сквер или вдоль бухты.

Если GraphHopper почему-то не принимает areas (например, другая версия),
мы автоматически повторяем запрос без них — сервис остаётся рабочим,
а в ответе появляется флаг `degraded`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import GH_PROFILE, GH_URL

# ---------- базовая модель «приятной пешей прогулки» ----------
# Чем выше priority, тем охотнее GraphHopper ведёт по этой улице.
BASE_PRIORITY: list[dict[str, Any]] = [
    {"if": "road_class == MOTORWAY", "multiply_by": "0.0"},
    {"if": "road_class == TRUNK", "multiply_by": "0.05"},
    {"if": "road_class == PRIMARY", "multiply_by": "0.35"},
    {"if": "road_class == SECONDARY", "multiply_by": "0.60"},
    {"if": "road_class == TERTIARY", "multiply_by": "0.85"},
    {"if": "road_class == RESIDENTIAL", "multiply_by": "1.00"},
    {"if": "road_class == FOOTWAY", "multiply_by": "1.15"},
    {"if": "road_class == PATH", "multiply_by": "1.10"},
    {"if": "road_class == PEDESTRIAN", "multiply_by": "1.20"},
    {"if": "road_class == STEPS", "multiply_by": "0.90"},
]

# Насколько маршрут готов сделать крюк: меньше — охотнее гулять.
# Быстрый маршрут считается вообще без custom model, поэтому там крюков нет.
ALIVE_DISTANCE_INFLUENCE = 40


@dataclass
class Route:
    """Один посчитанный маршрут."""

    mode: str
    coordinates: list[list[float]]          # [[lon, lat], ...]
    distance_m: float
    time_s: float
    degraded: bool = False
    bonuses: list[dict] = field(default_factory=list)

    @property
    def time_min(self) -> float:
        return round(self.time_s / 60, 1)

    def geojson(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "properties": {
                "mode": self.mode,
                "distance_m": round(self.distance_m),
                "time_s": round(self.time_s),
                "time_min": self.time_min,
                "degraded": self.degraded,
            },
            "geometry": {"type": "LineString", "coordinates": self.coordinates},
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "geojson": self.geojson(),
            "distance_m": round(self.distance_m),
            "time_s": round(self.time_s),
            "time_min": self.time_min,
            "degraded": self.degraded,
            "bonuses": self.bonuses,
        }


class GHError(RuntimeError):
    """Ошибка GraphHopper, уже переведённая на человеческий язык."""


def alive_custom_model(areas: dict | None, rules: list[dict], strength: float = 1.0) -> dict:
    """Собирает custom_model: правила по тегам + правила по зонам."""
    model: dict[str, Any] = {
        "distance_influence": ALIVE_DISTANCE_INFLUENCE,
        "priority": list(BASE_PRIORITY),
    }
    if areas and areas.get("features") and rules:
        model["priority"].extend(rules)
        model["areas"] = areas
    return model


def _request_body(start: list[float], end: list[float], custom_model: dict | None) -> dict:
    body: dict[str, Any] = {
        "profile": GH_PROFILE,
        "points": [start, end],
        "points_encoded": False,
        "instructions": False,
        "calc_points": True,
        "locale": "ru",
        # с custom_model нужен гибкий режим, CH/LM в конфиге не включены
        "ch.disable": True,
    }
    if custom_model is not None:
        body["custom_model"] = custom_model
    return body


def _human_error(status: int, payload: Any) -> str:
    message = ""
    if isinstance(payload, dict):
        message = str(payload.get("message") or "")
    low = message.lower()
    if "out of bounds" in low or "cannot find point" in low:
        return "точка вне зоны данных — поставь её ближе к улице Севастополя"
    if "connection between" in low or "not found" in low:
        return "между точками нет пешего прохода по данным OSM"
    if "point 0" in low:
        return "не удалось привязать начальную точку к улице"
    if "point 1" in low:
        return "не удалось привязать конечную точку к улице"
    if message:
        return f"GraphHopper: {message}"
    return f"GraphHopper ответил {status}"


async def route(
    client: httpx.AsyncClient,
    start: list[float],
    end: list[float],
    mode: str,
    areas: dict | None = None,
    rules: list[dict] | None = None,
    strength: float = 1.0,
) -> Route:
    """Считает маршрут: fast — штатный пеший, alive — с надбавками за зоны."""
    custom_model = None
    if mode == "alive":
        custom_model = alive_custom_model(areas, rules or [], strength=strength)

    async def call(model: dict | None) -> tuple[int, Any]:
        try:
            resp = await client.post(
                f"{GH_URL}/route",
                json=_request_body(start, end, model),
                timeout=25.0,
            )
        except httpx.HTTPError as exc:
            raise GHError(f"GraphHopper недоступен: {exc}") from exc
        try:
            payload = resp.json()
        except ValueError:
            payload = resp.text[:400]
        return resp.status_code, payload

    status, payload = await call(custom_model)

    # откат: если areas не понравились движку — повторяем без зон
    degraded = False
    if status >= 400 and custom_model is not None and _mentions_areas(payload):
        degraded = True
        status, payload = await call(alive_custom_model(None, []))

    if status >= 400:
        raise GHError(_human_error(status, payload))

    paths = (payload or {}).get("paths") or []
    if not paths:
        raise GHError("маршрут не найден: между точками нет пешего прохода")

    best = paths[0]
    coords = (best.get("points") or {}).get("coordinates") or []
    if len(coords) < 2:
        raise GHError("GraphHopper вернул пустую геометрию маршрута")

    return Route(
        mode=mode,
        coordinates=coords,
        distance_m=float(best.get("distance") or 0.0),
        time_s=float(best.get("time") or 0.0) / 1000.0,   # GH отдаёт миллисекунды
        degraded=degraded,
    )


def _mentions_areas(payload: Any) -> bool:
    text = str(payload).lower()
    return any(word in text for word in ("area", "custom model", "custom_model", "polygon"))


async def health(client: httpx.AsyncClient) -> dict:
    """Жив ли GraphHopper и какие профили подняты."""
    try:
        resp = await client.get(f"{GH_URL}/health", timeout=4.0)
        ok = resp.status_code < 400
        return {"ok": ok, "details": resp.text[:300]}
    except httpx.HTTPError as exc:
        return {"ok": False, "details": str(exc)}
