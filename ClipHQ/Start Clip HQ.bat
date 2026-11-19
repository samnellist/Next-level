@echo off
title Clip HQ - keep this window open
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Clip HQ is not installed yet. Double-click "Install Clip HQ.bat" first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run.py
if errorlevel 1 pause
