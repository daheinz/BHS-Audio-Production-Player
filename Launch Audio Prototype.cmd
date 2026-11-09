@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
python -m bhs_player.app --production "Audio Prototype"
if errorlevel 1 pause
