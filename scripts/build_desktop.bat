@echo off
chcp 65001 >nul
cd /d "%~dp0\.."

echo === Сборка AkelaNormativSync.exe (нужен Windows) ===
python -m pip install -q -r requirements.txt -r requirements-desktop.txt
pyinstaller --noconfirm desktop_sync\AkelaNormativSync.spec

mkdir release 2>nul
copy /Y dist\AkelaNormativSync.exe release\
copy /Y scripts\install_windows_autostart.bat release\
copy /Y desktop_sync\README.txt release\
powershell Compress-Archive -Path release\* -DestinationPath AkelaNormativSync-Windows.zip -Force

echo.
echo Готово: AkelaNormativSync-Windows.zip
pause
