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


def _repair_service_account_json(text: str) -> str:
    """Чинит частую ошибку: живые переносы строк внутри private_key."""
    import re

    text = text.strip().lstrip("\ufeff")

    pattern = re.compile(
        r'"private_key"\s*:\s*"(-----BEGIN PRIVATE KEY-----)\s*([\s\S]*?)\s*(-----END PRIVATE KEY-----)\s*"',
        re.MULTILINE,
    )

    def _repl(match: re.Match) -> str:
        begin, middle, end = match.group(1), match.group(2), match.group(3)
        middle = middle.replace("\r\n", "\n").replace("\r", "\n")
        middle = middle.replace("\\n", "\n")
        middle = middle.strip("\n")
        middle = middle.replace("\n", "\\n")
        return f'"private_key": "{begin}\\n{middle}\\n{end}\\n"'

    repaired, n = pattern.subn(_repl, text)
    if n == 0:
        # fallback: весь текст — убрать голые control chars вне строк сложно;
        # попробуем заменить реальные переносы только между BEGIN/END маркерами
        marker = "-----BEGIN PRIVATE KEY-----"
        end = "-----END PRIVATE KEY-----"
        if marker in text and end in text:
            i = text.find(marker)
            j = text.find(end) + len(end)
            chunk = text[i:j]
            chunk_esc = chunk.replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
            chunk_esc = chunk_esc.replace("\n", "\\n")
            # если private_key уже в кавычках с переносами — переписать целиком значение
            repaired = re.sub(
                r'"private_key"\s*:\s*"[\s\S]*?"',
                f'"private_key": "{chunk_esc}\\n"',
                text,
                count=1,
            )
    return repaired


def _service_account_info() -> dict:
    raw_text = None
    try:
        import streamlit as st

        if hasattr(st, "secrets"):
            if "google_service_account" in st.secrets:
                section = st.secrets["google_service_account"]
                info = {k: section[k] for k in section}
                if "private_key" in info and isinstance(info["private_key"], str):
                    info["private_key"] = info["private_key"].replace("\\n", "\n")
                return info
            raw = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON")
            if raw is not None:
                if isinstance(raw, dict):
                    return dict(raw)
                raw_text = str(raw)
    except Exception as exc:
                raise RuntimeError(f"Не удалось прочитать Secrets Google: {exc}") from exc

    if raw_text is None:
        path = os.path.join(os.path.dirname(__file__), "google_service_account.json")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        raise RuntimeError("Нет ключа Google service account в Secrets.")

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        repaired = _repair_service_account_json(raw_text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "JSON ключа Google повреждён (часто из‑за переноса private_key). "
                "Вставьте файл ключа целиком, не разбивая private_key на строки. "
                f"Детали: {exc}"
            ) from exc


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
        params={
            "q": q,
            "spaces": "drive",
            "fields": "files(id,name)",
            "pageSize": 5,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Drive list error {r.status_code}: {r.text[:400]}")
    files = (r.json() or {}).get("files") or []
    return files[0] if files else None


def _configured_file_id() -> str | None:
    _ensure_env()
    try:
        import streamlit as st

        if hasattr(st, "secrets") and st.secrets.get("GOOGLE_DRIVE_FILE_ID"):
            return str(st.secrets["GOOGLE_DRIVE_FILE_ID"]).strip()
    except Exception:
        pass
    return os.getenv("GOOGLE_DRIVE_FILE_ID", "").strip() or None


def load_store_dict() -> dict:
    """Читает shared_kpi.json из папки Drive."""
    file_id = _configured_file_id()
    meta = None
    if file_id:
        meta = {"id": file_id, "name": FILE_NAME}
    else:
        meta = _find_file(FILE_NAME, folder_id())
    if not meta:
        return {"timezone": "Asia/Tashkent", "version": 2, "days": {}}

    r = requests.get(
        f"{DRIVE_API}/files/{meta['id']}",
        headers=_headers(),
        params={"alt": "media", "supportsAllDrives": "true"},
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
    """
    Обновляет existing shared_kpi.json.
    Создавать файл сервисным аккаунтом нельзя (нет квоты) —
    файл должен заранее создать человек в Drive и расшарить на SA.
    """
    data = json.dumps(store, ensure_ascii=False, indent=2).encode("utf-8")
    file_id = _configured_file_id()
    existing = {"id": file_id, "name": FILE_NAME} if file_id else _find_file(FILE_NAME, folder_id())
    headers = _headers()

    if not existing:
        raise RuntimeError(
            "В папке Drive нет файла shared_kpi.json. "
            "Создайте его вручную в вашей папке (содержимое: "
            '{"timezone":"Asia/Tashkent","version":2,"days":{}} ), '
            "расшарьте папку на akela-streamlit@... как Редактор, "
            "затем повторите загрузку."
        )

    r = requests.patch(
        f"{UPLOAD_API}/files/{existing['id']}",
        headers={**headers, "Content-Type": "application/json"},
        params={"uploadType": "media", "supportsAllDrives": "true"},
        data=data,
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Drive update error {r.status_code}: {r.text[:500]}")
    return {"file_id": existing["id"], "name": FILE_NAME}
