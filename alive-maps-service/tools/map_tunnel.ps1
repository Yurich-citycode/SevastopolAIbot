# Публичный https-адрес для карты — одна команда (Windows / PowerShell)
#
#   Двойной клик по map_tunnel.bat или:
#   powershell -ExecutionPolicy Bypass -File tools\map_tunnel.ps1
#
# Что делает: находит или скачивает cloudflared, поднимает туннель до карты,
# вписывает адрес в .env бота как ALIVE_MAP_PUBLIC и висит в этом окне.
$ErrorActionPreference = "Continue"
$ServiceDir = Split-Path $PSScriptRoot -Parent
Set-Location $ServiceDir

$Port = if ($env:PORT) { $env:PORT } else { "8080" }
$EnvFile = Join-Path (Split-Path $ServiceDir -Parent) ".env"
$Bin = Join-Path $ServiceDir "cloudflared.exe"

function Ok([string]$m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "  [!] $m" -ForegroundColor Yellow }
function Die([string]$m)  { Write-Host ""; Write-Host "[x] $m" -ForegroundColor Red; Read-Host "Enter, чтобы закрыть"; exit 1 }

# ---------- 1. cloudflared ----------
$cf = (Get-Command cloudflared -ErrorAction SilentlyContinue)
if ($cf) {
    $Exe = $cf.Source
} elseif (Test-Path $Bin) {
    $Exe = $Bin
} else {
    Write-Host "Скачиваю cloudflared (один раз, ~35 МБ)..."
    try {
        Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $Bin -UseBasicParsing
    } catch {
        Die "не скачалось. Проверь интернет или скачай вручную: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
    }
    $Exe = $Bin
}
Ok "cloudflared: $Exe"

# ---------- 2. сервис отвечает? ----------
try {
    Invoke-WebRequest -Uri "http://localhost:$Port/health" -UseBasicParsing -TimeoutSec 4 | Out-Null
} catch {
    Warn "карта на localhost:$Port не отвечает - туннель всё равно подниму,"
    Warn "но сначала запусти сервис: start.bat"
}

# ---------- 3. туннель ----------
$log = Join-Path ([IO.Path]::GetTempPath()) "alive-tunnel.log"
if (Test-Path $log) { Remove-Item $log -Force }

Write-Host ""
Write-Host "Поднимаю туннель до http://localhost:$Port ..." -ForegroundColor Cyan
Write-Host "Окно не закрывай: пока оно живо, карта открывается с телефона."
Write-Host ""

$proc = Start-Process -FilePath $Exe `
    -ArgumentList @("tunnel", "--url", "http://localhost:$Port", "--no-autoupdate") `
    -RedirectStandardError $log -RedirectStandardOutput "$log.out" -PassThru -NoNewWindow

$url = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 700
    foreach ($file in @($log, "$log.out")) {
        if (Test-Path $file) {
            $text = Get-Content $file -Raw -ErrorAction SilentlyContinue
            if ($text -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
                $url = $Matches[0]
                break
            }
        }
    }
    if ($url) { break }
    if ($proc.HasExited) { break }
}

if ($url) {
    # ---------- 4. адрес в .env ----------
    $line = "ALIVE_MAP_PUBLIC=$url"
    if (Test-Path $EnvFile) {
        $content = Get-Content $EnvFile
        if ($content -match '^ALIVE_MAP_PUBLIC=') {
            $content = $content -replace '^ALIVE_MAP_PUBLIC=.*', $line
        } else {
            $content += ""
            $content += $line
        }
        [IO.File]::WriteAllLines($EnvFile, $content, (New-Object System.Text.UTF8Encoding($false)))
    } else {
        [IO.File]::WriteAllText($EnvFile, "$line`r`n", (New-Object System.Text.UTF8Encoding($false)))
    }
    Ok "адрес записан в $EnvFile"

    Write-Host ""
    Write-Host "  Карта теперь здесь: $url" -ForegroundColor Green
    Write-Host "  Дальше: перезапусти бота, потом в @BotFather -> /setmenubutton -> этот адрес."
    Write-Host ""
} else {
    Warn "не поймал адрес в выводе cloudflared - смотри файл $log"
}

if (-not $proc.HasExited) {
    Write-Host "Туннель работает. Ctrl+C - остановить." -ForegroundColor DarkGray
    $proc.WaitForExit()
}
