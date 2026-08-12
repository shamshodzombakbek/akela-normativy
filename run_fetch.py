#!/usr/bin/env python3
"""
Запуск загрузки Normativ с Диска Битрикс24 на любом компьютере.

Нужны: Python 3.9+, папка проекта, файл .env (см. env.example).

Примеры:
  python run_fetch.py --force
  python run_fetch.py --force --day 2026-08-12
  python run_fetch.py --force --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("дата в формате YYYY-MM-DD") from exc


def main(argv: list[str] | None = None) -> int:
    from schedule import (
        active_window_day,
        bitrix_target_day,
        is_fetch_window,
        now_tashkent,
        status_label,
    )
    from bitrix_fetch import fetch_normativs

    parser = argparse.ArgumentParser(
        description="Загрузить Normativ с Диска Битрикс24 и опубликовать на дашборде.",
    )
    parser.add_argument(
        "--day",
        type=_parse_day,
        default=None,
        help="Слот дашборда (YYYY-MM-DD). По умолчанию — текущий слот по Ташкенту.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Запустить вне окна 16:00–18:30 (для ручного запуска).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только прочитать Диск, без публикации на сайт.",
    )
    parser.add_argument(
        "--no-replace",
        action="store_true",
        help="Не заменять существующие записи дня (добавить к имеющимся).",
    )
    args = parser.parse_args(argv)

    now = now_tashkent()
    window_day = args.day or active_window_day(now)
    target = bitrix_target_day(window_day)

    print(now.isoformat(), status_label(now))
    print(f"window_day={window_day} · disk_folder={target.isoformat()}")

    if not args.force and not is_fetch_window(now):
        print(
            "Сейчас не окно 16:00–18:30 (Ташкент). "
            "Добавьте --force для ручного запуска."
        )
        return 2

    result = fetch_normativs(
        window_day,
        publish=not args.dry_run,
        replace=not args.no_replace,
    )
    for msg in result.get("messages") or []:
        print("-", msg)

    if not result.get("ok"):
        print("ERROR: не удалось загрузить файлы с Диска.")
        return 1

    action = "dry-run" if args.dry_run else "published"
    print(f"OK ({action}) count={result.get('count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
