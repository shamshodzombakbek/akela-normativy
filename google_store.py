"""Общее хранилище KPI в Google Drive через REST (без тяжёлого google-api-client)."""

from __future__ import annotations

import json
import os
from typing import Any

import requests
from dotenv import load_dotenv

FOLDER_ID_DEFAULT = "1Fe4ZmuB1iRV2l8K09V42QjBJmmMlTmvS"
FILE_NAME = "shared_kpi.json"
DRIVE_API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"


def _ensure_env() -> None:
    root = os.path.dirname(__file__)
    load_dotenv(os.path.join(root, ".env"), override=True)
    try:
        import streamlit as st

        if hasattr(st, "secrets") and st.secrets.get("GOOGLE_DRIVE_FOLDER_ID"):
            os.environ["GOOGLE_DRIVE_FOLDER_ID"] = str(st.secrets["GOOGLE_DRIVE_FOLDER_ID"])
    except Exception:
        pass


def folder_id() -> str:
    _ensure_env()
    return os.getenv("GOOGLE_DRIVE_FOLDER_ID", FOLDER_ID_DEFAULT).strip()


def is_google_configured() -> bool:
    try:
        import streamlit as st

        if hasattr(st, "secrets") and (
            "google_service_account" in st.secrets
            or st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        ):
            return True
    except Exception:
        pass
    return os.path.isfile(os.path.join(os.path.dirname(__file__), "google_service_account.json"))


def _service_account_info() -> dict:
    try:
        import streamlit as st

        if hasattr(st, "secrets"):
            if "google_service_account" in st.secrets:
                section = st.secrets["google_service_account"]
                return {k: section[k] for k in section}
            raw = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")
            if raw:
                return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception as exc:
        raise RuntimeError(f"Не удалось прочитать Secrets Google: {exc}") from exc

    path = os.path.join(os.path.dirname(__file__), "google_service_account.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    raise RuntimeError("Нет ключа Google service account в Secrets.")


def _access_token() -> str:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    info = _service_account_info()
    if "private_key" in info and isinstance(info["private_key"], str):
        info["private_key"] = info["private_key"].replace("\\n", "\n")

    required = ("type", "project_id", "private_key", "client_email", "token_uri")
    missing = [k for k in required if not info.get(k)]
    if missing:
        raise RuntimeError(f"В Secrets не хватает полей: {', '.join(missing)}")

    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    creds.refresh(Request())
    if not creds.token:
        raise RuntimeError("Google не выдал access token — проверьте private_key и client_email.")
    return creds.token


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_access_token()}"}


def _find_file(name: str, parent: str) -> dict | None:
    q = f"name = '{name}' and '{parent}' in parents and trashed = false"
    r = requests.get(
        f"{DRIVE_API}/files",
        headers=_headers(),
        params={"q": q, "spaces": "drive", "fields": "files(id,name)", "pageSize": 5},
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Drive list error {r.status_code}: {r.text[:400]}")
    files = (r.json() or {}).get("files") or []
    return files[0] if files else None


def load_store_dict() -> dict:
    """Читает shared_kpi.json из папки Drive."""
    parent = folder_id()
    meta = _find_file(FILE_NAME, parent)
    if not meta:
        return {"timezone": "Asia/Tashkent", "version": 2, "days": {}}

    r = requests.get(
        f"{DRIVE_API}/files/{meta['id']}",
        headers=_headers(),
        params={"alt": "media"},
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Drive download error {r.status_code}: {r.text[:400]}")
    try:
        payload = r.json()
    except Exception:
        try:
            payload = json.loads(r.content.decode("utf-8"))
        except Exception:
            payload = {}
    if not isinstance(payload, dict) or "days" not in payload:
        return {"timezone": "Asia/Tashkent", "version": 2, "days": {}}
    return payload


def save_store_dict(store: dict) -> dict[str, Any]:
    """Создаёт или обновляет shared_kpi.json в папке Drive."""
    parent = folder_id()
    data = json.dumps(store, ensure_ascii=False, indent=2).encode("utf-8")
    existing = _find_file(FILE_NAME, parent)
    headers = _headers()

    if existing:
        r = requests.patch(
            f"{UPLOAD_API}/files/{existing['id']}",
            headers={**headers, "Content-Type": "application/json"},
            params={"uploadType": "media"},
            data=data,
            timeout=60,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Drive update error {r.status_code}: {r.text[:400]}")
        return {"file_id": existing["id"], "name": FILE_NAME}

    metadata = {"name": FILE_NAME, "parents": [parent]}
    boundary = "akela_boundary"
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: application/json\r\n\r\n"
    ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")

    r = requests.post(
        f"{UPLOAD_API}/files",
        headers={
            **headers,
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        params={"uploadType": "multipart", "fields": "id,name"},
        data=body,
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Drive create error {r.status_code}: {r.text[:400]}")
    created = r.json()
    return {"file_id": created.get("id"), "name": FILE_NAME}
