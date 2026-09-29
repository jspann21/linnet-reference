@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" linnet media
) else (
    python linnet media
)
if errorlevel 1 pause
