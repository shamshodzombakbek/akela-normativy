"""Общее хранилище KPI в Google Drive (JSON-файл в папке)."""

from __future__ import annotations

import io
import json
import os
from typing import Any

from dotenv import load_dotenv

FOLDER_ID_DEFAULT = "1Fe4ZmuB1iRV2l8K09V42QjBJmmMlTmvS"
FILE_NAME = "shared_kpi.json"


def _ensure_env() -> None:
    root = os.path.dirname(__file__)
    load_dotenv(os.path.join(root, ".env"), override=True)
    try:
        import streamlit as st

        if hasattr(st, "secrets"):
            if st.secrets.get("GOOGLE_DRIVE_FOLDER_ID"):
                os.environ["GOOGLE_DRIVE_FOLDER_ID"] = str(st.secrets["GOOGLE_DRIVE_FOLDER_ID"])
    except Exception:
        pass


def folder_id() -> str:
    _ensure_env()
    return os.getenv("GOOGLE_DRIVE_FOLDER_ID", FOLDER_ID_DEFAULT).strip()


def is_google_configured() -> bool:
    """Есть ли ключ сервисного аккаунта в Secrets / файле."""
    try:
        import streamlit as st

        if hasattr(st, "secrets") and (
            "google_service_account" in st.secrets
            or st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        ):
            return True
    except Exception:
        pass
    path = os.path.join(os.path.dirname(__file__), "google_service_account.json")
    return os.path.isfile(path)


def _service_account_info() -> dict:
    try:
        import streamlit as st

        if hasattr(st, "secrets"):
            if "google_service_account" in st.secrets:
                # TOML section → dict-like
                section = st.secrets["google_service_account"]
                return {k: section[k] for k in section}
            raw = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")
            if raw:
                return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception:
        pass

    path = os.path.join(os.path.dirname(__file__), "google_service_account.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    raise RuntimeError(
        "Нет ключа Google. Добавьте в Streamlit Secrets секцию [google_service_account] "
        "или файл google_service_account.json (и расшарьте папку Drive на email сервисного аккаунта)."
    )


def _drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = _service_account_info()
    if "private_key" in info and isinstance(info["private_key"], str):
        info["private_key"] = info["private_key"].replace("\\n", "\n")

    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_file(service, name: str, parent: str) -> dict | None:
    q = (
        f"name = '{name}' and '{parent}' in parents and trashed = false"
    )
    res = (
        service.files()
        .list(q=q, spaces="drive", fields="files(id, name)", pageSize=5)
        .execute()
    )
    files = res.get("files") or []
    return files[0] if files else None


def load_store_dict() -> dict:
    """Читает shared_kpi.json из папки Drive. Пустой store, если файла ещё нет."""
    service = _drive_service()
    meta = _find_file(service, FILE_NAME, folder_id())
    if not meta:
        return {"timezone": "Asia/Tashkent", "version": 2, "days": {}}

    content = service.files().get_media(fileId=meta["id"]).execute()
    if isinstance(content, bytes):
        raw = content
    else:
        raw = bytes(content)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if "days" not in payload:
        payload = {"timezone": "Asia/Tashkent", "version": 2, "days": {}}
    return payload


def save_store_dict(store: dict) -> dict[str, Any]:
    """Создаёт или обновляет shared_kpi.json в папке Drive."""
    from googleapiclient.http import MediaIoBaseUpload

    service = _drive_service()
    parent = folder_id()
    data = json.dumps(store, ensure_ascii=False, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/json", resumable=False)

    existing = _find_file(service, FILE_NAME, parent)
    if existing:
        updated = (
            service.files()
            .update(fileId=existing["id"], media_body=media)
            .execute()
        )
        return {"file_id": updated.get("id"), "name": FILE_NAME}

    created = (
        service.files()
        .create(
            body={"name": FILE_NAME, "parents": [parent]},
            media_body=media,
            fields="id, name",
        )
        .execute()
    )
    return {"file_id": created.get("id"), "name": FILE_NAME}
