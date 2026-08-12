"""
Загрузка Normativ с Диска Битрикс24 (REST) → publish.

Без Selenium и без привязки к конкретному компьютеру.
Cron: fetch_scheduler.py или GitHub Actions (.github/workflows/fetch-normativy.yml).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from bitrix_disk import fetch_normativs_from_disk
from schedule import active_window_day, bitrix_target_day
from shared_store import publish_day_snapshot
from utils import load_excel_reports_from_blobs, load_excel_reports_from_dir

_ROOT = Path(__file__).resolve().parent


def fetch_normativs(
    window_day: date | None = None,
    *,
    publish: bool = True,
    replace: bool = True,
) -> dict[str, Any]:
    """
    window_day — слот дашборда.
    На Диске ищем подпапку bitrix_target_day(window_day) (отчёты за предыдущий рабочий день).
    """
    window_day = window_day or active_window_day()
    target = bitrix_target_day(window_day)
    messages: list[str] = [
        f"Слот {window_day.isoformat()} · файлы на Диске за {target.isoformat()}"
    ]

    disk = fetch_normativs_from_disk(target)
    messages.extend(disk.get("messages") or [])
    file_blobs: dict[str, bytes] = dict(disk.get("file_blobs") or {})
    local_dir = disk.get("dir")

    if not file_blobs:
        return {
            "ok": False,
            "window_day": window_day,
            "target_day": target,
            "source": "disk",
            "messages": messages,
            "count": 0,
        }

    if local_dir and Path(local_dir).is_dir():
        incoming = load_excel_reports_from_dir(local_dir)
    else:
        incoming = load_excel_reports_from_blobs(file_blobs)

    if incoming is None or incoming.empty:
        messages.append("Excel найдены, но не удалось прочитать % из ячейки A1.")
        return {
            "ok": False,
            "window_day": window_day,
            "target_day": target,
            "source": "disk",
            "messages": messages,
            "count": 0,
            "file_blobs": file_blobs,
        }

    skipped = incoming.attrs.get("skipped_non_reports") or []
    if skipped:
        messages.append(f"Пропущено файлов без %: {len(skipped)}")

    day_store = _ROOT / "downloads" / "reports" / window_day.isoformat()
    day_store.mkdir(parents=True, exist_ok=True)
    for name, blob in file_blobs.items():
        (day_store / name).write_bytes(blob)

    meta: dict[str, Any] = {}
    if publish:
        df_pub, meta = publish_day_snapshot(
            incoming,
            window_day=window_day,
            replace=replace,
            allow_outside_window=True,
            force=True,
            file_blobs=file_blobs,
        )
        messages.append(
            f"Опубликовано: {meta.get('count', len(df_pub))} записей с Диска Битрикс24."
        )
    else:
        messages.append(f"Распознано записей: {len(incoming)} (без публикации).")

    return {
        "ok": True,
        "window_day": window_day,
        "target_day": target,
        "source": "disk",
        "messages": messages,
        "count": len(incoming),
        "meta": meta,
        "file_blobs": file_blobs,
    }
