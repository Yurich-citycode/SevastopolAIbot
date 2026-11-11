@echo off
rem Запуск всего сразу: карта + бот. Двойной клик - и всё.
setlocal
title Sevastopol AI - запуск
cd /d "%~dp0"

echo ============================================
echo   Sevastopol AI: карта + бот
echo ============================================
echo.

echo [1/5] Python
where python >nul 2>&1
if errorlevel 1 (
    echo   Нет Python. Поставь с python.org, при установке отметь "Add to PATH",
    echo   перезагрузи компьютер и запусти RUN.bat снова.
    echo.
    pause
    exit /b 1
)
echo   есть

echo.
echo [2/5] Библиотеки бота
python -c "import aiogram, pandas, openpyxl, requests, dotenv" >nul 2>&1
if errorlevel 1 (
    echo   ставлю, это один раз...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo   не получилось поставить. Проверь интернет и запусти снова.
        pause
        exit /b 1
    )
)
echo   на месте

echo.
echo [3/5] Настройки
if not exist ".env" (
    echo   файла .env нет - запускаю мастер настройки.
    echo   он спросит токен бота и твой Telegram ID.
    echo.
    python tools\setup_env.py
)

echo.
echo [4/5] Карта Севастополя
echo   открываю отдельное окно и жду, пока поднимется.
echo   первый раз это 10-20 минут, дальше - секунды.
start "Карта Севастополя" /D "%~dp0alive-maps-service" cmd /k start.bat

python tools\preflight.py --wait-map 1200

echo.
echo [5/5] Бот
start "Бот" /D "%~dp0" cmd /k python sevastopolaibot.py

echo.
echo ============================================
echo   Готово.
echo   Карта:  http://localhost:8080
echo   Бот:    открылся в отдельном окне, пиши ему в Telegram
echo.
echo   Окна не закрывай - пока они открыты, всё работает.
echo ============================================
echo.
pause
