@echo off
REM Copia server-side TODO lo automotriz al Drive del usuario
REM Origen: H: (compartido) -> Destino: G:\SOLER_WORKSPACE\ (mi unidad 2TB)

set PATH=%PATH%;C:\Users\andre\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.73.4-windows-amd64
set LOG=D:\Herramientas\SOLER\logs\copy_all.log

echo [%DATE% %TIME%] Copiando TODO automotriz a Mi Drive... >> %LOG%

REM 1. 4LAP - Arquivos (49 GB)
echo [%DATE% %TIME%] Copiando 4LAP... >> %LOG%
rclone copy soler_shared:"4LAP - Arquivos" soler:"SOLER_WORKSPACE/4LAP" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 2. ECM PINOUT 8.0 (62 GB)
echo [%DATE% %TIME%] Copiando ECM PINOUT 8.0... >> %LOG%
rclone copy soler_shared:"ECM PINOUT 8.0" soler:"SOLER_WORKSPACE/ECM_PINOUT_8" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 3. PROGRAMAS AUTOMOTRICES
echo [%DATE% %TIME%] Copiando PROGRAMAS AUTOMOTRICES... >> %LOG%
rclone copy soler_shared:"PROGRAMAS AUTOMOTRICES" soler:"SOLER_WORKSPACE/PROGRAMAS_AUTOMOTRICES" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 4. DIAGRAMAS ELECTRICOS
echo [%DATE% %TIME%] Copiando DIAGRAMAS ELECTRICOS... >> %LOG%
rclone copy soler_shared:"DIAGRAMAS ELECTRICOS" soler:"SOLER_WORKSPACE/DIAGRAMAS_ELECTRICOS" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 5. MANUALES DE USUARIO
echo [%DATE% %TIME%] Copiando MANUALES DE USUARIO... >> %LOG%
rclone copy soler_shared:"MANUALES DE USUARIO" soler:"SOLER_WORKSPACE/MANUALES_USUARIO" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 6. MANUALES Y DIAGRAMAS MOTOS
echo [%DATE% %TIME%] Copiando MANUALES Y DIAGRAMAS MOTOS... >> %LOG%
rclone copy soler_shared:"MANUALES Y DIAGRAMAS MOTOS" soler:"SOLER_WORKSPACE/MANUALES_MOTOS" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 7. DICATEC + ATIVADOR
echo [%DATE% %TIME%] Copiando DICATEC... >> %LOG%
rclone copy soler_shared:"DICATEC + ATIVADOR  NA PASTA TODOS ATIVADORES" soler:"SOLER_WORKSPACE/DICATEC" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 8. IMMO CODE CALC
echo [%DATE% %TIME%] Copiando IMMO CODE CALC... >> %LOG%
rclone copy soler_shared:"IMMO CODE CALC SERVICE DIAGN PROG " soler:"SOLER_WORKSPACE/IMMO_CODE_CALC" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 9. Mercedes C280 AMG 2008 (del usuario)
echo [%DATE% %TIME%] Copiando Mercedes C280 AMG 2008... >> %LOG%
rclone copy soler_shared:"Mercedes C280 AMG 2008" soler:"SOLER_WORKSPACE/Mercedes_C280_AMG_2008" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 10. 01 - MECANICA 2020
echo [%DATE% %TIME%] Copiando 01 MECANICA 2020... >> %LOG%
rclone copy soler_shared:"01 - MECÂNICA 2020" soler:"SOLER_WORKSPACE/MECANICA_2020_01" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 11. 02 - Mecanica 2020
echo [%DATE% %TIME%] Copiando 02 Mecanica 2020... >> %LOG%
rclone copy soler_shared:"02 - Mecânica 2020" soler:"SOLER_WORKSPACE/MECANICA_2020_02" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 12. 01 - SIMPLO CELULAR
echo [%DATE% %TIME%] Copiando SIMPLO CELULAR... >> %LOG%
rclone copy soler_shared:"01 - SIMPLO CELULAR" soler:"SOLER_WORKSPACE/SIMPLO_CELULAR" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 13. 97 - Programa TecnoCar
echo [%DATE% %TIME%] Copiando TecnoCar... >> %LOG%
rclone copy soler_shared:"97 - Programa - TecnoCar" soler:"SOLER_WORKSPACE/TecnoCar" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 14. 98 - Programa Simplo 2022
echo [%DATE% %TIME%] Copiando Simplo 2022... >> %LOG%
rclone copy soler_shared:"98 - Programa - Simplo 2022" soler:"SOLER_WORKSPACE/Simplo_2022" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

REM 15. DOUTOR-IE.rar
echo [%DATE% %TIME%] Copiando DOUTOR-IE... >> %LOG%
rclone copy soler_shared:"DOUTOR-IE.rar" soler:"SOLER_WORKSPACE/DOUTOR-IE.rar" --drive-server-side-across-configs --log-file %LOG% --log-level INFO --stats 60s --transfers 16 --checkers 16

echo [%DATE% %TIME%] TODAS LAS COPIAS COMPLETADAS >> %LOG%
