#!/usr/bin/env bash
# Sevastopol Alive Maps — запуск одной командой (macOS / Linux / WSL / Git Bash).
#
#   bash start.sh
#
# Скрипт сам: проверит Docker → скачает данные → соберёт зоны и шрифты →
# соберёт тайлы → поднимет стек → дождётся готовности → откроет браузер.
# Повторный запуск ничего не перекачивает.
set -uo pipefail
cd "$(dirname "$0")"

BOLD=$'\033[1m'; DIM=$'\033[2m'; LIME=$'\033[38;5;154m'; RED=$'\033[31m'; OFF=$'\033[0m'

say()  { printf "%s\n" "$*"; }
step() { printf "\n%s▸ %s%s\n" "$BOLD" "$*" "$OFF"; }
ok()   { printf "  %s✓%s %s\n" "$LIME" "$OFF" "$*"; }
warn() { printf "  %s!%s %s\n" "$RED" "$OFF" "$*"; }
die()  { printf "\n%s✗ %s%s\n" "$RED" "$*" "$OFF"; exit 1; }

say "${BOLD}Sevastopol Alive Maps${OFF} ${DIM}— локальная карта с живыми маршрутами${OFF}"

# ---------- 1. Docker / Podman ----------
step "Проверяю Docker (или Podman)"
# macOS: Docker Desktop кладёт CLI сюда и не всегда обновляет PATH
for d in /Applications/Docker.app/Contents/Resources/bin "$HOME/.docker/bin"; do
  [ -d "$d" ] && case ":$PATH:" in *":$d:"*) ;; *) PATH="$d:$PATH" ;; esac
done
export PATH
if [ -n "${DC_CMD:-}" ]; then
  DC="$DC_CMD"
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  DC="podman compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  die "Не найден ни Docker, ни Podman.
  Если Docker Desktop только что установлен — перезапусти терминал/компьютер.
  Варианты:
   1) Docker Desktop  https://www.docker.com/products/docker-desktop/
   2) Podman Desktop  https://podman-desktop.io/downloads   (аналог, без лицензии Docker)
   3) совсем без контейнеров — см. SETUP.md, вариант D"
fi

# движок должен быть запущен
case "$DC" in
  podman*) ENG=podman ;;
  *)       ENG=docker ;;
esac
if ! $ENG info >/dev/null 2>&1; then
  die "$ENG установлен, но не запущен. Запусти $ENG Desktop и повтори."
fi
ok "готово: $DC"

# сколько свободно памяти — предупредим, если мало
if command -v free >/dev/null 2>&1; then
  MEM_GB=$(free -g | awk '/^Mem:/{print $2}')
  [ "${MEM_GB:-0}" -lt 6 ] && warn "у машины ${MEM_GB} ГБ RAM, комфортно с 6+ (может подтормаживать)"
fi

NOTTY="--no-TTY"
case "$DC" in podman*) NOTTY="" ;; esac
BUILD="$DC --profile build run --rm $NOTTY"

# ---------- 2. Данные ----------
step "Данные OpenStreetMap для Севастополя (~39 МБ)"
if [ -f data/sevastopol.osm.pbf ]; then
  ok "уже есть: $(du -h data/sevastopol.osm.pbf | cut -f1)"
else
  $BUILD tools sh /scripts/01-fetch-pbf.sh || die "не удалось скачать данные (нет интернета?)"
  ok "скачано"
fi

# ---------- 3. Живые зоны ----------
step "Живые зоны: парки, кафе, набережные, история"
if [ -f data/zones.geojson ] && [ data/zones.geojson -nt data/sevastopol.osm.pbf ]; then
  ok "уже есть ($(python3 -c "import json;print(len(json.load(open('data/zones.geojson'))['features']))" 2>/dev/null || echo '?') полигонов)"
else
  $BUILD tools python /scripts/02-build-zones.py /data/sevastopol.osm.pbf -o /data/zones.geojson \
    || die "не удалось собрать зоны"
  ok "собрано"
fi

# ---------- 4. Шрифты ----------
step "Шрифты для подписей на карте"
if [ -d data/fonts ] && [ -n "$(ls -A data/fonts 2>/dev/null)" ]; then
  ok "уже есть"
else
  $BUILD tools sh /scripts/03-fetch-fonts.sh || warn "шрифты не скачались — карта будет без подписей (не критично)"
fi

# ---------- 5. Тайлы ----------
step "Тайлы карты (Planetiler, 3–10 минут на первый раз)"
if [ -f data/sevastopol.mbtiles ]; then
  ok "уже есть: $(du -h data/sevastopol.mbtiles | cut -f1)"
else
  $DC --profile build run --rm planetiler || die "Planetiler не смог собрать тайлы"
  ok "тайлы собраны"
fi

# ---------- 6. Стек ----------
step "Поднимаю сервисы"
$DC up -d --build || die "docker compose up не удался — смотри вывод выше"
ok "контейнеры запущены"

# ---------- 7. Ждём готовности ----------
step "Жду GraphHopper (первый раз — импорт графа, 1–3 минуты)"
URL="http://localhost:${PORT:-8080}"
ready=0
for i in $(seq 1 120); do
  if curl -fsS "$URL/health" >/dev/null 2>&1; then
    gh=$(curl -fsS "$URL/api/health" 2>/dev/null | grep -o '"ok":[a-z]*' | tail -1 || true)
    if [ "$gh" = '"ok":true' ]; then ready=1; break; fi
  fi
  sleep 5
  [ $((i % 6)) -eq 0 ] && printf "  … ещё жду (%d с)\n" $((i * 5))
done

if [ "$ready" = "1" ]; then
  ok "сервис готов"
else
  warn "не дождался за 10 минут — открой логи: $DC logs -f graphhopper"
fi

say ""
say "${LIME}${BOLD}→ $URL${OFF}"
say "${DIM}   логи: $DC logs -f    остановить: $DC down${OFF}"

if command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
fi
