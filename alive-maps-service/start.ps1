# Sevastopol Alive Maps — запуск одной командой (Windows / PowerShell)
# Двойной клик по start.bat делает то же самое.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Say([string]$m)  { Write-Host $m }
function Step([string]$m) { Write-Host ""; Write-Host "> $m" -ForegroundColor Cyan }
function Ok([string]$m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "  [!] $m" -ForegroundColor Yellow }
function Die([string]$m)  { Write-Host ""; Write-Host "[x] $m" -ForegroundColor Red; Read-Host "Enter, чтобы закрыть"; exit 1 }

Say "Sevastopol Alive Maps - локальная карта с живыми маршрутами"

# ---------- 1. Docker ----------
Step "Проверяю Docker"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Die "Docker не найден.`n  1) Поставь Docker Desktop: https://www.docker.com/products/docker-desktop/`n  2) Перезагрузись`n  3) Запусти start.bat снова"
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Die "Docker установлен, но не запущен.`n  Открой Docker Desktop (значок кита в трее), дождись 'Engine running' и повтори."
}
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Die "Нужен Docker Compose v2 — обнови Docker Desktop до свежей версии." }
Ok "Docker работает"

# ---------- 2. Данные ----------
Step "Данные OpenStreetMap для Севастополя (~39 МБ)"
if (Test-Path "data/sevastopol.osm.pbf") {
  Ok "уже есть"
} else {
  docker compose --profile build run --rm --no-TTY tools sh /scripts/01-fetch-pbf.sh
  if (-not (Test-Path "data/sevastopol.osm.pbf")) { Die "Не удалось скачать данные. Проверь интернет и повтори." }
  Ok "скачано"
}

# ---------- 3. Зоны ----------
Step "Живые зоны: парки, кафе, набережные, история"
$needZones = $true
if (Test-Path "data/zones.geojson") {
  if ((Get-Item "data/zones.geojson").LastWriteTime -gt (Get-Item "data/sevastopol.osm.pbf").LastWriteTime) { $needZones = $false }
}
if ($needZones) {
  docker compose --profile build run --rm --no-TTY tools python /scripts/02-build-zones.py /data/sevastopol.osm.pbf -o /data/zones.geojson
  if (-not (Test-Path "data/zones.geojson")) { Die "Не удалось собрать зоны." }
  Ok "собрано"
} else { Ok "уже есть" }

# ---------- 4. Шрифты ----------
Step "Шрифты для подписей на карте"
$fontCount = 0
if (Test-Path "data/fonts") { $fontCount = (Get-ChildItem "data/fonts" -Directory | Measure-Object).Count }
if ($fontCount -eq 0) {
  docker compose --profile build run --rm --no-TTY tools sh /scripts/03-fetch-fonts.sh
  Warn "если шрифты не скачались — карта будет без подписей, это не критично"
} else { Ok "уже есть ($fontCount начертаний)" }

# ---------- 5. Тайлы ----------
Step "Тайлы карты (Planetiler, 3-10 минут на первый раз)"
if (Test-Path "data/sevastopol.mbtiles") {
  Ok "уже есть"
} else {
  docker compose --profile build run --rm planetiler
  if (-not (Test-Path "data/sevastopol.mbtiles")) { Die "Planetiler не смог собрать тайлы — смотри вывод выше." }
  Ok "тайлы собраны"
}

# ---------- 6. Стек ----------
Step "Поднимаю сервисы"
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Die "docker compose up не удался — смотри вывод выше." }
Ok "контейнеры запущены"

# ---------- 7. Ждём готовности ----------
$port = if ($env:PORT) { $env:PORT } else { "8080" }
$url = "http://localhost:$port"
Step "Жду GraphHopper (первый раз — импорт графа, 1-3 минуты)"
$ready = $false
for ($i = 1; $i -le 120; $i++) {
  try {
    $r = Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 3
    if ($r.Content -match '"graphhopper":\s*\{\s*"ok":\s*true') { $ready = $true; break }
  } catch { }
  Start-Sleep -Seconds 5
  if ($i % 6 -eq 0) { Write-Host "  ... ещё жду ($($i * 5) с)" }
}

if ($ready) { Ok "сервис готов" } else { Warn "не дождался за 10 минут: docker compose logs -f graphhopper" }

Write-Host ""
Write-Host "-> $url" -ForegroundColor Green
Write-Host "   логи: docker compose logs -f    остановить: docker compose down"
Start-Process $url
