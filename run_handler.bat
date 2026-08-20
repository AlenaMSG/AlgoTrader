@echo off
REM AlgoTrader — Telegram Bot Handler
REM Escucha comandos de Telegram y ejecuta órdenes en Alpaca.
REM
REM Dejar corriendo en background o añadir al Task Scheduler como tarea
REM "Al iniciar sesión" para que arranque automáticamente.
REM
REM   Programa: C:\proyectos\AlgoTrader\run_handler.bat
REM   Inicio en: C:\proyectos\AlgoTrader

cd /d "%~dp0"
echo [%date% %time%] Iniciando AlgoTrader Telegram Handler...
.venv\Scripts\python.exe telegram_handler.py
echo [%date% %time%] Handler detenido.
pause
