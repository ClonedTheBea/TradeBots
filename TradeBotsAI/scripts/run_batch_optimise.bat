@echo off
setlocal

cd /d "%~dp0\.."

if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"
if exist "venv\Scripts\activate.bat" call "venv\Scripts\activate.bat"

if not exist "logs" mkdir "logs"

py -m app.main batch-optimise >> "logs\batch_optimise_task.log" 2>&1

endlocal
