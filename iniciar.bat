@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo O ambiente Python nao foi encontrado. Consulte README.md.
    pause
    exit /b 1
)
"venv\Scripts\python.exe" main.py
if errorlevel 1 pause
