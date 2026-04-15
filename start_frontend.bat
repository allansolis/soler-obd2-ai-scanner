@echo off
REM SOLER OBD2 AI Scanner - Frontend Autostart
REM Reinicia automaticamente si se cae

cd /d D:\Herramientas\SOLER\soler-obd2-ai-scanner\frontend

:loop
echo [%DATE% %TIME%] Starting SOLER frontend...
call npm run dev >> "D:\Herramientas\SOLER\logs\frontend.log" 2>&1
echo [%DATE% %TIME%] Frontend stopped, restarting in 5s...
timeout /t 5 /nobreak > nul
goto loop
