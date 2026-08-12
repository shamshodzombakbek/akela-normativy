#!/usr/bin/env python3
"""
Локальный скрипт: в окне 16:00–20:00 (Ташкент) качает Normativ из Битрикс
за вчера и сохраняет снимок дня на Общий диск.

Запуск по cron каждые 10–15 минут, например:
*/10 16-19 * * * cd "/Users/habibullaevnurbek/Akela group" && /usr/bin/python3 fetch_scheduler.py >> logs/fetch.log 2>&1
0 20 * * * cd "/Users/habibullaevnurbek/Akela group" && /usr/bin/python3 fetch_scheduler.py >> logs/fetch.log 2>&1
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from schedule import (  # noqa: E402
    active_window_day,
    bitrix_target_day,
    is_fetch_window,
    now_tashkent,
    status_label,
)
from shared_store import load_day, publish_day_snapshot  # noqa: E402
from utils import load_excel_reports_from_dir  # noqa: E402


def main() -> int:
    now = now_tashkent()
    print(now.isoformat(), status_label(now))
    if not is_fetch_window(now):
        # вне окна — только убедиться что прошлые слоты читаются
        day = active_window_day(now)
        df, meta = load_day(day)
        print(f"skip fetch · show {day} · rows={len(df)} · frozen={meta.get('frozen')}")
        return 0

    window_day = active_window_day(now)
    target = bitrix_target_day(window_day)
    print(f"fetch window_day={window_day} bitrix_day={target}")

    from bitrix_selenium import download_work_report_excels

    result = download_work_report_excels(target)
    for msg in result.get("messages") or []:
        print("-", msg)
    files = result.get("files") or []
    folder = result.get("dir")
    if not files:
        print("ERROR: no excel downloaded")
        return 1

    incoming = load_excel_reports_from_dir(folder)
    if incoming is None or incoming.empty:
        print("ERROR: could not parse A1 percents")
        return 1

    file_blobs: dict[str, bytes] = {}
    for p in files:
        path = Path(p) if not isinstance(p, Path) else p
        if path.is_file():
            file_blobs[path.name] = path.read_bytes()

    df, meta = publish_day_snapshot(
        incoming, window_day=window_day, replace=True, file_blobs=file_blobs or None
    )
    print(f"saved rows={len(df)} updated_at={meta.get('updated_at')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
