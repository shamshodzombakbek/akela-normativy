"""
Загрузка Normativ:
  «Отчёты о работе» (Selenium, только десктоп) → папка на Диске → дашборд.
  Сайт / GitHub Actions читают только Диск (без браузера).
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Literal

from bitrix_disk import fetch_normativs_from_disk, upload_normativs_to_disk
from schedule import active_window_day, bitrix_target_day
from shared_store import publish_day_snapshot
from utils import load_excel_reports_from_blobs, load_excel_reports_from_dir

Source = Literal["auto", "disk", "reports"]

_ROOT = Path(__file__).resolve().parent


def selenium_available() -> tuple[bool, str]:
    login = (os.getenv("BITRIX_LOGIN") or "").strip()
    password = (os.getenv("BITRIX_PASSWORD") or "").strip()
    if not login or not password:
        return False, "Нужны логин и пароль Битрикс24."
    try:
        import selenium  # noqa: F401
        import webdriver_manager  # noqa: F401
    except ImportError:
        return False, "Не установлены selenium / webdriver-manager."
    return True, ""


def fetch_reports_to_disk(target_day: date) -> dict[str, Any]:
    """
    Открывает «Отчёты о работе», качает Normativ_*.xlsx,
    кладёт в Общий диск / Akela Normativy / YYYY-MM-DD /.
    """
    from bitrix_selenium import download_work_report_excels

    messages: list[str] = []
    result = download_work_report_excels(target_day)
    for msg in result.get("messages") or []:
        messages.append(str(msg))

    file_blobs: dict[str, bytes] = {}
    for p in result.get("files") or []:
        path = Path(p)
        if path.is_file():
            file_blobs[path.name] = path.read_bytes()

    if not file_blobs:
        messages.append("Из «Отчётов» не скачано ни одного Excel.")
        return {
            "ok": False,
            "file_blobs": {},
            "dir": result.get("dir"),
            "messages": messages,
        }

    messages.append(f"Из «Отчётов»: {len(file_blobs)} файл(ов).")
    try:
        messages.extend(upload_normativs_to_disk(target_day, file_blobs))
        messages.append(
            f"Файлы записаны на Диск: Akela Normativy / {target_day.isoformat()} /"
        )
    except Exception as exc:  # noqa: BLE001
        messages.append(f"Не удалось положить на Диск: {exc}")
        return {
            "ok": False,
            "file_blobs": file_blobs,
            "dir": result.get("dir"),
            "messages": messages,
        }

    return {
        "ok": True,
        "file_blobs": file_blobs,
        "dir": result.get("dir"),
        "messages": messages,
    }


def fetch_normativs(
    window_day: date | None = None,
    *,
    source: Source = "disk",
    publish: bool = True,
    replace: bool = True,
) -> dict[str, Any]:
    """
    source:
      disk — только REST с Диска (сайт / GitHub Actions);
      reports — Selenium из «Отчётов» + копия на Диск (десктоп);
      auto — сначала «Отчёты», если пусто — Диск.
    """
    window_day = window_day or active_window_day()
    target = bitrix_target_day(window_day)
    messages: list[str] = [
        f"Слот {window_day.isoformat()} · день в Битрикс {target.isoformat()}"
    ]

    file_blobs: dict[str, bytes] = {}
    source_used: str | None = None
    local_dir: Path | None = None

    if source in ("auto", "reports"):
        ok_sel, why = selenium_available()
        if not ok_sel:
            messages.append(why)
        else:
            messages.append("Качаю из раздела «Отчёты о работе»…")
            rep = fetch_reports_to_disk(target)
            messages.extend(rep.get("messages") or [])
            if rep.get("ok") and rep.get("file_blobs"):
                file_blobs = dict(rep["file_blobs"])
                source_used = "reports"
                local_dir = Path(rep["dir"]) if rep.get("dir") else None

    if not file_blobs and source in ("auto", "disk"):
        disk = fetch_normativs_from_disk(target)
        messages.extend(disk.get("messages") or [])
        if disk.get("ok") and disk.get("file_blobs"):
            file_blobs = dict(disk["file_blobs"])
            source_used = "disk"
            local_dir = disk.get("dir")

    if not file_blobs:
        return {
            "ok": False,
            "window_day": window_day,
            "target_day": target,
            "source": source_used,
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
            "source": source_used,
            "messages": messages,
            "count": 0,
            "file_blobs": file_blobs,
        }

    skipped = incoming.attrs.get("skipped_non_reports") or []
    if skipped:
        messages.append(f"Пропущено файлов без %: {len(skipped)}")

    day_store = _ROOT / "downloads" / "reports" / window_day.isoformat()
    try:
        day_store.mkdir(parents=True, exist_ok=True)
        for name, blob in file_blobs.items():
            (day_store / name).write_bytes(blob)
    except Exception:
        pass

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
            f"Опубликовано на сайт: {meta.get('count', len(df_pub))} записей "
            f"(источник: {source_used})."
        )
    else:
        messages.append(f"Распознано записей: {len(incoming)} (без публикации).")

    return {
        "ok": True,
        "window_day": window_day,
        "target_day": target,
        "source": source_used or source,
        "messages": messages,
        "count": len(incoming),
        "meta": meta,
        "file_blobs": file_blobs,
    }
