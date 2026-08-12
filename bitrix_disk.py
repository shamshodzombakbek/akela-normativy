"""
Normativ Excel на Диске Битрикс24 — скачивание/загрузка через REST (без браузера).

Структура:
  Общий диск / {BITRIX_NORMATIV_FOLDER} / YYYY-MM-DD / Normativ_*.xlsx

Работает на Streamlit Cloud и на VPS — нужен только BITRIX_WEBHOOK_URL с правом disk.
"""

from __future__ import annotations

import base64
import os
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from bitrix_api import bitrix_call, bitrix_call_full

_ENV_PATH = Path(__file__).resolve().parent / ".env"
_DEFAULT_STORAGE_ID = 3
_DEFAULT_FOLDER = "Akela Normativy"


def _ensure_env() -> None:
    load_dotenv(_ENV_PATH, override=True)
    try:
        import streamlit as st

        if hasattr(st, "secrets"):
            for key in (
                "BITRIX_WEBHOOK_URL",
                "BITRIX_SHARED_STORAGE_ID",
                "BITRIX_NORMATIV_FOLDER",
                "BITRIX_NORMATIV_FOLDER_ID",
            ):
                if key in st.secrets and st.secrets[key]:
                    os.environ[key] = str(st.secrets[key])
    except Exception:
        pass


def _storage_id() -> int:
    _ensure_env()
    return int(os.getenv("BITRIX_SHARED_STORAGE_ID", str(_DEFAULT_STORAGE_ID)))


def _normativ_folder_name() -> str:
    _ensure_env()
    return os.getenv("BITRIX_NORMATIV_FOLDER", _DEFAULT_FOLDER).strip()


def _is_excel_name(name: str) -> bool:
    low = (name or "").lower()
    return low.endswith(".xlsx") or low.endswith(".xls")


def download_disk_file_bytes(file_meta: dict) -> bytes:
    url = file_meta.get("DOWNLOAD_URL")
    if not url:
        fresh = bitrix_call("disk.file.get", {"id": int(file_meta["ID"])}) or {}
        url = fresh.get("DOWNLOAD_URL")
    if not url:
        raise RuntimeError(f"Нет DOWNLOAD_URL у файла {file_meta.get('NAME')}")
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response.content


def get_normativ_root_folder() -> dict:
    """Корневая папка Normativ на Общем диске (по ID или по имени)."""
    _ensure_env()
    folder_id = (os.getenv("BITRIX_NORMATIV_FOLDER_ID") or "").strip()
    if folder_id:
        meta = bitrix_call("disk.folder.get", {"id": int(folder_id)})
        if not meta:
            raise RuntimeError(f"Папка BITRIX_NORMATIV_FOLDER_ID={folder_id} не найдена.")
        return meta

    storage_id = _storage_id()
    name = _normativ_folder_name()
    children = bitrix_call("disk.storage.getchildren", {"id": storage_id}) or []
    for item in children:
        if item.get("NAME") == name and item.get("TYPE") == "folder":
            return item

    created = bitrix_call(
        "disk.storage.addfolder",
        {"id": storage_id, "data": {"NAME": name}},
    )
    if not created:
        raise RuntimeError(f"Не удалось создать папку «{name}» на Общем диске.")
    return created


def get_or_create_day_folder(target_day: date) -> dict:
    root = get_normativ_root_folder()
    root_id = int(root["ID"])
    day_name = target_day.isoformat()
    children = bitrix_call("disk.folder.getchildren", {"id": root_id}) or []
    for item in children:
        if item.get("NAME") == day_name and item.get("TYPE") == "folder":
            return item
    created = bitrix_call(
        "disk.folder.addsubfolder",
        {"id": root_id, "data": {"NAME": day_name}},
    )
    if not created:
        raise RuntimeError(f"Не удалось создать подпапку {day_name}.")
    return created


def list_excel_files(folder_id: int) -> list[dict]:
    children = bitrix_call("disk.folder.getchildren", {"id": folder_id}) or []
    files = [c for c in children if c.get("TYPE") == "file" and _is_excel_name(c.get("NAME") or "")]
    files.sort(key=lambda x: str(x.get("UPDATE_TIME") or x.get("CREATE_TIME") or ""), reverse=True)
    return files


def upload_excel(folder_id: int, filename: str, content: bytes) -> dict:
    encoded = base64.b64encode(content).decode("ascii")
    payload = bitrix_call_full(
        "disk.folder.uploadfile",
        {
            "id": folder_id,
            "data": {"NAME": filename},
            "fileContent": [filename, encoded],
        },
    )
    result = payload.get("result") if isinstance(payload, dict) else payload
    if not result:
        raise RuntimeError(f"Не удалось загрузить {filename} на Диск.")
    return result if isinstance(result, dict) else {"NAME": filename}


def upload_normativs_to_disk(target_day: date, file_blobs: dict[str, bytes]) -> list[str]:
    """Кладёт Excel в подпапку дня (для последующей загрузки с сервера без Selenium)."""
    if not file_blobs:
        return []
    day_folder = get_or_create_day_folder(target_day)
    folder_id = int(day_folder["ID"])
    messages: list[str] = []
    for name, blob in file_blobs.items():
        if not _is_excel_name(name):
            continue
        upload_excel(folder_id, name, blob)
        messages.append(f"На Диск: {target_day.isoformat()}/{name}")
    return messages


def fetch_normativs_from_disk(target_day: date) -> dict[str, Any]:
    """
    Скачивает Normativ Excel за день с Диска.
    Возвращает file_blobs, локальную папку (если сохраняем), messages.
    """
    messages: list[str] = []
    root = get_normativ_root_folder()
    messages.append(f"Папка Диска: {root.get('NAME')} (id={root.get('ID')})")

    day_folder = get_or_create_day_folder(target_day)
    folder_id = int(day_folder["ID"])
    files_meta = list_excel_files(folder_id)

    # если в подпапке дня пусто — ищем Normativ_* в корне (старый flat-layout)
    if not files_meta:
        root_files = list_excel_files(int(root["ID"]))
        day_token = target_day.strftime("%d_%m").replace("_", ".")
        alt_token = target_day.strftime("%d.%m")
        for meta in root_files:
            name = meta.get("NAME") or ""
            if "normativ" in name.lower() and (
                target_day.isoformat() in name
                or day_token in name
                or alt_token in name
            ):
                files_meta.append(meta)
        if files_meta:
            messages.append(
                f"В подпапке {target_day.isoformat()} пусто — взято {len(files_meta)} "
                f"файл(ов) из корня папки."
            )

    if not files_meta:
        messages.append(
            f"На Диске нет Excel за {target_day.isoformat()}. "
            f"Положите файлы в «{root.get('NAME')} / {target_day.isoformat()}» "
            f"или запустите загрузку из «Отчётов»."
        )
        return {
            "ok": False,
            "target_day": target_day,
            "file_blobs": {},
            "files_meta": [],
            "dir": None,
            "messages": messages,
        }

    file_blobs: dict[str, bytes] = {}
    local_dir = Path(__file__).resolve().parent / "downloads" / "bitrix_disk" / target_day.isoformat()
    local_dir.mkdir(parents=True, exist_ok=True)

    for meta in files_meta:
        name = str(meta.get("NAME") or "report.xlsx")
        try:
            blob = download_disk_file_bytes(meta)
            file_blobs[name] = blob
            (local_dir / name).write_bytes(blob)
            messages.append(f"С Диска: {name} ({len(blob)} байт)")
        except Exception as exc:  # noqa: BLE001
            messages.append(f"Ошибка {name}: {exc}")

    if not file_blobs:
        return {
            "ok": False,
            "target_day": target_day,
            "file_blobs": {},
            "files_meta": files_meta,
            "dir": local_dir,
            "messages": messages,
        }

    messages.append(f"Итого с Диска: {len(file_blobs)} файл(ов).")
    return {
        "ok": True,
        "target_day": target_day,
        "file_blobs": file_blobs,
        "files_meta": files_meta,
        "dir": local_dir,
        "messages": messages,
    }


def disk_folder_url_hint() -> str:
    """Подсказка для админки — где лежат файлы."""
    try:
        root = get_normativ_root_folder()
        return f"{root.get('NAME', _normativ_folder_name())} → YYYY-MM-DD → Normativ_*.xlsx"
    except Exception:
        return f"{_normativ_folder_name()} → YYYY-MM-DD → Normativ_*.xlsx"
