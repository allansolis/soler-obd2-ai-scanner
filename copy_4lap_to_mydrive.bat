@echo off
REM Copia server-side "4LAP - Arquivos" al Drive del usuario
REM No descarga/sube - es copia directa dentro de Google servers (rapido)

set PATH=%PATH%;C:\Users\andre\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.73.4-windows-amd64

echo [%DATE% %TIME%] Iniciando copia server-side de 4LAP - Arquivos...
echo Origen: H:\ (shared)
echo Destino: G:\SOLER_WORKSPACE\4LAP (mi unidad)
echo.

rclone copy soler_shared:"4LAP - Arquivos" soler:"SOLER_WORKSPACE/4LAP" ^
  --drive-server-side-across-configs ^
  --log-file "D:\Herramientas\SOLER\logs\copy_4lap.log" ^
  --log-level INFO ^
  --stats 30s ^
  --transfers 16 ^
  --checkers 16

echo [%DATE% %TIME%] Copia completada
