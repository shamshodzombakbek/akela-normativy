"""Общее хранилище KPI по дням в Битрикс24 → Общий диск."""

from __future__ import annotations

import base64
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

from bitrix_api import bitrix_call, bitrix_call_full
from schedule import (
    active_window_day,
    bitrix_target_day,
    is_fetch_window,
    now_tashkent,
    can_upload_for_day,
    week_id,
    month_id,
    week_start,
    week_end,
    parse_week_id,
    parse_month_id,
)
from utils import kpi_category

STORAGE_ID = 3
FOLDER_NAME = "Akela Normativy Shared"
FILE_NAME = "shared_kpi.json"


def _ensure_env() -> None:
    root = os.path.dirname(__file__)
    load_dotenv(os.path.join(root, ".env"), override=True)
    try:
        import streamlit as st

        if hasattr(st, "secrets"):
            for key in (
                "BITRIX_WEBHOOK_URL",
                "BITRIX_SHARED_STORAGE_ID",
                "BITRIX_SHARED_FOLDER",
            ):
                if key in st.secrets and st.secrets[key]:
                    os.environ[key] = str(st.secrets[key])
    except Exception:
        pass
    global STORAGE_ID, FOLDER_NAME
    STORAGE_ID = int(os.getenv("BITRIX_SHARED_STORAGE_ID", str(STORAGE_ID)))
    FOLDER_NAME = os.getenv("BITRIX_SHARED_FOLDER", FOLDER_NAME)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_shared_folder() -> dict:
    _ensure_env()
    children = bitrix_call("disk.storage.getchildren", {"id": STORAGE_ID}) or []
    for item in children:
        if item.get("NAME") == FOLDER_NAME and item.get("TYPE") == "folder":
            return item
    created = bitrix_call(
        "disk.storage.addfolder",
        {"id": STORAGE_ID, "data": {"NAME": FOLDER_NAME}},
    )
    if not created:
        raise RuntimeError(f"Не удалось создать папку «{FOLDER_NAME}» на Диске.")
    return created


def _find_shared_file(folder_id: int) -> dict | None:
    children = bitrix_call("disk.folder.getchildren", {"id": folder_id}) or []
    for item in children:
        if item.get("NAME") == FILE_NAME and item.get("TYPE") == "file":
            return item
    return None


def _download_file_bytes(file_meta: dict) -> bytes:
    url = file_meta.get("DOWNLOAD_URL")
    if not url:
        fresh = bitrix_call("disk.file.get", {"id": int(file_meta["ID"])}) or {}
        url = fresh.get("DOWNLOAD_URL")
    if not url:
        raise RuntimeError("Нет DOWNLOAD_URL у shared_kpi.json")
    # Не используем окруженческие прокси, чтобы локальный запуск не ломался.
    s = requests.Session()
    s.trust_env = False
    response = s.get(url, timeout=60)
    response.raise_for_status()
    return response.content


def _empty_store() -> dict:
    return {
        "timezone": "Asia/Tashkent",
        "version": 3,
        "days": {},
        "weeks": {},
        "months": {},
        "staffing_overrides": {},
    }


def _norm_code(code: str | None) -> str:
    return str(code or "").strip()


def _save_meta(saved: dict, disk_meta: dict, **extra: Any) -> dict[str, Any]:
    file_obj = saved.get("file") if isinstance(saved.get("file"), dict) else {}
    return {
        "folder_id": disk_meta.get("folder_id"),
        "file_id": int(file_obj["ID"]) if file_obj.get("ID") else disk_meta.get("file_id"),
        "backend": saved.get("backend") or disk_meta.get("backend"),
        **extra,
    }


def _ensure_period_buckets(store: dict) -> dict:
    store.setdefault("days", {})
    store.setdefault("weeks", {})
    store.setdefault("months", {})
    store.setdefault("staffing_overrides", store.get("staffing_overrides") or {})
    return store


def _period_bucket(store: dict, kind: str) -> dict:
    _ensure_period_buckets(store)
    if kind == "day":
        return store["days"]
    if kind == "week":
        return store["weeks"]
    if kind == "month":
        return store["months"]
    raise RuntimeError(f"Неизвестный тип периода: {kind}")


def period_key(kind: str, ref: date) -> str:
    kind = (kind or "day").strip().lower()
    if kind == "day":
        return ref.isoformat()
    if kind == "week":
        return week_id(ref)
    if kind == "month":
        return month_id(ref)
    raise RuntimeError(f"Неизвестный тип периода: {kind}")


def _period_label(kind: str, key: str) -> str:
    if kind == "day":
        try:
            return date.fromisoformat(key).strftime("%d.%m.%Y")
        except Exception:
            return key
    if kind == "week":
        try:
            ws, we = parse_week_id(key)
            return f"неделя {key} ({ws.strftime('%d.%m')}–{we.strftime('%d.%m.%Y')})"
        except Exception:
            return key
    if kind == "month":
        try:
            y, m = parse_month_id(key)
            return date(y, m, 1).strftime("%m.%Y")
        except Exception:
            return key
    return key


def _migrate_payload(payload: dict) -> dict:
    """Старый формат {employees:[...]} → days[active]."""
    if "days" in payload and isinstance(payload["days"], dict):
        store = dict(payload)
        return _ensure_period_buckets(store)
    store = _empty_store()
    employees = payload.get("employees") or []
    if employees:
        day_key = active_window_day().isoformat()
        store["days"][day_key] = {
            "window_day": day_key,
            "bitrix_day": bitrix_target_day(date.fromisoformat(day_key)).isoformat(),
            "employees": employees,
            "updated_at": payload.get("updated_at") or _utc_now(),
            "frozen": False,
        }
    return store


def _load_raw_store() -> tuple[dict, dict[str, Any]]:
    """Читает store: сначала Google Drive, иначе Диск Битрикс."""
    _ensure_env()
    try:
        from google_store import is_google_configured, load_store_dict

        if is_google_configured():
            store = load_store_dict()
            return _migrate_payload(store), {"backend": "google", "file_id": None, "folder_id": None}
    except Exception as google_exc:
        # если Google настроен, но упал — не молчим в meta
        try:
            from google_store import is_google_configured

            if is_google_configured():
                raise RuntimeError(f"Google Drive: {google_exc}") from google_exc
        except RuntimeError:
            raise
        except Exception:
            pass

    folder = ensure_shared_folder()
    folder_id = int(folder["ID"])
    file_meta = _find_shared_file(folder_id)
    meta: dict[str, Any] = {"backend": "bitrix", "folder_id": folder_id, "file_id": None}
    if not file_meta:
        return _empty_store(), meta
    meta["file_id"] = int(file_meta["ID"])
    raw = _download_file_bytes(file_meta)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        payload = {}
    return _migrate_payload(payload if isinstance(payload, dict) else {}), meta


def save_store(store: dict, file_id: int | None, folder_id: int | None) -> dict:
    _ensure_env()
    try:
        from google_store import is_google_configured, save_store_dict

        if is_google_configured():
            saved = save_store_dict(store)
            return {"file": saved, "store": store, "backend": "google"}
    except Exception as google_exc:
        try:
            from google_store import is_google_configured

            if is_google_configured():
                raise RuntimeError(f"Google Drive: {google_exc}") from google_exc
        except RuntimeError:
            raise
        except Exception:
            pass

    if folder_id is None:
        folder = ensure_shared_folder()
        folder_id = int(folder["ID"])
    if file_id is None:
        existing = _find_shared_file(folder_id)
        file_id = int(existing["ID"]) if existing else None

    content = json.dumps(store, ensure_ascii=False, indent=2).encode("utf-8")
    encoded = base64.b64encode(content).decode("ascii")
    if file_id:
        result = bitrix_call(
            "disk.file.uploadversion",
            {"id": file_id, "fileContent": [FILE_NAME, encoded]},
        )
        return {"file": result, "store": store, "backend": "bitrix"}
    result = bitrix_call_full(
        "disk.folder.uploadfile",
        {
            "id": folder_id,
            "data": {"NAME": FILE_NAME},
            "fileContent": [FILE_NAME, encoded],
        },
    )
    return {"file": result.get("result"), "store": store, "backend": "bitrix"}


def _employees_to_df(employees: list) -> pd.DataFrame:
    df = pd.DataFrame(employees or [])
    if df.empty:
        return pd.DataFrame(
            columns=["Сотрудник", "KPI", "Категория", "Файл", "Обновлено", "Кто загрузил"]
        )
    if "KPI" in df.columns:
        df["KPI"] = pd.to_numeric(df["KPI"], errors="coerce").fillna(0.0)
        df["Категория"] = df["KPI"].map(kpi_category)
    return df


def _df_to_employees(df: pd.DataFrame) -> list[dict]:
    cols = [
        c
        for c in ["Сотрудник", "KPI", "Категория", "Файл", "Обновлено", "Кто загрузил"]
        if c in df.columns
    ]
    records = df[cols].to_dict(orient="records")
    for row in records:
        if "KPI" in row:
            try:
                row["KPI"] = float(row["KPI"])
            except Exception:
                row["KPI"] = 0.0
    return records


MAX_REPORT_BYTES = 2 * 1024 * 1024  # 2 MB на файл в shared_kpi.json


def _encode_file_blobs(blobs: dict[str, bytes] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not blobs:
        return out
    for name, data in blobs.items():
        fname = Path(str(name or "")).name
        if not fname or not data:
            continue
        if len(data) > MAX_REPORT_BYTES:
            continue
        out[fname] = base64.b64encode(data).decode("ascii")
    return out


def _merge_slot_files(
    existing: dict | None,
    blobs: dict[str, bytes] | None,
    *,
    replace: bool,
) -> dict[str, str]:
    base: dict[str, str] = {}
    if not replace and isinstance(existing, dict):
        base = {str(k): str(v) for k, v in existing.items() if v}
    base.update(_encode_file_blobs(blobs))
    return base


def _decode_report_b64(files_b64: dict | None, filename: str) -> bytes | None:
    if not isinstance(files_b64, dict):
        return None
    fname = Path(str(filename or "").strip()).name
    if not fname:
        return None
    raw = files_b64.get(fname)
    if raw is None:
        low = fname.casefold()
        for k, v in files_b64.items():
            if str(k).casefold() == low:
                raw = v
                break
    if not raw:
        return None
    try:
        return base64.b64decode(str(raw))
    except Exception:
        return None


def get_report_bytes(
    filename: str,
    *,
    period_kind: str = "day",
    period_key: str | None = None,
) -> bytes | None:
    """Excel из shared_kpi (files_b64) для периода."""
    fname = Path(str(filename or "").strip()).name
    if not fname:
        return None
    store, _ = _load_raw_store()
    kind = (period_kind or "day").strip().lower()
    key = period_key or active_window_day().isoformat()
    bucket = _period_bucket(store, kind)
    slot = bucket.get(key) or {}
    return _decode_report_b64(slot.get("files_b64"), fname)


def get_report_bytes_any_period(filename: str) -> bytes | None:
    """Ищет файл во всех слотах day/week/month."""
    fname = Path(str(filename or "").strip()).name
    if not fname:
        return None
    store, _ = _load_raw_store()
    store = _ensure_period_buckets(store)
    for kind in ("days", "weeks", "months"):
        for slot in (store.get(kind) or {}).values():
            if not isinstance(slot, dict):
                continue
            data = _decode_report_b64(slot.get("files_b64"), fname)
            if data:
                return data
    return None


def list_available_days(store: dict | None = None) -> list[date]:
    if store is None:
        store, _ = _load_raw_store()
    days = []
    for key, slot in (store.get("days") or {}).items():
        try:
            # зелёный день = хотя бы один загруженный отчёт
            if bool(slot.get("employees")):
                days.append(date.fromisoformat(key))
        except Exception:
            continue
    return sorted(days, reverse=True)


def load_day(window_day: date | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Загрузить снимок за слот (без скачивания из Битрикс)."""
    return load_period("day", window_day or active_window_day())


def list_available_weeks(store: dict | None = None) -> list[str]:
    if store is None:
        store, _ = _load_raw_store()
    keys = []
    for key, slot in (store.get("weeks") or {}).items():
        if slot.get("employees") or slot.get("seat_overrides"):
            keys.append(str(key))
    return sorted(keys, reverse=True)


def list_available_months(store: dict | None = None) -> list[str]:
    if store is None:
        store, _ = _load_raw_store()
    keys = []
    for key, slot in (store.get("months") or {}).items():
        if slot.get("employees") or slot.get("seat_overrides"):
            keys.append(str(key))
    return sorted(keys, reverse=True)


def load_period(kind: str, ref: date | str) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    kind: day | week | month
    ref: date или готовый ключ (2026-08-11 / 2026-W33 / 2026-08)
    """
    store, disk_meta = _load_raw_store()
    kind = (kind or "day").strip().lower()
    if isinstance(ref, str) and ref.strip():
        key = ref.strip()
        if kind == "day":
            anchor = date.fromisoformat(key)
        elif kind == "week":
            anchor, _ = parse_week_id(key)
        else:
            y, m = parse_month_id(key)
            anchor = date(y, m, 1)
    else:
        anchor = ref if isinstance(ref, date) else active_window_day()
        key = period_key(kind, anchor)

    bucket = _period_bucket(store, kind)
    slot = bucket.get(key) or {}
    df = _employees_to_df(slot.get("employees") or [])
    seat_overrides = slot.get("seat_overrides") or {}
    if not isinstance(seat_overrides, dict):
        seat_overrides = {}
    return df, {
        **disk_meta,
        "period_kind": kind,
        "period_key": key,
        "period_label": _period_label(kind, key),
        "window_day": key if kind == "day" else (slot.get("window_day") or key),
        "bitrix_day": slot.get("bitrix_day")
        or (bitrix_target_day(anchor).isoformat() if kind == "day" else None),
        "updated_at": slot.get("updated_at"),
        "frozen": bool(slot.get("frozen")),
        "frozen_at": slot.get("frozen_at"),
        "count": len(df),
        "seat_overrides": seat_overrides,
        "available_days": [d.isoformat() for d in list_available_days(store)],
        "available_weeks": list_available_weeks(store),
        "available_months": list_available_months(store),
        "can_fetch": kind == "day" and is_fetch_window() and anchor == active_window_day(),
        "anchor_date": anchor.isoformat(),
    }


def days_in_week_with_data(week_key: str, store: dict | None = None) -> list[date]:
    if store is None:
        store, _ = _load_raw_store()
    try:
        ws, we = parse_week_id(week_key)
    except Exception:
        return []
    out = []
    for d in list_available_days(store):
        if ws <= d <= we:
            out.append(d)
    return sorted(out, reverse=True)


def days_in_month_with_data(month_key: str, store: dict | None = None) -> list[date]:
    if store is None:
        store, _ = _load_raw_store()
    try:
        y, m = parse_month_id(month_key)
    except Exception:
        return []
    out = []
    for d in list_available_days(store):
        if d.year == y and d.month == m:
            out.append(d)
    return sorted(out, reverse=True)


def weeks_in_month_with_data(month_key: str, store: dict | None = None) -> list[str]:
    if store is None:
        store, _ = _load_raw_store()
    try:
        y, m = parse_month_id(month_key)
    except Exception:
        return []
    from schedule import weeks_in_month

    month_weeks = {w for w, _, _ in weeks_in_month(y, m)}
    found: set[str] = set()
    for w in list_available_weeks(store):
        if w in month_weeks:
            found.add(w)
    for d in days_in_month_with_data(month_key, store):
        found.add(week_id(d))
    return sorted(found, reverse=True)


def publish_period_snapshot(
    incoming_df: pd.DataFrame,
    kind: str,
    ref: date | None = None,
    replace: bool = True,
    allow_outside_window: bool = False,
    force: bool = False,
    file_blobs: dict[str, bytes] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Сохранить снимок периода.
    day — прежние правила окна; week/month — без окна 16–20 (отдельные отчёты).
    force=True — админ без ограничений.
    """
    kind = (kind or "day").strip().lower()
    anchor = ref or active_window_day()
    if kind == "day":
        return publish_day_snapshot(
            incoming_df,
            window_day=anchor,
            replace=replace,
            allow_outside_window=allow_outside_window,
            force=force,
            file_blobs=file_blobs,
        )

    store, disk_meta = _load_raw_store()
    _ensure_period_buckets(store)
    key = period_key(kind, anchor)
    bucket = _period_bucket(store, kind)
    existing_slot = bucket.get(key) or {}
    now_s = _utc_now()
    employees = _df_to_employees(incoming_df)

    if not replace and key in bucket:
        old = _employees_to_df(bucket[key].get("employees") or [])
        incoming = incoming_df.copy()
        if "Обновлено" not in incoming.columns:
            incoming["Обновлено"] = now_s
        old["_key"] = (
            old["Сотрудник"].astype(str).str.strip().str.casefold()
            if not old.empty
            else pd.Series(dtype=str)
        )
        incoming["_key"] = incoming["Сотрудник"].astype(str).str.strip().str.casefold()
        if not old.empty:
            old = old[~old["_key"].isin(set(incoming["_key"]))]
            merged = pd.concat([old, incoming], ignore_index=True).drop(
                columns=["_key"], errors="ignore"
            )
        else:
            merged = incoming.drop(columns=["_key"], errors="ignore")
        employees = _df_to_employees(merged)

    preserved_overrides = existing_slot.get("seat_overrides") or {}
    if not isinstance(preserved_overrides, dict):
        preserved_overrides = {}

    files_b64 = _merge_slot_files(
        existing_slot.get("files_b64"),
        file_blobs,
        replace=replace,
    )
    bucket[key] = {
        "period_kind": kind,
        "period_key": key,
        "window_day": key,
        "employees": employees,
        "files_b64": files_b64,
        "updated_at": now_s,
        "frozen": False,
        "seat_overrides": preserved_overrides,
        "anchor_date": anchor.isoformat(),
        "week_start": week_start(anchor).isoformat() if kind == "week" else None,
        "week_end": week_end(anchor).isoformat() if kind == "week" else None,
    }
    store.setdefault("staffing_overrides", store.get("staffing_overrides") or {})
    saved = save_store(store, disk_meta.get("file_id"), disk_meta.get("folder_id"))
    df = _employees_to_df(employees)
    return df, _save_meta(
        saved,
        disk_meta,
        period_kind=kind,
        period_key=key,
        period_label=_period_label(kind, key),
        updated_at=now_s,
        frozen=False,
        count=len(df),
        seat_overrides=preserved_overrides,
        available_days=[d.isoformat() for d in list_available_days(store)],
        available_weeks=list_available_weeks(store),
        available_months=list_available_months(store),
    )


def freeze_day_if_needed(store: dict, window_day: date) -> bool:
    """После 20:00 помечаем слот как frozen."""
    if is_fetch_window():
        return False
    key = window_day.isoformat()
    slot = (store.get("days") or {}).get(key)
    if not slot or slot.get("frozen"):
        return False
    if not slot.get("employees"):
        return False
    # замораживаем только если уже не в окне для этого активного слота
    if active_window_day() != window_day and now_tashkent().date() <= window_day:
        return False
    if active_window_day() == window_day and is_fetch_window():
        return False
    # Если текущий активный слот и время после 20:00
    now = now_tashkent()
    if active_window_day(now) == window_day and not is_fetch_window(now):
        slot["frozen"] = True
        slot["frozen_at"] = _utc_now()
        return True
    # Если смотрим прошлый слот — тоже frozen
    if window_day < active_window_day(now):
        slot["frozen"] = True
        slot.setdefault("frozen_at", _utc_now())
        return True
    return False


def publish_day_snapshot(
    incoming_df: pd.DataFrame,
    window_day: date | None = None,
    replace: bool = True,
    allow_outside_window: bool = False,
    force: bool = False,
    file_blobs: dict[str, bytes] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Сохранить снимок за слот.
    replace=True — полностью заменить сотрудников слота (типично для Битрикс-fetch).
    allow_outside_window=True — ручная загрузка Excel вне окна 16–20.
    force=True — админ: без окна и без блокировки frozen.
    """
    store, disk_meta = _load_raw_store()
    day = window_day or active_window_day()

    if not force:
        ok, reason = can_upload_for_day(day)
        if not ok:
            raise RuntimeError(reason)

        if (
            not allow_outside_window
            and not is_fetch_window()
            and day == active_window_day()
        ):
            raise RuntimeError(
                "Сейчас вне окна 16:00–18:30 (Ташкент). Обновление из Битрикс закрыто."
            )

    key = day.isoformat()
    store.setdefault("days", {})
    existing_slot = store["days"].get(key) or {}
    if existing_slot.get("frozen") and not force:
        raise RuntimeError(
            f"День {day.strftime('%d.%m.%Y')} уже закрыт после 18:30 — добавлять отчёты нельзя."
        )

    now_s = _utc_now()
    employees = _df_to_employees(incoming_df)

    if not replace and key in store["days"]:
        # merge by name
        old = _employees_to_df(store["days"][key].get("employees") or [])
        incoming = incoming_df.copy()
        if "Обновлено" not in incoming.columns:
            incoming["Обновлено"] = now_s
        old["_key"] = old["Сотрудник"].astype(str).str.strip().str.casefold() if not old.empty else pd.Series(dtype=str)
        incoming["_key"] = incoming["Сотрудник"].astype(str).str.strip().str.casefold()
        if not old.empty:
            old = old[~old["_key"].isin(set(incoming["_key"]))]
            merged = pd.concat([old, incoming], ignore_index=True).drop(columns=["_key"], errors="ignore")
        else:
            merged = incoming.drop(columns=["_key"], errors="ignore")
        employees = _df_to_employees(merged)

    preserved_overrides = existing_slot.get("seat_overrides") or {}
    if not isinstance(preserved_overrides, dict):
        preserved_overrides = {}

    keep_frozen = bool(existing_slot.get("frozen")) if force else False
    files_b64 = _merge_slot_files(
        existing_slot.get("files_b64"),
        file_blobs,
        replace=replace,
    )
    store["days"][key] = {
        "window_day": key,
        "bitrix_day": bitrix_target_day(day).isoformat(),
        "employees": employees,
        "files_b64": files_b64,
        "updated_at": now_s,
        "frozen": keep_frozen,
        "seat_overrides": preserved_overrides,
    }

    # заморозить прошлые дни
    for past_key, slot in store["days"].items():
        try:
            past = date.fromisoformat(past_key)
        except Exception:
            continue
        if past < day and not slot.get("frozen") and slot.get("employees"):
            slot["frozen"] = True
            slot.setdefault("frozen_at", now_s)

    # корневые staffing_overrides не трогаем
    store.setdefault("staffing_overrides", store.get("staffing_overrides") or {})

    saved = save_store(store, disk_meta.get("file_id"), disk_meta.get("folder_id"))
    df = _employees_to_df(employees)
    return df, _save_meta(
        saved,
        disk_meta,
        window_day=key,
        bitrix_day=bitrix_target_day(day).isoformat(),
        updated_at=now_s,
        frozen=keep_frozen,
        count=len(df),
        seat_overrides=preserved_overrides,
        available_days=[d.isoformat() for d in list_available_days(store)],
        can_fetch=True,
    )


def remove_employees_from_day(
    names: list[str],
    window_day: date | None = None,
    match_files: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Удалить ошибочные записи из слота (по Сотрудник / Файл).
    Работает даже после 20:00 — это правка, не добавление.
    """
    store, disk_meta = _load_raw_store()
    day = window_day or active_window_day()
    key = day.isoformat()
    store.setdefault("days", {})
    slot = store["days"].get(key) or {}
    employees = list(slot.get("employees") or [])
    if not employees:
        raise RuntimeError(f"За {day.strftime('%d.%m.%Y')} нет записей для удаления.")

    targets = {str(n or "").strip().casefold() for n in names if str(n or "").strip()}
    if not targets:
        raise RuntimeError("Не выбрано ни одной записи для удаления.")

    def _hit(row: dict) -> bool:
        name = str(row.get("Сотрудник") or "").strip().casefold()
        fname = str(row.get("Файл") or "").strip().casefold()
        if name in targets:
            return True
        if match_files and fname:
            for t in targets:
                if t and t in fname:
                    return True
        return False

    kept = [row for row in employees if not _hit(row)]
    removed = len(employees) - len(kept)
    if removed <= 0:
        raise RuntimeError("Совпадений не найдено — ничего не удалено.")

    now_s = _utc_now()
    slot = dict(slot)
    slot["employees"] = kept
    slot["updated_at"] = now_s
    slot["window_day"] = key
    slot.setdefault("bitrix_day", bitrix_target_day(day).isoformat())
    # frozen не снимаем — только чистим ошибочные строки
    store["days"][key] = slot

    saved = save_store(store, disk_meta.get("file_id"), disk_meta.get("folder_id"))
    df = _employees_to_df(kept)
    return df, _save_meta(
        saved,
        disk_meta,
        window_day=key,
        updated_at=now_s,
        removed=removed,
        count=len(df),
        available_days=[d.isoformat() for d in list_available_days(store)],
    )


def load_staffing_overrides() -> dict[str, dict]:
    """Корневые кадровые overrides по Код места."""
    store, _ = _load_raw_store()
    raw = store.get("staffing_overrides") or {}
    if not isinstance(raw, dict):
        return {}
    return { _norm_code(k): dict(v) for k, v in raw.items() if _norm_code(k) and isinstance(v, dict) }


def load_seat_overrides(window_day: date | None = None) -> dict[str, dict]:
    store, _ = _load_raw_store()
    day = window_day or active_window_day()
    slot = (store.get("days") or {}).get(day.isoformat()) or {}
    raw = slot.get("seat_overrides") or {}
    if not isinstance(raw, dict):
        return {}
    return { _norm_code(k): dict(v) for k, v in raw.items() if _norm_code(k) and isinstance(v, dict) }


def upsert_seat_override(
    code: str,
    status: str,
    kpi: float | None = None,
    window_day: date | None = None,
    file_name: str = "",
) -> dict[str, Any]:
    """
    Ручной статус сдачи по месту (Код) на день.
    Работает в любое время, в т.ч. после freeze.
    """
    code_key = _norm_code(code)
    if not code_key:
        raise RuntimeError("Не указан код места.")
    status = str(status or "").strip()
    allowed = {"✅ Сдал", "⚫ 0%", "❌ Не сдал"}
    if status not in allowed:
        raise RuntimeError(f"Статус должен быть один из: {', '.join(sorted(allowed))}")

    store, disk_meta = _load_raw_store()
    day = window_day or active_window_day()
    key = day.isoformat()
    store.setdefault("days", {})
    slot = dict(store["days"].get(key) or {})
    overrides = dict(slot.get("seat_overrides") or {})
    if not isinstance(overrides, dict):
        overrides = {}

    try:
        kpi_val = float(kpi) if kpi is not None else 0.0
    except Exception:
        kpi_val = 0.0
    if status in {"❌ Не сдал", "⚫ 0%"}:
        kpi_val = 0.0
    if status == "❌ Не сдал":
        cat = kpi_category(None)
        file_out = ""
    elif status == "⚫ 0%":
        cat = kpi_category(0.0)
        file_out = str(file_name or "")
    else:
        cat = kpi_category(kpi_val if kpi_val > 0 else None)
        file_out = str(file_name or "")

    now_s = _utc_now()
    overrides[code_key] = {
        "Статус": status,
        "KPI": kpi_val,
        "Категория": cat,
        "Файл": file_out,
        "source": "admin",
        "updated_at": now_s,
    }

    slot["seat_overrides"] = overrides
    slot["window_day"] = key
    slot.setdefault("bitrix_day", bitrix_target_day(day).isoformat())
    slot.setdefault("employees", slot.get("employees") or [])
    slot["updated_at"] = now_s
    store["days"][key] = slot
    store.setdefault("staffing_overrides", store.get("staffing_overrides") or {})

    saved = save_store(store, disk_meta.get("file_id"), disk_meta.get("folder_id"))
    return _save_meta(
        saved,
        disk_meta,
        window_day=key,
        updated_at=now_s,
        code=code_key,
        seat_overrides=overrides,
    )


def clear_seat_override(
    code: str,
    window_day: date | None = None,
) -> dict[str, Any]:
    """Убрать ручную правку статуса по месту."""
    code_key = _norm_code(code)
    if not code_key:
        raise RuntimeError("Не указан код места.")

    store, disk_meta = _load_raw_store()
    day = window_day or active_window_day()
    key = day.isoformat()
    store.setdefault("days", {})
    slot = dict(store["days"].get(key) or {})
    overrides = dict(slot.get("seat_overrides") or {})
    if code_key not in overrides:
        raise RuntimeError(f"Для {code_key} нет ручной правки статуса.")
    overrides.pop(code_key, None)
    now_s = _utc_now()
    slot["seat_overrides"] = overrides
    slot["window_day"] = key
    slot.setdefault("bitrix_day", bitrix_target_day(day).isoformat())
    slot.setdefault("employees", slot.get("employees") or [])
    slot["updated_at"] = now_s
    store["days"][key] = slot
    store.setdefault("staffing_overrides", store.get("staffing_overrides") or {})

    saved = save_store(store, disk_meta.get("file_id"), disk_meta.get("folder_id"))
    return _save_meta(
        saved,
        disk_meta,
        window_day=key,
        updated_at=now_s,
        code=code_key,
        removed=True,
        seat_overrides=overrides,
    )


def admin_upsert_employee(
    name: str,
    kpi: float = 0.0,
    file_name: str = "",
    window_day: date | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Добавить/обновить Excel-строку дня без окна 16–20 и без блока frozen."""
    emp_name = str(name or "").strip()
    if not emp_name:
        raise RuntimeError("Укажите имя сотрудника / название отчёта.")

    store, disk_meta = _load_raw_store()
    day = window_day or active_window_day()
    key = day.isoformat()
    store.setdefault("days", {})
    slot = dict(store["days"].get(key) or {})
    employees = list(slot.get("employees") or [])
    now_s = _utc_now()
    try:
        kpi_val = float(kpi)
    except Exception:
        kpi_val = 0.0

    row = {
        "Сотрудник": emp_name,
        "KPI": kpi_val,
        "Категория": kpi_category(kpi_val if kpi_val > 0 else None),
        "Файл": str(file_name or "") or "(admin)",
        "Обновлено": now_s,
        "Кто загрузил": "admin",
    }
    fold = emp_name.casefold()
    kept = [
        r
        for r in employees
        if str(r.get("Сотрудник") or "").strip().casefold() != fold
    ]
    kept.append(row)

    preserved = slot.get("seat_overrides") or {}
    if not isinstance(preserved, dict):
        preserved = {}
    slot["employees"] = kept
    slot["seat_overrides"] = preserved
    slot["window_day"] = key
    slot.setdefault("bitrix_day", bitrix_target_day(day).isoformat())
    slot["updated_at"] = now_s
    # frozen не снимаем
    store["days"][key] = slot
    store.setdefault("staffing_overrides", store.get("staffing_overrides") or {})

    saved = save_store(store, disk_meta.get("file_id"), disk_meta.get("folder_id"))
    df = _employees_to_df(kept)
    return df, _save_meta(
        saved,
        disk_meta,
        window_day=key,
        updated_at=now_s,
        count=len(df),
        available_days=[d.isoformat() for d in list_available_days(store)],
    )


def set_staffing_override(
    code: str,
    fio: str = "",
    status: str = "Занято",
    note: str = "",
    action: str = "replace",
    prev_fio: str | None = None,
) -> dict[str, Any]:
    """
    Кадровая правка места: увольнение / замена / заполнение вакансии.
    Ключ — Код из staffing.csv.
    """
    code_key = _norm_code(code)
    if not code_key:
        raise RuntimeError("Не указан код места.")

    status_norm = str(status or "").strip()
    if status_norm not in {"Занято", "Вакансия"}:
        raise RuntimeError("Статус места: Занято или Вакансия.")
    fio_clean = str(fio or "").strip()
    if status_norm == "Занято" and not fio_clean:
        raise RuntimeError("Для занятого места укажите ФИО.")
    if status_norm == "Вакансия":
        fio_clean = ""

    store, disk_meta = _load_raw_store()
    overrides = dict(store.get("staffing_overrides") or {})
    if not isinstance(overrides, dict):
        overrides = {}
    now_s = _utc_now()
    existing = dict(overrides.get(code_key) or {})
    payload = {
        "ФИО": fio_clean,
        "Статус_места": status_norm,
        "Пометка": str(note or "").strip(),
        "action": str(action or "replace").strip() or "replace",
        "updated_at": now_s,
    }
    if prev_fio is not None:
        payload["prev_fio"] = str(prev_fio).strip()
    elif existing.get("prev_fio") and status_norm == "Вакансия":
        payload["prev_fio"] = existing.get("prev_fio")
    overrides[code_key] = payload
    store["staffing_overrides"] = overrides

    saved = save_store(store, disk_meta.get("file_id"), disk_meta.get("folder_id"))
    return _save_meta(
        saved,
        disk_meta,
        code=code_key,
        updated_at=now_s,
        staffing_overrides=overrides,
    )


def clear_staffing_override(code: str) -> dict[str, Any]:
    """Вернуть место к значению из staffing.csv."""
    code_key = _norm_code(code)
    if not code_key:
        raise RuntimeError("Не указан код места.")

    store, disk_meta = _load_raw_store()
    overrides = dict(store.get("staffing_overrides") or {})
    if code_key not in overrides:
        raise RuntimeError(f"Для {code_key} нет кадровой правки.")
    overrides.pop(code_key, None)
    now_s = _utc_now()
    store["staffing_overrides"] = overrides

    saved = save_store(store, disk_meta.get("file_id"), disk_meta.get("folder_id"))
    return _save_meta(
        saved,
        disk_meta,
        code=code_key,
        updated_at=now_s,
        removed=True,
        staffing_overrides=overrides,
    )


# Обратная совместимость для старых импортов
def load_shared_employees() -> tuple[pd.DataFrame, dict[str, Any]]:
    return load_day(active_window_day())


def publish_incoming(incoming_df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    return publish_day_snapshot(incoming_df, active_window_day(), replace=True)
