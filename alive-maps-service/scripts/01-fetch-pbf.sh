#!/usr/bin/env bash
# Скачивает OSM-данные для Севастополя.
#
# Источник: Geofabrik, «Crimean Federal District» (~39 МБ, обновляется ежедневно).
# Это весь Крым — для города это нормально: граф GraphHopper получится чуть больше,
# а тайлы мы всё равно ограничиваем bbox'ом Севастополя.
#
# Если установлен osmium-tool, файл обрезается по bbox города.
set -euo pipefail

cd "$(dirname "$0")/.."

DATA_DIR="${DATA_DIR:-data}"
OUT="$DATA_DIR/sevastopol.osm.pbf"
RAW="$DATA_DIR/crimea.osm.pbf"
URL="${PBF_URL:-https://download.geofabrik.de/russia/crimean-fed-district-latest.osm.pbf}"
BBOX_STR="${BBOX:-33.30,44.28,33.85,44.78}"

mkdir -p "$DATA_DIR"

if [ -f "$OUT" ]; then
  echo "✓ данные уже есть: $OUT ($(du -h "$OUT" | cut -f1))"
  echo "  перекачать: rm $OUT && make data"
  exit 0
fi

echo "→ качаю $URL"
curl -fL --progress-bar -o "$RAW" "$URL"

if command -v osmium >/dev/null 2>&1; then
  echo "→ обрезаю по bbox $BBOX_STR (osmium)"
  osmium extract -b "$BBOX_STR" --overwrite "$RAW" -o "$OUT"
  rm -f "$RAW"
else
  echo "! osmium-tool не найден — беру файл целиком (весь Крым)."
  echo "  Хочешь только Севастополь: brew install osmium-tool / apt install osmium-tool"
  mv "$RAW" "$OUT"
fi

echo "✓ готово: $OUT ($(du -h "$OUT" | cut -f1))"
