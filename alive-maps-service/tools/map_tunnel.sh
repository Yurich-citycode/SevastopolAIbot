#!/usr/bin/env bash
# Публичный https-адрес для карты — одна команда.
#
#   bash tools/map_tunnel.sh
#
# Что делает:
#   1. находит или скачивает cloudflared;
#   2. поднимает туннель до локальной карты (http://localhost:8080);
#   3. получившийся адрес https://…trycloudflare.com вписывает в .env бота
#      как ALIVE_MAP_PUBLIC;
#   4. висит в этом окне — пока оно открыто, карта доступна с телефона.
#
# Дальше: перезапусти бота и в @BotFather сделай /setmenubutton с этим адресом.
set -uo pipefail

cd "$(dirname "$0")/.."          # из tools/ в корень сервиса
SERVICE_DIR="$(pwd)"
ENV_FILE="$(dirname "$SERVICE_DIR")/.env"
PORT="${PORT:-8080}"
BIN="$SERVICE_DIR/cloudflared"

say()  { printf '%s\n' "$*"; }
ok()   { printf '  \033[38;5;154m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m✗ %s\033[0m\n' "$*"; exit 1; }

# ---------- 1. cloudflared ----------
if command -v cloudflared >/dev/null 2>&1; then
  CF="$(command -v cloudflared)"
elif [ -x "$BIN" ]; then
  CF="$BIN"
else
  say "Скачиваю cloudflared (один раз, ~35 МБ)…"
  case "$(uname -s)" in
    Linux)  URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" ;;
    Darwin) URL="https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz" ;;
    *)      die "не знаю, как ставить cloudflared в $(uname -s). Поставь вручную: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" ;;
  esac
  if [ "${URL##*.}" = "tgz" ]; then
    curl -fsSL -o "$SERVICE_DIR/cloudflared.tgz" "$URL" || die "не скачалось"
    tar -xzf "$SERVICE_DIR/cloudflared.tgz" -C "$SERVICE_DIR" cloudflared || die "не распаковалось"
    rm -f "$SERVICE_DIR/cloudflared.tgz"
  else
    curl -fsSL -o "$BIN" "$URL" || die "не скачалось (нет интернета?)"
  fi
  chmod +x "$BIN"
  CF="$BIN"
fi
ok "cloudflared: $CF"

# ---------- 2. сервис отвечает? ----------
if ! curl -fsS "http://localhost:$PORT/health" >/dev/null 2>&1; then
  warn "карта на localhost:$PORT не отвечает — туннель всё равно подниму,"
  warn "но сначала запусти сервис: ./start.sh (или start.bat)"
fi

# ---------- 3. адрес в .env ----------
write_env() {
  local url="$1"
  [ -f "$ENV_FILE" ] || : > "$ENV_FILE"
  if grep -q '^ALIVE_MAP_PUBLIC=' "$ENV_FILE" 2>/dev/null; then
    # заменяю строку, не трогая остальное
    tmp="$(mktemp)"
    awk -v u="$url" 'BEGIN{done=0} /^ALIVE_MAP_PUBLIC=/ && !done {print "ALIVE_MAP_PUBLIC=" u; done=1; next} {print}' \
      "$ENV_FILE" > "$tmp" && mv "$tmp" "$ENV_FILE"
  else
    printf '\nALIVE_MAP_PUBLIC=%s\n' "$url" >> "$ENV_FILE"
  fi
  ok "адрес записан в $ENV_FILE"
}

# ---------- 4. туннель ----------
say ""
say "Поднимаю туннель до http://localhost:$PORT …"
say "Окно не закрывай: пока оно живо, карта открывается с телефона."
say ""

"$CF" tunnel --url "http://localhost:$PORT" --no-autoupdate 2>&1 | while IFS= read -r line; do
  printf '%s\n' "$line"
  if printf '%s' "$line" | grep -qoE 'https://[a-z0-9-]+\.trycloudflare\.com'; then
    url="$(printf '%s' "$line" | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1)"
    if [ ! -f "${TMPDIR:-/tmp}/alive-tunnel-url" ] || [ "$(cat "${TMPDIR:-/tmp}/alive-tunnel-url")" != "$url" ]; then
      printf '%s' "$url" > "${TMPDIR:-/tmp}/alive-tunnel-url"
      write_env "$url"
      say ""
      say "  Карта теперь здесь: $url"
      say "  Дальше: перезапусти бота, потом в @BotFather → /setmenubutton → этот адрес."
      say ""
    fi
  fi
done
