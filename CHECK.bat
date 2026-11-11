@echo off
rem Проверка перед запуском: что готово, а чего не хватает.
setlocal
title Sevastopol AI - проверка
cd /d "%~dp0"
python tools\preflight.py
echo.
pause
