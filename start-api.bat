@echo off
rem Restart only the business API (port 8000). inference/web keep running.
set "ROOT=%~dp0"
start "YIYING api 8000" /d "%ROOT%server" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
exit /b 0
