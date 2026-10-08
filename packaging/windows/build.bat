@echo off
setlocal
cd /d "%~dp0\..\.."
py -m PyInstaller --noconfirm --clean --windowed --onefile --name Purify --uac-admin purify.py
if errorlevel 1 exit /b %errorlevel%
echo Artefato: dist\Purify.exe
 echo Valide em VMs Windows suportadas antes de distribuir.
