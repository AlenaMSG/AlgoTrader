@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo.
echo ============================================================
echo  INSTRUCCIONES:
echo  1. Se abrira un browser de Alpaca
echo  2. El script rellenara el email y la contrasena SOLO
echo  3. Cuando pida el codigo 2FA, veras un mensaje aqui
echo     → Abre Google Authenticator en tu movil
echo     → Escribe el codigo asi en esta ventana:
echo         echo 123456 > Readme\mfa_code.txt
echo     (cambia 123456 por tu codigo real)
echo  4. El script continuara solo y guardara las keys
echo ============================================================
echo.
python get_api_keys.py
echo.
pause
