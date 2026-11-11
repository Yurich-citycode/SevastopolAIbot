#!/usr/bin/env bash
# Шрифты для подписей на карте (TileServer GL отдаёт их по /fonts/...).
# Один раз, без интернета в рантайме.
set -euo pipefail

cd "$(dirname "$0")/.."

DATA_DIR="${DATA_DIR:-data}"
FONTS_DIR="$DATA_DIR/fonts"
URL="${FONTS_URL:-https://github.com/openmaptiles/fonts/releases/download/v2.0/v2.0.zip}"
TMP="$(mktemp -d)"

if [ -d "$FONTS_DIR" ] && [ -n "$(ls -A "$FONTS_DIR" 2>/dev/null)" ]; then
  echo "✓ шрифты уже есть: $FONTS_DIR ($(ls "$FONTS_DIR" | wc -l | tr -d ' ') начертаний)"
  exit 0
fi

echo "→ качаю шрифты OpenMapTiles (Noto Sans)"
curl -fL --progress-bar -o "$TMP/fonts.zip" "$URL"
mkdir -p "$FONTS_DIR"
unzip -q "$TMP/fonts.zip" -d "$TMP/x"

# в архиве папки вида "Noto Sans Regular" — переносим их как есть
find "$TMP/x" -maxdepth 2 -type d -name "Noto*" -exec cp -r {} "$FONTS_DIR"/ \;

rm -rf "$TMP"
echo "✓ шрифты: $(ls "$FONTS_DIR" | wc -l | tr -d ' ') начертаний в $FONTS_DIR"
echo "  если подписей на карте нет — проверь логи tileserver"
