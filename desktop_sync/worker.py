"""Фоновая синхронизация Normativ с Диска Битрикс24."""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any, Callable

from desktop_sync.config_store import apply_config_to_env, log_path
from schedule import active_window_day, is_fetch_window, now_tashkent


LogFn = Callable[[str], None]


def _write_log(line: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"[{stamp}] {line}\n"
    try:
        with log_path().open("a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def run_sync_once(
    *,
    force: bool = False,
    on_log: LogFn | None = None,
    only_report_ids: set[int] | list[int] | None = None,
    replace: bool | None = None,
) -> dict[str, Any]:
    """
    force=True — ручной запуск вне окна 16:00–18:30.
    only_report_ids — докачать только выбранных (merge на сайт).
    """

    def log(msg: str) -> None:
        _write_log(msg)
        if on_log:
            on_log(msg)

    empty: dict[str, Any] = {
        "ok": False,
        "message": "",
        "skipped_reports": [],
        "downloaded_reports": [],
        "window_day": None,
        "target_day": None,
        "count": 0,
    }

    try:
        apply_config_to_env()
        now = now_tashkent()
        window_day = active_window_day(now)

        if not force and not only_report_ids and not is_fetch_window(now):
            msg = f"Вне окна 16:00–18:30 · слот {window_day.isoformat()} · ожидание"
            log(msg)
            return {
                **empty,
                "ok": True,
                "message": msg,
                "window_day": window_day,
                "outside_window": True,
            }

        from bitrix_fetch import fetch_normativs

        do_replace = True if replace is None else bool(replace)
        if only_report_ids:
            do_replace = False
            log(
                f"Докачка выбранных ({len(list(only_report_ids))}) · "
                f"слот {window_day.isoformat()}"
            )
        else:
            log(f"Старт: «Отчёты» → Диск → сайт · слот {window_day.isoformat()}")

        result = fetch_normativs(
            window_day,
            source="auto" if not only_report_ids else "reports",
            publish=True,
            replace=do_replace,
            only_report_ids=only_report_ids,
        )
        for m in result.get("messages") or []:
            log(str(m))

        skipped = list(result.get("skipped_reports") or [])
        downloaded = list(result.get("downloaded_reports") or [])

        if result.get("ok"):
            msg = f"OK · {result.get('count', 0)} записей опубликовано на сайт"
            log(msg)
            return {
                "ok": True,
                "message": msg,
                "skipped_reports": skipped,
                "downloaded_reports": downloaded,
                "window_day": result.get("window_day") or window_day,
                "target_day": result.get("target_day"),
                "count": result.get("count", 0),
            }

        msg = "Не удалось скачать из «Отчётов» и на Диске нет файлов за этот день"
        if skipped:
            msg = (
                f"Скачать не удалось · не загружено: {len(skipped)} "
                f"(можно выбрать и добавить позже)"
            )
        log(msg)
        return {
            "ok": False,
            "message": msg,
            "skipped_reports": skipped,
            "downloaded_reports": downloaded,
            "window_day": result.get("window_day") or window_day,
            "target_day": result.get("target_day"),
            "count": 0,
        }
    except Exception as exc:
        tb = traceback.format_exc()
        log(f"ОШИБКА: {exc}\n{tb}")
        return {**empty, "ok": False, "message": str(exc)}
