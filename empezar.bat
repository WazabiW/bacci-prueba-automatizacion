@echo off
REM Windows: doble clic
cd /d "%~dp0"
python empezar.py %*
if errorlevel 1 pause
