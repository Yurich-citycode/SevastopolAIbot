@echo off
rem Тест-бот виджетов: двойной клик - и он в Telegram.
rem Главный бот не трогается: это отдельный файл и отдельный токен.
setlocal
title Тест-бот виджетов
cd /d "%~dp0"

echo ============================================
echo   Тест-бот виджетов (Bot API 10.4)
echo ============================================
echo.

echo [1/4] Python
where python >nul 2>&1
if errorlevel 1 (
    echo   Нет Python. Поставь с python.org, при установке отметь "Add to PATH",
    echo   перезагрузи компьютер и запусти снова.
    echo.
    pause
    exit /b 1
)
echo   есть

echo.
echo [2/4] Библиотеки
python -c "import requests, pandas, openpyxl" >nul 2>&1
if errorlevel 1 (
    echo   ставлю, это один раз...
    python -m pip install requests pandas openpyxl
    if errorlevel 1 (
        echo   не получилось поставить. Проверь интернет и запусти снова.
        pause
        exit /b 1
    )
)
echo   на месте

echo.
echo [3/4] Токен тестового бота
if exist "widgets\token.txt" goto have_token
echo   Нужен ОТДЕЛЬНЫЙ бот: в Telegram открой @BotFather и нажми /newbot.
echo   Токен основного бота не подойдёт: два бота на одном токене мешают друг другу.
echo.
set /p TOKEN=  Вставь токен и нажми Enter: 
if "%TOKEN%"=="" (
    echo   Пусто. Запусти заново, когда будет токен.
    pause
    exit /b 1
)
> "widgets\token.txt" echo %TOKEN%
echo   сохранил в widgets\token.txt (в git не попадает)
:have_token

echo.
echo [4/4] Запуск
echo   Дальше: в Telegram найди своего тестового бота и нажми Start.
echo   Если вместо карточки пришёл текст - обнови Telegram до последней версии.
echo.
echo   Это окно не закрывай: пока оно открыто, бот работает.
echo   Остановить - Ctrl+C или закрыть окно.
echo.
python testbotwidgets.py
echo.
echo Бот остановлен.
pause
