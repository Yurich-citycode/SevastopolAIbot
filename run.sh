#!/usr/bin/env bash
# Запуск всего сразу (macOS / Linux): карта + бот.
set -uo pipefail
cd "$(dirname "$0")"

python3 tools/preflight.py || true
echo

bash alive-maps-service/start.sh
echo
echo "Бот запускается в этом окне. Ctrl+C — остановить."
exec python3 sevastopolaibot.py
