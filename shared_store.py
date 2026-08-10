"""Общее хранилище KPI по дням в Битрикс24 → Общий диск."""

from __future__ import annotations

import base64
import json
import os
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

from bitrix_api import bitrix_call, bitrix_call_full
from schedule import active_window_day, bitrix_target_day, is_fetch_window, now_tashkent
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
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.content


def _empty_store() -> dict:
    return {"timezone": "Asia/Tashkent", "version": 2, "days": {}}


def _migrate_payload(payload: dict) -> dict:
    """Старый формат {employees:[...]} → days[active]."""
    if "days" in payload and isinstance(payload["days"], dict):
        return payload
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
    _ensure_env()
    folder = ensure_shared_folder()
    folder_id = int(folder["ID"])
    file_meta = _find_shared_file(folder_id)
    meta = {"folder_id": folder_id, "file_id": None}
    if not file_meta:
        return _empty_store(), meta
    meta["file_id"] = int(file_meta["ID"])
    raw = _download_file_bytes(file_meta)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        payload = {}
    return _migrate_payload(payload if isinstance(payload, dict) else {}), meta


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


def list_available_days(store: dict | None = None) -> list[date]:
    if store is None:
        store, _ = _load_raw_store()
    days = []
    for key, slot in (store.get("days") or {}).items():
        try:
            if slot.get("employees"):
                days.append(date.fromisoformat(key))
        except Exception:
            continue
    return sorted(days, reverse=True)


def load_day(window_day: date | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Загрузить снимок за слот (без скачивания из Битрикс)."""
    store, disk_meta = _load_raw_store()
    day = window_day or active_window_day()
    key = day.isoformat()
    slot = (store.get("days") or {}).get(key) or {}
    df = _employees_to_df(slot.get("employees") or [])
    return df, {
        **disk_meta,
        "window_day": key,
        "bitrix_day": slot.get("bitrix_day") or bitrix_target_day(day).isoformat(),
        "updated_at": slot.get("updated_at"),
        "frozen": bool(slot.get("frozen")),
        "frozen_at": slot.get("frozen_at"),
        "count": len(df),
        "available_days": [d.isoformat() for d in list_available_days(store)],
        "can_fetch": is_fetch_window() and day == active_window_day(),
    }


def save_store(store: dict, file_id: int | None, folder_id: int | None) -> dict:
    _ensure_env()
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
        return {"file": result, "store": store}
    result = bitrix_call_full(
        "disk.folder.uploadfile",
        {
            "id": folder_id,
            "data": {"NAME": FILE_NAME},
            "fileContent": [FILE_NAME, encoded],
        },
    )
    return {"file": result.get("result"), "store": store}


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
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Сохранить снимок за слот.
    replace=True — полностью заменить сотрудников слота (типично для Битрикс-fetch).
    allow_outside_window=True — ручная загрузка Excel вне окна 16–20.
    """
    store, disk_meta = _load_raw_store()
    day = window_day or active_window_day()
    if (
        not allow_outside_window
        and not is_fetch_window()
        and day == active_window_day()
    ):
        raise RuntimeError("Сейчас вне окна 16:00–20:00 (Ташкент). Обновление из Битрикс закрыто.")

    key = day.isoformat()
    store.setdefault("days", {})
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

    store["days"][key] = {
        "window_day": key,
        "bitrix_day": bitrix_target_day(day).isoformat(),
        "employees": employees,
        "updated_at": now_s,
        "frozen": False,
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

    saved = save_store(store, disk_meta.get("file_id"), disk_meta.get("folder_id"))
    df = _employees_to_df(employees)
    file_obj = saved.get("file") if isinstance(saved.get("file"), dict) else {}
    return df, {
        "folder_id": disk_meta.get("folder_id"),
        "file_id": int(file_obj["ID"]) if file_obj.get("ID") else disk_meta.get("file_id"),
        "window_day": key,
        "bitrix_day": bitrix_target_day(day).isoformat(),
        "updated_at": now_s,
        "frozen": False,
        "count": len(df),
        "available_days": [d.isoformat() for d in list_available_days(store)],
        "can_fetch": True,
    }


# Обратная совместимость для старых импортов
def load_shared_employees() -> tuple[pd.DataFrame, dict[str, Any]]:
    return load_day(active_window_day())


def publish_incoming(incoming_df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    return publish_day_snapshot(incoming_df, active_window_day(), replace=True)
