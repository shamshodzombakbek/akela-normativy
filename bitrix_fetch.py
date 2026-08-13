"""
Загрузка Normativ:
  «Отчёты о работе» (Selenium, только десктоп) → папка на Диске → дашборд.
  Сайт / GitHub Actions читают только Диск (без браузера).
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal

from bitrix_disk import fetch_normativs_from_disk, upload_normativs_to_disk
from schedule import active_window_day, bitrix_target_day
from shared_store import publish_day_snapshot
from utils import load_excel_reports_from_blobs, load_excel_reports_from_dir

Source = Literal["auto", "disk", "reports"]
LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int, str], None]

_ROOT = Path(__file__).resolve().parent


def _emit(messages: list[str], msg: str, on_log: LogFn | None) -> None:
    messages.append(msg)
    if on_log:
        try:
            on_log(msg)
        except Exception:
            pass


def _progress(on_progress: ProgressFn | None, cur: int, total: int, label: str) -> None:
    if on_progress:
        try:
            on_progress(cur, total, label)
        except Exception:
            pass


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


def fetch_reports_to_disk(
    target_day: date,
    *,
    only_report_ids: set[int] | list[int] | None = None,
    on_log: LogFn | None = None,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """
    Открывает «Отчёты о работе», качает Normativ_*.xlsx,
    кладёт в Общий диск / Akela Normativy / YYYY-MM-DD /.
    """
    from bitrix_selenium import download_work_report_excels

    messages: list[str] = []
    result = download_work_report_excels(
        target_day,
        only_report_ids=only_report_ids,
        on_log=on_log,
        on_progress=on_progress,
    )
    # selenium уже стримил свои сообщения — не дублируем в on_log
    for msg in result.get("messages") or []:
        messages.append(str(msg))

    file_blobs: dict[str, bytes] = {}
    for p in result.get("files") or []:
        path = Path(p)
        if path.is_file():
            file_blobs[path.name] = path.read_bytes()

    if not file_blobs:
        summary = result.get("summary") or {}
        skipped = result.get("skipped_reports") or []
        _emit(messages, "Из «Отчётов» не скачано ни одного Excel.", on_log)
        if summary:
            _emit(
                messages,
                f"Сводка: всего {summary.get('total', 0)}, "
                f"скачано {summary.get('downloaded', 0)}, "
                f"пропущено {summary.get('skipped', 0)}.",
                on_log,
            )
        if skipped:
            _emit(
                messages,
                f"Пропущено отчётов: {len(skipped)} (см. лог выше).",
                on_log,
            )
        return {
            "ok": False,
            "file_blobs": {},
            "dir": result.get("dir"),
            "messages": messages,
            "summary": summary,
            "skipped_reports": skipped,
            "downloaded_reports": result.get("downloaded_reports") or [],
        }

    _emit(messages, f"Из «Отчётов»: {len(file_blobs)} файл(ов).", on_log)
    _progress(on_progress, 94, 100, "Загрузка на Диск Битрикс…")
    try:
        for line in upload_normativs_to_disk(target_day, file_blobs):
            _emit(messages, str(line), on_log)
        _emit(
            messages,
            f"Файлы записаны на Диск: Akela Normativy / {target_day.isoformat()} /",
            on_log,
        )
    except Exception as exc:  # noqa: BLE001
        _emit(messages, f"Не удалось положить на Диск: {exc}", on_log)
        return {
            "ok": False,
            "file_blobs": file_blobs,
            "dir": result.get("dir"),
            "messages": messages,
            "skipped_reports": result.get("skipped_reports") or [],
            "downloaded_reports": result.get("downloaded_reports") or [],
        }

    return {
        "ok": True,
        "file_blobs": file_blobs,
        "dir": result.get("dir"),
        "messages": messages,
        "summary": result.get("summary") or {},
        "downloaded_reports": result.get("downloaded_reports") or [],
        "skipped_reports": result.get("skipped_reports") or [],
    }


def fetch_normativs(
    window_day: date | None = None,
    *,
    source: Source = "disk",
    publish: bool = True,
    replace: bool = True,
    only_report_ids: set[int] | list[int] | None = None,
    on_log: LogFn | None = None,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """
    source:
      disk — только REST с Диска (сайт / GitHub Actions);
      reports — Selenium из «Отчётов» + копия на Диск (десктоп);
      auto — сначала «Отчёты», если пусто — Диск.

    only_report_ids — докачать только выбранные отчёты (replace обычно False).
    """
    window_day = window_day or active_window_day()
    target = bitrix_target_day(window_day)
    messages: list[str] = []
    _emit(
        messages,
        f"Слот {window_day.isoformat()} · день в Битрикс {target.isoformat()}",
        on_log,
    )

    file_blobs: dict[str, bytes] = {}
    source_used: str | None = None
    local_dir: Path | None = None
    skipped_reports: list[dict[str, Any]] = []
    downloaded_reports: list[dict[str, Any]] = []

    # Выборочная докачка — только через «Отчёты», без fallback на весь Диск
    effective_source: Source = "reports" if only_report_ids else source

    if effective_source in ("auto", "reports"):
        ok_sel, why = selenium_available()
        if not ok_sel:
            _emit(messages, why, on_log)
        else:
            _emit(messages, "Качаю из раздела «Отчёты о работе»…", on_log)
            _progress(on_progress, 2, 100, "Старт браузера…")
            rep = fetch_reports_to_disk(
                target,
                only_report_ids=only_report_ids,
                on_log=on_log,
                on_progress=on_progress,
            )
            # selenium messages already streamed; keep for return payload
            for m in rep.get("messages") or []:
                if m not in messages:
                    messages.append(str(m))
            skipped_reports = list(rep.get("skipped_reports") or [])
            downloaded_reports = list(rep.get("downloaded_reports") or [])
            if rep.get("ok") and rep.get("file_blobs"):
                file_blobs = dict(rep["file_blobs"])
                source_used = "reports"
                local_dir = Path(rep["dir"]) if rep.get("dir") else None

    if not file_blobs and effective_source in ("auto", "disk") and not only_report_ids:
        _emit(messages, "Читаю файлы с Диска…", on_log)
        _progress(on_progress, 50, 100, "Чтение Диска…")
        disk = fetch_normativs_from_disk(target)
        for m in disk.get("messages") or []:
            _emit(messages, str(m), on_log)
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
            "skipped_reports": skipped_reports,
            "downloaded_reports": downloaded_reports,
        }

    _progress(on_progress, 96, 100, "Разбор Excel…")
    if local_dir and Path(local_dir).is_dir() and not only_report_ids:
        incoming = load_excel_reports_from_dir(local_dir)
    else:
        incoming = load_excel_reports_from_blobs(file_blobs)

    if incoming is None or incoming.empty:
        _emit(messages, "Excel найдены, но не удалось прочитать % из ячейки A1.", on_log)
        return {
            "ok": False,
            "window_day": window_day,
            "target_day": target,
            "source": source_used,
            "messages": messages,
            "count": 0,
            "file_blobs": file_blobs,
            "skipped_reports": skipped_reports,
            "downloaded_reports": downloaded_reports,
        }

    skipped = incoming.attrs.get("skipped_non_reports") or []
    if skipped:
        _emit(messages, f"Пропущено файлов без %: {len(skipped)}", on_log)

    day_store = _ROOT / "downloads" / "reports" / window_day.isoformat()
    try:
        day_store.mkdir(parents=True, exist_ok=True)
        for name, blob in file_blobs.items():
            (day_store / name).write_bytes(blob)
    except Exception:
        pass

    meta: dict[str, Any] = {}
    if publish:
        _progress(on_progress, 98, 100, "Публикация на сайт…")
        df_pub, meta = publish_day_snapshot(
            incoming,
            window_day=window_day,
            replace=replace,
            allow_outside_window=True,
            force=True,
            file_blobs=file_blobs,
        )
        mode = "замена" if replace else "добавление к уже загруженным"
        _emit(
            messages,
            f"Опубликовано на сайт: {meta.get('count', len(df_pub))} записей "
            f"(источник: {source_used}, {mode}).",
            on_log,
        )
    else:
        _emit(messages, f"Распознано записей: {len(incoming)} (без публикации).", on_log)

    _progress(on_progress, 100, 100, "Готово")
    return {
        "ok": True,
        "window_day": window_day,
        "target_day": target,
        "source": source_used or effective_source,
        "messages": messages,
        "count": len(incoming),
        "meta": meta,
        "file_blobs": file_blobs,
        "skipped_reports": skipped_reports,
        "downloaded_reports": downloaded_reports,
    }
