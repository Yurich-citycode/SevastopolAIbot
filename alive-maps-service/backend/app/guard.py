"""Простые предохранители для API: размер запроса и частота обращений.

Зачем
-----
Сервис смотрит в сеть через туннель, когда карта нужна в мини-аппе. Значит,
кроме меня к /api/compare может постучаться кто угодно и сколько угодно раз.
Один такой запрос — это до шести обращений к GraphHopper и рендер PNG, то есть
заметная нагрузка на мой ноутбук или на VPS.

Что делает
----------
* отказывает в запросах с телом больше 64 КБ — в JSON тут влезает пара сотен
  байт, всё остальное мусор;
* лимит по адресу отправителя: 120 запросов в минуту на /api/*, из них не
  больше 30 на тяжёлые compare;
* общий лимит на тяжёлые запросы: 60 в минуту со всех адресов сразу —
  на случай бота с одной точки, который не стесняется;
* помнит не больше 2000 адресов, чтобы память не росла.

Локально это ничему не мешает: лимиты с большим запасом.
"""

from __future__ import annotations

import time
from typing import Any

from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY = 64 * 1024           # байт
WINDOW = 60.0                  # окно, секунды
LIMIT_ALL = 120                # запросов на /api/* с одного адреса
LIMIT_HEAVY = 30               # из них на compare
LIMIT_HEAVY_TOTAL = 60         # тяжёлых запросов всего, со всех адресов
MAX_CLIENTS = 2000

HEAVY = ("/api/compare",)

# адрес → [начало окна, всего, тяжёлых]
_buckets: dict[str, list[float]] = {}
_total_heavy: list[float] = [0.0, 0]


def _client_ip(connection: HTTPConnection) -> str:
    """Адрес отправителя. За туннелем настоящий адрес приходит в X-Forwarded-For."""
    forwarded = connection.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    client = connection.client
    return (client.host if client else "?")[:64]


def _allow(ip: str, heavy: bool) -> bool:
    now = time.time()

    if heavy:
        if now - _total_heavy[0] > WINDOW:
            _total_heavy[0], _total_heavy[1] = now, 0
        if _total_heavy[1] >= LIMIT_HEAVY_TOTAL:
            return False

    bucket = _buckets.get(ip)
    if bucket is None or now - bucket[0] > WINDOW:
        if len(_buckets) > MAX_CLIENTS:
            _buckets.clear()
        _buckets[ip] = [now, 1, 1 if heavy else 0]
        if heavy:
            _total_heavy[1] += 1
        return True

    if bucket[1] >= LIMIT_ALL or (heavy and bucket[2] >= LIMIT_HEAVY):
        return False

    bucket[1] += 1
    if heavy:
        bucket[2] += 1
        _total_heavy[1] += 1
    return True


async def _too_big(scope: Scope, receive: Receive, send: Send, status: int, text: str) -> None:
    response = JSONResponse(
        {"detail": text},
        status_code=status,
        headers={"Retry-After": str(int(WINDOW))} if status == 429 else None,
    )
    await response(scope, receive, send)


class GuardMiddleware:
    """ASGI-прослойка: размер тела и частота обращений к /api/*."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/api/"):
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        path = str(scope["path"])
        heavy = path.startswith(HEAVY)

        if not _allow(_client_ip(connection), heavy):
            await _too_big(scope, receive, send, 429, "слишком часто — подожди минуту")
            return

        # тело читаем целиком и сами: иначе Content-Length можно не указывать
        body = b""
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                break
            body += message.get("body", b"")
            if len(body) > MAX_BODY:
                await _too_big(scope, receive, send, 413, "слишком большой запрос")
                return
            more = bool(message.get("more_body"))

        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        await self.app(scope, replay, send)


def reset() -> None:
    """Сбросить счётчики (нужно тестам)."""
    _buckets.clear()
    _total_heavy[0], _total_heavy[1] = 0.0, 0
