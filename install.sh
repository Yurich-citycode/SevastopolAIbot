#!/usr/bin/env bash
# Установка и обновление бота на сервере одной командой (Ubuntu / Debian).
#
#   1. Скачай репозиторий: Code → Download ZIP, закинь на сервер, распакуй.
#   2. В папке проекта:   sudo bash install.sh
#
# Первый раз спросит TG_TOKEN и ADMIN_ID. Повторный запуск (после новой версии)
# обновляет код и перезапускает бота: токен, паспорта и бэкапы не трогает.
# Перенос с компьютера/Colab: положи старый bot_state.json рядом с install.sh.
#
# Без вопросов:  sudo TG_TOKEN=... ADMIN_ID=... bash install.sh
# Удалить бота:  sudo bash install.sh --uninstall   (данные в /var/lib остаются)
set -euo pipefail

NAME=sevastopol-ai-bot
APP_DIR=/opt/$NAME
DATA_DIR=/var/lib/$NAME
ENV_FILE=/etc/$NAME.env
UNIT=/etc/systemd/system/$NAME.service
RUN_USER=sevastopolbot
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n❌ %s\n' "$*" >&2; exit 1; }
have_systemd() { [ -d /run/systemd/system ]; }

[ "$(id -u)" -eq 0 ] || die "Нужны права администратора: sudo bash install.sh"

if [ "${1:-}" = "--uninstall" ]; then
  have_systemd && { systemctl disable --now "$NAME" 2>/dev/null || true; rm -f "$UNIT"; systemctl daemon-reload; }
  rm -rf "$APP_DIR"
  say "Бот удалён. Паспорта и бэкапы остались в $DATA_DIR, настройки — в $ENV_FILE."
  exit 0
fi

[ -f "$SRC_DIR/sevastopolaibot.py" ] || die "Запускай install.sh из папки проекта (рядом должен лежать sevastopolaibot.py)."

say "1/5 Python и пакеты системы"
if command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq || true
  apt-get install -y -qq python3 python3-venv python3-pip ca-certificates >/dev/null
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Нужен Python 3.10 или новее."

say "2/5 Код → $APP_DIR"
id "$RUN_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$RUN_USER"
mkdir -p "$APP_DIR" "$DATA_DIR/backups"
if [ "$SRC_DIR" != "$APP_DIR" ]; then
  find "$APP_DIR" -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf {} +
  tar -C "$SRC_DIR" --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.env \
      --exclude=bot_state.json --exclude='bot_state.json.*' --exclude=backups -cf - . | tar -C "$APP_DIR" -xf -
fi
if [ -f "$SRC_DIR/bot_state.json" ] && [ ! -f "$DATA_DIR/bot_state.json" ]; then
  install -m 600 "$SRC_DIR/bot_state.json" "$DATA_DIR/bot_state.json"
  echo "Перенёс паспорта из bot_state.json."
fi
chown -R root:root "$APP_DIR"
chown -R "$RUN_USER:$RUN_USER" "$DATA_DIR"
chmod 700 "$DATA_DIR"

say "3/5 Зависимости (1–2 минуты)"
[ -x "$APP_DIR/.venv/bin/python" ] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

say "4/5 Настройки → $ENV_FILE"
check_token() {
  "$APP_DIR/.venv/bin/python" - "$1" <<'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen(f"https://api.telegram.org/bot{sys.argv[1]}/getMe", timeout=15) as r:
        print("✅ Токен рабочий: @" + json.load(r)["result"]["username"])
except Exception as e:
    print(f"⚠️  Telegram не подтвердил токен ({e}). Проверь его в @BotFather.")
    sys.exit(1)
PY
}
if [ -f "$ENV_FILE" ]; then
  echo "Уже есть — оставляю как есть. Поменять: sudo nano $ENV_FILE"
else
  TOKEN="${TG_TOKEN:-}"; ADMIN="${ADMIN_ID:-}"
  while [ -z "$TOKEN" ]; do
    read -r -s -p "TG_TOKEN (из @BotFather, на экране не видно): " TOKEN </dev/tty; echo
    if [ -n "$TOKEN" ] && ! check_token "$TOKEN"; then
      read -r -p "Ввести токен заново? [Y/n] " again </dev/tty
      [[ "$again" =~ ^[nNнН] ]] || TOKEN=""
    fi
  done
  until [[ "$ADMIN" =~ ^[0-9]+$ ]]; do
    read -r -p "ADMIN_ID (число из @userinfobot): " ADMIN </dev/tty
  done
  umask 077
  {
    echo "TG_TOKEN=$TOKEN"
    echo "ADMIN_ID=$ADMIN"
    echo "STATE_FILE=$DATA_DIR/bot_state.json"
    echo "BACKUP_DIR=$DATA_DIR/backups"
    echo "# Места в клубе и «Основатели» меняются прямо в боте: /seats 45, /founders on"
    echo "CLUB_SEATS_OPEN=0"
    echo "CLUB_FOUNDERS_OPEN=0"
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"; chown root:root "$ENV_FILE"
fi

say "5/5 Автозапуск"
cat > "$UNIT" <<EOF
[Unit]
Description=Sevastopol AI Bot
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$APP_DIR/.venv/bin/python -u sevastopolaibot.py
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
EOF

if have_systemd; then
  systemctl daemon-reload
  systemctl enable "$NAME" >/dev/null 2>&1
  systemctl restart "$NAME"
  sleep 5
  if systemctl is-active --quiet "$NAME"; then
    say "✅ Бот работает и сам поднимется после перезагрузки сервера."
  else
    journalctl -u "$NAME" -n 30 --no-pager || true
    die "Бот не запустился — выше последние строки лога."
  fi
else
  say "⚠️  systemd нет (контейнер?). Запуск вручную:"
  echo "  sudo -u $RUN_USER env \$(cat $ENV_FILE | grep -v '^#' | xargs) $APP_DIR/.venv/bin/python $APP_DIR/sevastopolaibot.py"
fi
cat <<EOF

Полезное:
  логи:          journalctl -u $NAME -f
  перезапуск:    sudo systemctl restart $NAME
  обновить код:  распакуй новый ZIP и снова  sudo bash install.sh
  паспорта:      $DATA_DIR/bot_state.json  (бэкапы: $DATA_DIR/backups)
EOF
