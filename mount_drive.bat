@echo off
REM SOLER - Mount Google Drive como G:
REM Se auto-reintenta si falla

cd /d D:\Herramientas\SOLER

set PATH=%PATH%;C:\Users\andre\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.73.4-windows-amd64

:loop
echo [%DATE% %TIME%] Montando Drive como G:...
rclone mount soler: G: --vfs-cache-mode full --vfs-cache-max-size 20G --drive-chunk-size 64M --buffer-size 128M --dir-cache-time 1h --log-file "D:\Herramientas\SOLER\logs\mount.log" --log-level INFO
echo [%DATE% %TIME%] Mount desmontado, reintentando en 5s...
timeout /t 5 /nobreak > nul
goto loop
