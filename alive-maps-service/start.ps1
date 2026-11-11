# Sevastopol Alive Maps — запуск одной командой (Windows / PowerShell)
# Двойной клик по start.bat делает то же самое.
# Подробная инструкция: SETUP.md
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Say([string]$m)  { Write-Host $m }
function Step([string]$m) { Write-Host ""; Write-Host "> $m" -ForegroundColor Cyan }
function Ok([string]$m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "  [!] $m" -ForegroundColor Yellow }
function Die([string]$m)  { Write-Host ""; Write-Host "[x] $m" -ForegroundColor Red; Read-Host "Enter, чтобы закрыть"; exit 1 }

# Docker Desktop иногда не попадает в PATH до перезагрузки — ищем по стандартным местам
foreach ($p in @(
    "$env:ProgramFiles\Docker\Docker\resources\bin",
    "$env:LOCALAPPDATA\Programs\Docker\Docker\resources\bin",
    "$env:ProgramFiles\RedHat\Podman"
)) {
  if ((Test-Path $p) -and ($env:Path -notlike "*$p*")) { $env:Path = "$p;$env:Path" }
}

Say "Sevastopol Alive Maps - локальная карта с живыми маршрутами"

# ---------- 1. Docker / Podman ----------
Step "Проверяю Docker (или Podman)"

# $script:DC — имя движка. compose вызываем напрямую (& $script:DC compose ...),
# без функций-обёрток: PowerShell иначе калечит аргументы вида --no-TTY.
$script:DC = $null
if (Get-Command docker -ErrorAction SilentlyContinue) {
  docker compose version *> $null
  if ($LASTEXITCODE -eq 0) { $script:DC = 'docker' }
}
if (-not $script:DC -and (Get-Command podman -ErrorAction SilentlyContinue)) {
  podman compose version *> $null
  if ($LASTEXITCODE -eq 0) { $script:DC = 'podman' }
}
if (-not $script:DC) {
  Die "Не найден ни Docker, ни Podman.`n`n  Если Docker Desktop только что установлен - ПЕРЕЗАГРУЗИ компьютер`n  (или выйди и зайди в аккаунт Windows) и запусти start.bat снова:`n  установщик прописывает docker в PATH только после входа в систему.`n`n  Другие варианты:`n   1) Docker Desktop   https://www.docker.com/products/docker-desktop/`n   2) Podman Desktop   https://podman-desktop.io/downloads   (аналог, без лицензии Docker)`n   3) Docker внутри Ubuntu (WSL): sudo apt install docker.io`n   4) совсем без контейнеров - см. SETUP.md, вариант D"
}

& $script:DC info *> $null
if ($LASTEXITCODE -ne 0) {
  Die "$($script:DC) установлен, но не запущен.`n  Открой $($script:DC) Desktop (значок в трее), дождись 'Engine running' и повтори."
}
Ok "готово: $($script:DC) compose"

# Одноразовый контейнер tools. Флаг TTY в разных версиях compose называется
# по-разному, поэтому сначала обычный запуск, при ошибке - повтор с -T.
function ToolRun([string[]]$cmd) {
  & $script:DC compose --profile build run --rm tools @cmd
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  повтор с -T ..." -ForegroundColor DarkGray
    & $script:DC compose --profile build run --rm -T tools @cmd
  }
}

# ---------- 2. Данные ----------
Step "Данные OpenStreetMap для Севастополя (~39 МБ)"
if (Test-Path "data/sevastopol.osm.pbf") {
  Ok "уже есть"
} else {
  ToolRun @('sh', '/scripts/01-fetch-pbf.sh')
  if (-not (Test-Path "data/sevastopol.osm.pbf")) {
    Die "Не удалось скачать данные.`n`n  Если дело в сети - скачай вручную в браузере:`n  https://download.geofabrik.de/russia/crimean-fed-district-latest.osm.pbf`n  положи файл в папку data под именем sevastopol.osm.pbf и запусти start.bat снова."
  }
  Ok "скачано"
}

# ---------- 3. Зоны ----------
Step "Живые зоны: парки, кафе, набережные, история"
$needZones = $true
if (Test-Path "data/zones.geojson") {
  if ((Get-Item "data/zones.geojson").LastWriteTime -gt (Get-Item "data/sevastopol.osm.pbf").LastWriteTime) { $needZones = $false }
}
if ($needZones) {
  ToolRun @('python', '/scripts/02-build-zones.py', '/data/sevastopol.osm.pbf', '-o', '/data/zones.geojson')
  if (-not (Test-Path "data/zones.geojson")) { Die "Не удалось собрать зоны - смотри ошибку выше." }
  Ok "собрано"
} else { Ok "уже есть" }

# ---------- 4. Шрифты ----------
Step "Шрифты для подписей на карте"
$fontCount = 0
if (Test-Path "data/fonts") { $fontCount = (Get-ChildItem "data/fonts" -Directory | Measure-Object).Count }
if ($fontCount -eq 0) {
  ToolRun @('sh', '/scripts/03-fetch-fonts.sh')
  Warn "если шрифты не скачались - карта будет без подписей, это не критично"
} else { Ok "уже есть ($fontCount начертаний)" }

# ---------- 5. Тайлы ----------
Step "Тайлы карты (Planetiler, 3-10 минут на первый раз)"
if (Test-Path "data/sevastopol.mbtiles") {
  Ok "уже есть"
} else {
  & $script:DC compose --profile build run --rm planetiler
  if (-not (Test-Path "data/sevastopol.mbtiles")) { Die "Planetiler не смог собрать тайлы - смотри вывод выше." }
  Ok "тайлы собраны"
}

# ---------- 6. Стек ----------
Step "Поднимаю сервисы"
& $script:DC compose up -d --build
if ($LASTEXITCODE -ne 0) { Die "compose up не удался - смотри вывод выше." }
Ok "контейнеры запущены"

# ---------- 7. Ждём готовности ----------
$port = if ($env:PORT) { $env:PORT } else { "8080" }
$url = "http://localhost:$port"
Step "Жду GraphHopper (первый раз - импорт графа, 1-3 минуты)"
$ready = $false
for ($i = 1; $i -le 120; $i++) {
  try {
    $r = Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 3
    if ($r.Content -match '"graphhopper":\s*\{\s*"ok":\s*true') { $ready = $true; break }
  } catch { }
  Start-Sleep -Seconds 5
  if ($i % 6 -eq 0) { Write-Host "  ... ещё жду ($($i * 5) с)" }
}

if ($ready) { Ok "сервис готов" } else { Warn "не дождался за 10 минут: $($script:DC) compose logs -f graphhopper" }

Write-Host ""
Write-Host "-> $url" -ForegroundColor Green
Write-Host "   логи: $($script:DC) compose logs -f    остановить: $($script:DC) compose down"
Write-Host "   инструкция: SETUP.md"
Start-Process $url
