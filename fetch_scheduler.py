#!/usr/bin/env python3
"""
Автозагрузка Normativ с Диска Битрикс24 → shared_kpi (Google Drive / Bitrix).

Не требует Mac, Chrome или Selenium — только BITRIX_WEBHOOK_URL с правом disk.

Cron (любой сервер / GitHub Actions), каждые 10 мин 16:00–18:30 Ташкент, пн–сб:
*/10 16-18 * * 1-6 cd "/path/to/Akela group" && python3 fetch_scheduler.py >> logs/fetch.log 2>&1

Ручной запуск на любом ПК: python run_fetch.py --force
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from schedule import active_window_day, is_fetch_window, now_tashkent, status_label  # noqa: E402
from shared_store import load_day  # noqa: E402


def main() -> int:
    now = now_tashkent()
    print(now.isoformat(), status_label(now))
    if not is_fetch_window(now):
        day = active_window_day(now)
        df, meta = load_day(day)
        print(f"skip fetch · show {day} · rows={len(df)} · frozen={meta.get('frozen')}")
        return 0

    from run_fetch import main as run_main

    return run_main([])


if __name__ == "__main__":
    raise SystemExit(main())
