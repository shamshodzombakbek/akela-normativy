#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 не найден. Установите Python 3.9+"
  read -r -p "Enter..."
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Файл .env не найден. Скопируйте env.example в .env и заполните."
  read -r -p "Enter..."
  exit 1
fi

echo "Установка зависимостей..."
python3 -m pip install -q -r requirements.txt

echo ""
echo "Загрузка с Диска Битрикс24..."
python3 run_fetch.py --force "$@"
ERR=$?

echo ""
if [[ $ERR -eq 0 ]]; then echo "Готово."; else echo "Ошибка, код $ERR."; fi
read -r -p "Enter..."
