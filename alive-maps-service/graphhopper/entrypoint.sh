#!/bin/sh
# Понятная ошибка вместо java-стектрейса, если забыли скачать данные.
set -e

PBF="${PBF:-/data/sevastopol.osm.pbf}"

if [ ! -f "$PBF" ]; then
  cat >&2 <<EOF
──────────────────────────────────────────────────────────────
 GraphHopper: не найден файл данных $PBF

 Скачай данные и собери зоны:
     make data

 (это scripts/01-fetch-pbf.sh + scripts/02-build-zones.py)
──────────────────────────────────────────────────────────────
EOF
  exit 1
fi

if [ -f /data/graph-cache/properties ]; then
  echo "[gh] граф уже собран, импорт пропускаем"
else
  echo "[gh] первый запуск: импортирую $(du -h "$PBF" | cut -f1) OSM-данных, это может занять несколько минут"
fi

echo "[gh] GraphHopper ${GH_VERSION} → http://0.0.0.0:8989"
exec java ${JAVA_OPTS:--Xmx2g} -jar /app/graphhopper.jar "$@"
