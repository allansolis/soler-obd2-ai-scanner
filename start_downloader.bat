@echo off
REM SOLER OBD2 AI Scanner - Drive Downloader Autostart
REM Descarga TODO el contenido automotriz a D:/Herramientas/SOLER/drive_downloads/
REM Se reinicia automaticamente hasta completar todas las descargas

cd /d D:\Herramientas\SOLER\soler-obd2-ai-scanner

:loop
echo [%DATE% %TIME%] Iniciando descarga del Drive...
python download_to_d.py 250 >> "D:\Herramientas\SOLER\logs\downloader.log" 2>&1
echo [%DATE% %TIME%] Downloader termino, esperando 60s para continuar...
timeout /t 60 /nobreak > nul
goto loop
