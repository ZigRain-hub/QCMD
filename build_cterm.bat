@echo off

rem# QULW Terminal
rem# Copyright (c) 2026 [ZigRain-hub]
rem# Licensed under the MIT License. See LICENSE file for details.
rem ============================================================
rem ДЛЯ open source, что делает сборщик и qcmd (кратко)
rem  build_cterm.bat - сборка ОДНОГО exe, который сам себя устанавливает
rem
rem  cterm.exe (QCMD) при первом запуске сам:
rem    1) копирует себя в %LOCALAPPDATA%\QCmd
rem    2) прописывает Win+R -> QCmd (App Paths)
rem    3) создаёт ярлык QCmd на рабочем столе
rem    4) запускает установленную копию
rem
rem  Положи РЯДОМ с cterm.py
rem  Запуск:  build_cterm.bat          - обычная сборка
rem           build_cterm.bat clean    - снести venv и собрать с нуля
rem           build_cterm.bat noupx    - без UPX
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

set SCRIPT=cterm.py
if not exist %SCRIPT% (
    echo ОШИБКА: %SCRIPT% не найден
    pause
    exit /b 1
)

if /i "%1"=="clean" (
    echo [0/7] Чищу venv и результаты...
    rmdir /s /q .venv-cterm 2>nul
    rmdir /s /q build 2>nul
    rmdir /s /q dist 2>nul
)
set NOUPX=0
if /i "%1"=="noupx" set NOUPX=1

set ICONOPT=
if exist icon.ico set ICONOPT=--icon icon.ico

echo [1/6] Python:
python -V || goto :err
python -c "import sys;sys.exit(0 if sys.maxsize>2**32 else 1)" || (
    echo ОШИБКА: нужен 64-битный Python
    goto :err
)

if exist .venv-cterm\Scripts\activate.bat (
    echo [2/6] venv уже есть ^(снести: build_cterm.bat clean^)
) else (
    echo [2/6] Создаю venv
    python -m venv .venv-cterm || goto :err
)
call .venv-cterm\Scripts\activate.bat || goto :err

echo [3/6] Зависимости
python -m pip install --upgrade pip >nul 2>nul
pip install --disable-pip-version-check -q pyinstaller PySide6-Essentials PySideSix-Frameless-Window pyte PyWinPTY psutil || goto :err

rem --- UPX -
set UPXOPT=--upx-exclude "python*.dll" --upx-exclude "vcruntime*.dll" --upx-exclude "ucrtbase.dll"
set UPXDIR=
if "%NOUPX%"=="1" (
    echo [4/6] UPX отключён
    goto :upx_done
)
where upx >nul 2>nul
if not errorlevel 1 (
    echo [4/6] UPX найден в PATH
    set UPXDIR=PATH
    goto :upx_done
)
if exist upx.exe (
    echo [4/6] UPX найден рядом со скриптом
    set UPXDIR=.
    goto :upx_done
)
echo [4/6] UPX не найден для оптимизации
:upx_done
if "%UPXDIR%"=="." set UPXOPT=--upx-dir . %UPXOPT%

echo [5/6] Собрка QCMD.exe (self-installing)...
pyinstaller --noconfirm --onefile --windowed --name cterm %ICONOPT% %SCRIPT% ^
  --collect-all qframelesswindow ^
  --collect-all winpty ^
  --collect-all pyte ^
  --exclude-module numpy --exclude-module sounddevice --exclude-module pyaudiowpatch ^
  --exclude-module tkinter --exclude-module matplotlib --exclude-module pandas ^
  --exclude-module scipy --exclude-module IPython --exclude-module pytest ^
  --exclude-module PyQt5 --exclude-module PyQt6 %UPXOPT% || goto :err

echo.
echo Готово
echo в %%LOCALAPPDATA%%\QCmd, пропишет Win+R -^> QCmd и ярлык на рабочем столе.
pause
exit /b 0

:err
echo.
echo ОШИБКА СБОРКИ
pause
exit /b 1
