@echo off
cd /d "%~dp0"
python linnet media
if errorlevel 1 pause
