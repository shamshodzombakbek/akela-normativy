"""Фоновая синхронизация Normativ с Диска Битрикс24."""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Callable

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


def run_sync_once(*, force: bool = False, on_log: LogFn | None = None) -> tuple[bool, str]:
    def log(msg: str) -> None:
        _write_log(msg)
        if on_log:
            on_log(msg)

    try:
        apply_config_to_env()
        now = now_tashkent()
        window_day = active_window_day(now)

        if not force and not is_fetch_window(now):
            msg = f"Вне окна 16:00–18:30 · слот {window_day.isoformat()} · ожидание"
            log(msg)
            return True, msg

        from bitrix_fetch import fetch_normativs

        log(f"Старт: «Отчёты» → Диск → сайт · слот {window_day.isoformat()}")
        result = fetch_normativs(
            window_day, source="auto", publish=True, replace=True
        )
        for m in result.get("messages") or []:
            log(str(m))

        if result.get("ok"):
            msg = f"OK · {result.get('count', 0)} записей опубликовано на сайт"
            log(msg)
            return True, msg

        msg = "Не удалось скачать из «Отчётов» и на Диске нет файлов за этот день"
        log(msg)
        return False, msg
    except Exception as exc:
        tb = traceback.format_exc()
        log(f"ОШИБКА: {exc}\n{tb}")
        return False, str(exc)
