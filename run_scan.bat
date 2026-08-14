@echo off
REM AlgoTrader — Scanner diario S&P100
REM Añadir al Task Scheduler de Windows para ejecución automática.
REM
REM Configuración sugerida en Task Scheduler:
REM   Trigger : Diariamente a las 09:45 (15 min después de apertura US)
REM   Acción  : Iniciar programa
REM   Programa: C:\proyectos\AlgoTrader\run_scan.bat
REM   Inicio en: C:\proyectos\AlgoTrader

cd /d "%~dp0"
echo [%date% %time%] Iniciando scan S^&P100...
.venv\Scripts\python.exe scan_sp100.py >> scan_log_console.txt 2>&1
echo [%date% %time%] Scan completado.
