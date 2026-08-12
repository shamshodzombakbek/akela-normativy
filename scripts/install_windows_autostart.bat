@echo off
chcp 65001 >nul
REM Установка автозапуска (запускать из папки с AkelaNormativSync.exe)

set "EXE=%~dp0AkelaNormativSync.exe"
if not exist "%EXE%" (
  echo Файл AkelaNormativSync.exe не найден в этой папке.
  pause
  exit /b 1
)

schtasks /Create /TN "AkelaNormativSync" /TR "\"%EXE%\" --background" /SC ONLOGON /RL LIMITED /F
if errorlevel 1 (
  echo Не удалось создать задачу. Запустите от имени администратора.
  pause
  exit /b 1
)

echo Готово: программа будет работать в фоне при входе в Windows.
echo Один раз откройте AkelaNormativSync.exe и сохраните настройки.
pause
