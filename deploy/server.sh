#!/usr/bin/env bash
# Поднять всё на сервере одной командой.
#
#   bash deploy/server.sh            первый раз: соберёт данные карты и запустит всё
#   bash deploy/server.sh --fast     без сборки данных (когда data уже есть)
#
# Делает по шагам: проверяет docker → собирает данные карты, если их нет →
# поднимает карту → ждёт её готовности → поднимает бота контейнером.
set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
SERVICE="$ROOT/alive-maps-service"
FAST=0
[ "${1:-}" = "--fast" ] && FAST=1

BOLD=$'\033[1m'; LIME=$'\033[38;5;154m'; RED=$'\033[31m'; DIM=$'\033[2m'; OFF=$'\033[0m'
step() { printf "\n%s▸ %s%s\n" "$BOLD" "$*" "$OFF"; }
ok()   { printf "  %s✓%s %s\n" "$LIME" "$OFF" "$*"; }
warn() { printf "  %s!%s %s\n" "$RED" "$OFF" "$*"; }
die()  { printf "\n%s✗ %s%s\n" "$RED" "$*" "$OFF"; exit 1; }

printf "%sSevastopol AI%s %s— запуск на сервере%s\n" "$BOLD" "$OFF" "$DIM" "$OFF"

# ---------- 1. docker ----------
step "Проверяю Docker"
command -v docker >/dev/null 2>&1 || die "Docker не установлен. Поставь: curl -fsSL https://get.docker.com | sh"
docker info >/dev/null 2>&1 || die "Docker установлен, но не запущен (systemctl start docker)"
docker compose version >/dev/null 2>&1 || die "нет docker compose (обнови Docker)"
DC="docker compose"
ok "docker и compose на месте"

# ---------- 2. настройки ----------
step "Проверяю .env"
[ -f "$ROOT/.env" ] || die "нет .env. Создай: cp .env.example .env и впиши TG_TOKEN и ADMIN_ID"
grep -qE '^TG_TOKEN=[0-9]{6,12}:' "$ROOT/.env" || die "в .env не заполнен TG_TOKEN"
ok "TG_TOKEN есть"

# ---------- 3. данные карты ----------
step "Данные карты"
mkdir -p "$SERVICE/data"
if [ -f "$SERVICE/data/sevastopol.mbtiles" ] && [ -f "$SERVICE/data/sevastopol.osm.pbf" ]; then
  ok "данные уже собраны ($(du -h "$SERVICE/data/sevastopol.mbtiles" | cut -f1) тайлов)"
elif [ "$FAST" = "1" ]; then
  warn "данных нет, а запуск в режиме --fast — карта поднимется пустой"
else
  cd "$SERVICE"
  [ -f data/sevastopol.osm.pbf ] || $DC --profile build run --rm --build tools sh /scripts/01-fetch-pbf.sh \
    || die "не скачались данные OSM"
  ok "OSM скачан"

  [ -f data/zones.geojson ] || $DC --profile build run --rm --build tools \
    python /scripts/02-build-zones.py /data/sevastopol.osm.pbf -o /data/zones.geojson \
    || die "не собрались зоны"
  ok "зоны собраны"

  if [ ! -d data/fonts ] || [ -z "$(ls -A data/fonts 2>/dev/null)" ]; then
    $DC --profile build run --rm --build tools sh /scripts/03-fetch-fonts.sh || warn "шрифты не скачались (не критично)"
  fi
  ok "шрифты на месте"

  [ -f data/sevastopol.mbtiles ] || $DC --profile build run --rm planetiler || die "Planetiler не собрал тайлы"
  ok "тайлы собраны"

  # мои точки из базы бота, если рядом есть python с pandas
  if [ -f "$ROOT/Sevastopol AI База.xlsx" ] && command -v python3 >/dev/null 2>&1; then
    python3 tools/export_pois.py --xlsx "$ROOT/Sevastopol AI База.xlsx" \
      --out data/pois.geojson >/dev/null 2>&1 && ok "мои точки обновлены из базы" \
      || warn "точки из базы не обновились (нет pandas) — остался прежний файл"
  fi
  cd "$ROOT"
fi

# ---------- 4. карта ----------
step "Поднимаю карту"
$DC -f "$SERVICE/docker-compose.yml" up -d --build || die "карта не поднялась"
ok "контейнеры запущены"

step "Жду GraphHopper (первый раз импорт графа — 1–3 минуты)"
ready=0
for i in $(seq 1 90); do
  if curl -fsS "http://localhost:8080/api/health" 2>/dev/null | grep -q '"ok":true'; then
    ready=1; break
  fi
  sleep 4
  [ $((i % 10)) -eq 0 ] && printf "  … ещё жду (%d с)\n" $((i * 4))
done
[ "$ready" = "1" ] && ok "карта отвечает на http://localhost:8080" \
  || { warn "карта не ответила за 6 минут"; $DC -f "$SERVICE/docker-compose.yml" logs --tail=25 graphhopper; }

# ---------- 5. бот ----------
step "Поднимаю бота"
mkdir -p "$ROOT/deploy/bot-state"
$DC -f "$ROOT/deploy/docker-compose.server.yml" up -d --build || die "бот не поднялся"
sleep 5
if $DC -f "$ROOT/deploy/docker-compose.server.yml" ps --status running 2>/dev/null | grep -q alive-bot; then
  ok "бот запущен"
else
  warn "бот, похоже, упал — смотри логи:"
  $DC -f "$ROOT/deploy/docker-compose.server.yml" logs --tail=30
fi

# ---------- 6. итог ----------
printf "\n%s%sГотово%s\n" "$BOLD" "$LIME" "$OFF"
printf "  карта:  http://localhost:8080\n"
printf "  бот:    пиши ему в Telegram — кнопка «🗺 Живая карта»\n"
printf "  логи:   docker compose -f deploy/docker-compose.server.yml logs -f\n"
printf "  стоп:   docker compose -f deploy/docker-compose.server.yml down\n"
