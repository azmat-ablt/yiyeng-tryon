@echo off
set "ROOT=%~dp0"
start "YIYING inference 9000" /d "%ROOT%inference" cmd /k ".venv\Scripts\python.exe -m uvicorn service:app --host 127.0.0.1 --port 9000"
start "YIYING api 8000" /d "%ROOT%server" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "YIYING web 3000" /d "%ROOT%web" cmd /k "C:\Users\lenovo\nodejs\node.exe node_modules\next\dist\bin\next dev"
exit /b 0
