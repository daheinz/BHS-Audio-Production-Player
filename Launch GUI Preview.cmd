@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
python -m bhs_player.app --gui-preview
if errorlevel 1 pause
