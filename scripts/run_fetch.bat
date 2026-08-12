@echo off
chcp 65001 >nul
cd /d "%~dp0\.."

where python >nul 2>&1
if errorlevel 1 (
  echo Python не найден. Установите Python 3.9+ с python.org
  pause
  exit /b 1
)

if not exist ".env" (
  echo Файл .env не найден. Скопируйте env.example в .env и заполните.
  pause
  exit /b 1
)

echo Установка зависимостей...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo Ошибка pip install
  pause
  exit /b 1
)

echo.
echo Загрузка с Диска Битрикс24...
python run_fetch.py --force %*
set ERR=%ERRORLEVEL%

echo.
if %ERR%==0 (echo Готово.) else (echo Ошибка, код %ERR%.)
pause
exit /b %ERR%
