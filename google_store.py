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
    raw = os.getenv("GOOGLE_DRIVE_FOLDER_ID", FOLDER_ID_DEFAULT).strip().strip('"').strip("'")
    return raw


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
        sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "").strip()
        if sa_path and os.path.isfile(sa_path):
            with open(sa_path, encoding="utf-8") as f:
                return json.load(f)
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


DOCS_EDITORS_MIME = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
    "application/vnd.google-apps.drawing",
}
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"


def _empty_store() -> dict:
    return {"timezone": "Asia/Tashkent", "version": 2, "days": {}}


def _sa_email() -> str:
    try:
        info = _service_account_info()
        return str(info.get("client_email") or "akela-streamlit@...")
    except Exception:
        return "akela-streamlit@..."


def _file_hint(meta: dict) -> str:
    fid = meta.get("id") or "?"
    mime = meta.get("mimeType") or "?"
    return f"id={fid}, mime={mime}"


def _get_file_meta(file_id: str) -> dict:
    r = requests.get(
        f"{DRIVE_API}/files/{file_id}",
        headers=_headers(),
        params={
            "fields": "id,name,mimeType,parents,shortcutDetails,size",
            "supportsAllDrives": "true",
        },
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Drive meta error {r.status_code}: {r.text[:400]}")
    return r.json()


def _resolve_meta(meta: dict) -> dict:
    """Разворачивает ярлык Google Drive до целевого файла."""
    mime = (meta.get("mimeType") or "").strip()
    if mime != SHORTCUT_MIME:
        return meta
    target = (meta.get("shortcutDetails") or {}).get("targetId")
    if not target:
        raise RuntimeError(f"shared_kpi.json — ярлык без цели ({_file_hint(meta)})")
    return _get_file_meta(target)


def _list_folder_children(parent: str) -> list[dict]:
    """Все файлы в папке (без опоры только на name= query)."""
    out: list[dict] = []
    page_token = None
    while True:
        params: dict[str, Any] = {
            "q": f"'{parent}' in parents and trashed = false",
            "spaces": "drive",
            "fields": "nextPageToken,files(id,name,mimeType,shortcutDetails,size)",
            "pageSize": 100,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "corpora": "allDrives",
        }
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(
            f"{DRIVE_API}/files",
            headers=_headers(),
            params=params,
            timeout=60,
        )
        if r.status_code >= 400:
            # fallback без corpora=allDrives (обычные shared folders)
            params.pop("corpora", None)
            r = requests.get(
                f"{DRIVE_API}/files",
                headers=_headers(),
                params=params,
                timeout=60,
            )
        if r.status_code >= 400:
            raise RuntimeError(f"Drive list error {r.status_code}: {r.text[:400]}")
        payload = r.json() or {}
        out.extend(payload.get("files") or [])
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return out


def _list_by_exact_name(name: str) -> list[dict]:
    """Поиск по имени во всех доступных дисках (если parent-query пуст)."""
    q = f"name = '{name}' and trashed = false"
    r = requests.get(
        f"{DRIVE_API}/files",
        headers=_headers(),
        params={
            "q": q,
            "spaces": "drive",
            "fields": "files(id,name,mimeType,parents,shortcutDetails,size)",
            "pageSize": 20,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "corpora": "allDrives",
        },
        timeout=60,
    )
    if r.status_code >= 400:
        r = requests.get(
            f"{DRIVE_API}/files",
            headers=_headers(),
            params={
                "q": q,
                "spaces": "drive",
                "fields": "files(id,name,mimeType,parents,shortcutDetails,size)",
                "pageSize": 20,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
            timeout=60,
        )
    if r.status_code >= 400:
        raise RuntimeError(f"Drive name search error {r.status_code}: {r.text[:400]}")
    return list((r.json() or {}).get("files") or [])


def _name_matches(file_name: str | None, want: str = FILE_NAME) -> bool:
    if not file_name:
        return False
    return file_name.strip().casefold() == want.casefold()


def _score_candidate(meta: dict) -> int:
    mime = (meta.get("mimeType") or "").strip()
    if mime in ("application/json", "application/octet-stream", "text/plain", "text/json"):
        return 0
    if not mime.startswith("application/vnd.google-apps."):
        return 1
    if mime in DOCS_EDITORS_MIME:
        return 5
    if mime == SHORTCUT_MIME:
        return 6
    return 9


def _pick_best_file(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    resolved: list[dict] = []
    for raw in candidates:
        mime = (raw.get("mimeType") or "").strip()
        if mime == "application/vnd.google-apps.folder":
            continue
        try:
            resolved.append(_resolve_meta(raw))
        except RuntimeError:
            # оставляем как есть — разберёмся при download
            resolved.append(raw)
    if not resolved:
        return None
    resolved.sort(key=_score_candidate)
    return resolved[0]


def _folder_diag(parent: str, children: list[dict]) -> str:
    names = [f"{c.get('name')} [{c.get('mimeType')}]" for c in children[:15]]
    sample = "; ".join(names) if names else "(пусто)"
    return (
        f"folder_id={parent}, SA={_sa_email()}, файлов в папке={len(children)}. "
        f"Видно: {sample}. "
        f"Папка должна быть расшарена на {_sa_email()} как Редактор."
    )


def _find_store_file() -> dict | None:
    configured = _configured_file_id()
    if configured:
        return _resolve_meta(_get_file_meta(configured))

    parent = folder_id()
    children = _list_folder_children(parent)
    named = [c for c in children if _name_matches(c.get("name"))]
    if named:
        return _pick_best_file(named)

    # fallback: файл есть, но parent query не видит (права/кэш) — поиск по имени
    worldwide = _list_by_exact_name(FILE_NAME)
    in_folder = [
        f
        for f in worldwide
        if parent in (f.get("parents") or [])
    ]
    if in_folder:
        return _pick_best_file(in_folder)
    if worldwide:
        # берём первый доступный shared_kpi.json
        return _pick_best_file(worldwide)

    return None


def _not_found_error() -> RuntimeError:
    parent = folder_id()
    try:
        children = _list_folder_children(parent)
    except Exception as exc:
        return RuntimeError(
            f"Не удалось прочитать папку Drive ({parent}): {exc}. "
            f"Проверьте GOOGLE_DRIVE_FOLDER_ID и доступ Редактор для {_sa_email()}."
        )
    return RuntimeError(
        f"В папке Drive не найден shared_kpi.json. {_folder_diag(parent, children)}"
    )


def _download_media(file_id: str) -> tuple[bytes | None, str]:
    r = requests.get(
        f"{DRIVE_API}/files/{file_id}",
        headers=_headers(),
        params={"alt": "media", "supportsAllDrives": "true"},
        timeout=60,
    )
    if r.status_code < 400:
        return r.content, ""
    return None, f"{r.status_code}: {r.text[:300]}"


def _download_export(file_id: str) -> tuple[bytes | None, str]:
    last_err = ""
    for export_mime in ("text/plain", "application/json"):
        r = requests.get(
            f"{DRIVE_API}/files/{file_id}/export",
            headers=_headers(),
            params={"mimeType": export_mime},
            timeout=60,
        )
        if r.status_code < 400:
            return r.content, ""
        last_err = f"{r.status_code}: {r.text[:200]}"
    return None, last_err


def _download_file_bytes(file_meta: dict) -> bytes:
    """Сначала binary download, потом export — по факту ответа API, не по иконке UI."""
    meta = _resolve_meta(file_meta)
    file_id = meta["id"]
    mime = (meta.get("mimeType") or "").strip()

    raw, media_err = _download_media(file_id)
    if raw is not None:
        return raw

    if mime in DOCS_EDITORS_MIME or "fileNotDownloadable" in media_err:
        raw, export_err = _download_export(file_id)
        if raw is not None:
            return raw
        raise RuntimeError(
            f"Не удалось скачать shared_kpi.json ({_file_hint(meta)}). "
            f"media={media_err}; export={export_err}"
        )

    raise RuntimeError(
        f"Не удалось скачать shared_kpi.json ({_file_hint(meta)}): {media_err}"
    )


def _configured_file_id() -> str | None:
    _ensure_env()
    try:
        import streamlit as st

        if hasattr(st, "secrets") and st.secrets.get("GOOGLE_DRIVE_FILE_ID"):
            return str(st.secrets["GOOGLE_DRIVE_FILE_ID"]).strip() or None
    except Exception:
        pass
    return os.getenv("GOOGLE_DRIVE_FILE_ID", "").strip() or None


def _is_binary_upload(meta: dict) -> bool:
    mime = (meta.get("mimeType") or "").strip()
    return bool(mime) and not mime.startswith("application/vnd.google-apps.")


def load_store_dict() -> dict:
    """Читает shared_kpi.json из папки Drive."""
    meta = _find_store_file()
    if not meta:
        # нет файла — пустой store (создание при первой публикации)
        return _empty_store()

    raw = _download_file_bytes(meta)
    try:
        text = raw.decode("utf-8-sig").strip()
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        payload = json.loads(text)
    except Exception:
        payload = {}
    if not isinstance(payload, dict) or "days" not in payload:
        return _empty_store()
    return payload


def save_store_dict(store: dict) -> dict[str, Any]:
    """Обновляет shared_kpi.json. Нужен обычный загруженный файл (не Google Docs)."""
    data = json.dumps(store, ensure_ascii=False, indent=2).encode("utf-8")
    existing = _find_store_file()

    if not existing:
        raise _not_found_error()

    existing = _resolve_meta(existing)
    if not _is_binary_upload(existing):
        raise RuntimeError(
            f"shared_kpi.json найден, но это Google Apps ({_file_hint(existing)}), "
            "а не загруженный файл. Нужен MIME вроде application/json. "
            "Удалите объект и загрузите .json через «Загрузка файла» "
            f"или укажите GOOGLE_DRIVE_FILE_ID бинарного файла. SA={_sa_email()}"
        )

    r = requests.patch(
        f"{UPLOAD_API}/files/{existing['id']}",
        headers={**_headers(), "Content-Type": "application/json"},
        params={"uploadType": "media", "supportsAllDrives": "true"},
        data=data,
        timeout=60,
    )
    if r.status_code >= 400:
        raise RuntimeError(
            f"Drive update error {r.status_code}: {r.text[:500]} ({_file_hint(existing)})"
        )
    return {"file_id": existing["id"], "name": FILE_NAME, "mimeType": existing.get("mimeType")}
