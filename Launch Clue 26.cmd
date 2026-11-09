@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
python -m bhs_player.app --production "Clue 26"
if errorlevel 1 pause
