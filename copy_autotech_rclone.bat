@echo off
REM Copia los 14 folders AutoTech al Drive usando rclone server-side
REM Los nombres EXACTOS como aparecen en shared-with-me

set PATH=%PATH%;C:\Users\andre\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.73.4-windows-amd64
set LOG=D:\Herramientas\SOLER\logs\copy_autotech_rclone.log
set FLAGS=--drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 30s --transfers 16 --checkers 16 --retries 5 --low-level-retries 10

echo [%DATE% %TIME%] Iniciando copia autotech via rclone... >> %LOG%

rclone copy soler_shared:"ALLDATA 2014" soler:"SOLER_WORKSPACE/AUTOTECH/ALLDATA_2014" %FLAGS%
rclone copy soler_shared:"ARCHIVOS VARIADOS" soler:"SOLER_WORKSPACE/AUTOTECH/ARCHIVOS_VARIADOS" %FLAGS%
rclone copy soler_shared:"DIAGRAMAS ELECTRICOS" soler:"SOLER_WORKSPACE/AUTOTECH/DIAGRAMAS_ELECTRICOS" %FLAGS%
rclone copy soler_shared:"MANUALES DE MOTOR" soler:"SOLER_WORKSPACE/AUTOTECH/MANUALES_DE_MOTOR" %FLAGS%
rclone copy soler_shared:"MANUALES DE USUARIO" soler:"SOLER_WORKSPACE/AUTOTECH/MANUALES_DE_USUARIO" %FLAGS%
rclone copy soler_shared:"MANUALES DE TRANSMISIONES" soler:"SOLER_WORKSPACE/AUTOTECH/MANUALES_DE_TRANSMISIONES" %FLAGS%
rclone copy soler_shared:"MANUALES DE TALLER" soler:"SOLER_WORKSPACE/AUTOTECH/MANUALES_DE_TALLER" %FLAGS%
rclone copy soler_shared:"MARCAS AMERICA" soler:"SOLER_WORKSPACE/AUTOTECH/MARCAS_AMERICA" %FLAGS%
rclone copy soler_shared:"MARCAS ASIA" soler:"SOLER_WORKSPACE/AUTOTECH/MARCAS_ASIA" %FLAGS%
rclone copy soler_shared:"MARCAS EUROPA" soler:"SOLER_WORKSPACE/AUTOTECH/MARCAS_EUROPA" %FLAGS%
rclone copy soler_shared:"PINOUT - ECUS" soler:"SOLER_WORKSPACE/AUTOTECH/PINOUT_ECUS" %FLAGS%
rclone copy soler_shared:"PINOUT - TABLEROS" soler:"SOLER_WORKSPACE/AUTOTECH/PINOUT_TABLEROS" %FLAGS%
rclone copy soler_shared:"TORQUES MOTORES PESADOS" soler:"SOLER_WORKSPACE/AUTOTECH/TORQUES_MOTORES_PESADOS" %FLAGS%
rclone copy soler_shared:"MANUALES Y DIAGRAMAS MOTOS" soler:"SOLER_WORKSPACE/AUTOTECH/MANUALES_Y_DIAGRAMAS_MOTOS" %FLAGS%

echo [%DATE% %TIME%] Copia AUTOTECH completada >> %LOG%
