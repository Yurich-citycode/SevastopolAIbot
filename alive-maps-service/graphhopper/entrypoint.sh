#!/bin/sh
# Понятная ошибка вместо java-стектрейса, если забыли скачать данные,
# и один автоматический перезапуск, если кэш графа остался битым
# после прерванного импорта (частая история при первом запуске).
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

attempt=1
while true; do
  echo "[gh] GraphHopper ${GH_VERSION} → http://0.0.0.0:8989 (попытка $attempt)"
  set +e
  java ${JAVA_OPTS:--Xmx2g} -jar /app/graphhopper.jar "$@"
  code=$?
  set -e

  [ "$code" -eq 0 ] && exit 0

  if [ "$attempt" -ge 2 ]; then
    echo "[gh] второй запуск тоже упал (код $code) — смотри лог выше" >&2
    exit "$code"
  fi

  if [ -d /data/graph-cache ]; then
    echo "[gh] импорт оборвался — удаляю недописанный кэш /data/graph-cache и пробую ещё раз"
    rm -rf /data/graph-cache
    attempt=$((attempt + 1))
    continue
  fi

  exit "$code"
done
