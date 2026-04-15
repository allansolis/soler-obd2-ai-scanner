@echo off
REM Copia TODO lo compartido conmigo al Drive del usuario
REM Usa rclone copy recursivo de toda H: a G:\SOLER_WORKSPACE\

set PATH=%PATH%;C:\Users\andre\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.73.4-windows-amd64
set LOG=D:\Herramientas\SOLER\logs\copy_ALL_shared.log

echo [%DATE% %TIME%] Copiando TODO shared-with-me a Mi Drive... >> %LOG%
echo Origen: soler_shared: (todo Compartido conmigo) >> %LOG%
echo Destino: soler:SOLER_WORKSPACE_COMPLETO (Mi Drive 2TB) >> %LOG%
echo. >> %LOG%

rclone copy soler_shared: soler:"SOLER_WORKSPACE_COMPLETO" ^
  --drive-server-side-across-configs ^
  --log-file %LOG% ^
  --log-level INFO ^
  --stats 60s ^
  --transfers 32 ^
  --checkers 32 ^
  --drive-pacer-min-sleep 5ms ^
  --drive-pacer-burst 500

echo [%DATE% %TIME%] Copia TOTAL completada >> %LOG%
