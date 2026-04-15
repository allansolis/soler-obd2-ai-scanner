@echo off
REM SOLER OBD2 AI Scanner - Backend Autostart
REM Reinicia automaticamente si se cae

cd /d D:\Herramientas\SOLER\soler-obd2-ai-scanner

:loop
echo [%DATE% %TIME%] Starting SOLER backend...
python -m uvicorn backend.api.server:app --host 0.0.0.0 --port 8000 >> "D:\Herramientas\SOLER\logs\backend.log" 2>&1
echo [%DATE% %TIME%] Backend stopped, restarting in 5s...
timeout /t 5 /nobreak > nul
goto loop
