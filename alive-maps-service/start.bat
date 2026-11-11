@echo off
chcp 65001 >nul
title Sevastopol Alive Maps
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
echo.
pause
