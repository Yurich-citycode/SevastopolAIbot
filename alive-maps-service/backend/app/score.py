"""Оценка «живости» маршрута: один балл 0–100 и разбивка в процентах.

Зачем это нужно
---------------
Раньше карточка говорила «+7 минут» — понятно, но не видно, *насколько* живой
маршрут и за счёт чего. Здесь появляется:

    балл = сумма по категориям: вес × (доля маршрута в категории / норма)

Доля — сколько процентов длины маршрута проходит внутри таких мест. Норма —
сколько нужно, чтобы получить полный балл по этой категории (дальше не растёт,
иначе маршрут целиком в парке забирал бы всё).

Категории совпадают с зонами, которые уже есть в данных: парки, набережные,
кафе, история, людные места. Плюс отдельно «мои места» из базы бота.
"""

from __future__ import annotations

from .pois import POIS
from .zones import ZONES

# (ключ, как называть, вес в балле, сколько процентов маршрута = полный балл)
CATEGORIES: tuple[tuple[str, str, float, float], ...] = (
    ("park", "Парки и зелень", 0.26, 35.0),
    ("waterfront", "У воды", 0.22, 20.0),
    ("cafe", "Кафе и витрины", 0.16, 22.0),
    ("historic", "История", 0.14, 15.0),
    ("lively", "Людные места", 0.12, 18.0),
    ("own", "Мои места", 0.10, 10.0),
)

WEIGHT_SUM = sum(item[2] for item in CATEGORIES)


def _share(part: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, part / total))


def evaluate(coordinates: list[list[float]]) -> dict:
    """Балл 0–100 + проценты по категориям для одного маршрута."""
    cov = ZONES.coverage(coordinates)
    total = cov["total"]

    shares = {kind: _share(meters, total) for kind, meters in cov["by_kind"].items()}
    own_meters = POIS.coverage(coordinates)
    if total > 0:
        shares["own"] = _share(own_meters, total * 0.6)  # мои точки считаем щедрее

    score = 0.0
    breakdown: list[dict] = []
    for kind, title, weight, cap in CATEGORIES:
        share = shares.get(kind, 0.0)
        percent = round(share * 100)
        if percent > 0 or kind in ("park", "waterfront"):
            filled = min(1.0, share * 100 / cap) if cap > 0 else 0.0
            score += weight * filled
            breakdown.append({
                "key": kind,
                "title": title,
                "percent": percent,
                "full_at": round(cap),
            })

    # нормируем на сумму весов и переводим в 0–100
    value = round(100 * score / WEIGHT_SUM) if WEIGHT_SUM else 0
    return {
        "score": max(0, min(100, value)),
        "breakdown": breakdown,
        "length_m": round(total),
    }


def compare(a: dict, b: dict) -> dict:
    """Насколько один маршрут живее другого — для фразы «на 35% живее»."""
    fast, alive = a.get("score", 0), b.get("score", 0)
    if fast <= 0:
        more = 0
    else:
        more = round((alive - fast) * 100 / fast)
    return {"alive": alive, "fast": fast, "percent": more}
