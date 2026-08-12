"""Настройки десктопной программы (вне папки установки)."""

from __future__ import annotations

import json
import os
import platform
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class AppConfig:
    bitrix_webhook_url: str = ""
    bitrix_login: str = ""
    bitrix_password: str = ""
    bitrix_portal: str = "https://akelagroup.bitrix24.ru"
    google_drive_folder_id: str = ""
    google_key_path: str = ""
    bitrix_normativ_folder: str = "Akela Normativy"
    auto_sync: bool = True
    interval_minutes: int = 10
    show_browser: bool = False


def config_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"
    path = base / "AkelaNormativSync"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> AppConfig:
    path = config_path()
    if not path.is_file():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AppConfig(**{k: data[k] for k in asdict(AppConfig()).keys() if k in data})
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig) -> None:
    config_path().write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_configured(cfg: AppConfig | None = None) -> bool:
    cfg = cfg or load_config()
    return bool(
        cfg.bitrix_webhook_url.strip()
        and cfg.bitrix_login.strip()
        and cfg.bitrix_password.strip()
        and cfg.google_drive_folder_id.strip()
        and cfg.google_key_path.strip()
        and Path(cfg.google_key_path).is_file()
    )


def apply_config_to_env(cfg: AppConfig | None = None) -> Path:
    """Пишет secrets в os.environ для Selenium, Диска и дашборда."""
    cfg = cfg or load_config()
    os.environ["BITRIX_WEBHOOK_URL"] = cfg.bitrix_webhook_url.strip()
    os.environ["BITRIX_LOGIN"] = cfg.bitrix_login.strip()
    os.environ["BITRIX_PASSWORD"] = cfg.bitrix_password.strip()
    os.environ["BITRIX_PORTAL"] = (
        cfg.bitrix_portal.strip() or "https://akelagroup.bitrix24.ru"
    )
    os.environ["BITRIX_HEADLESS"] = "false" if cfg.show_browser else "true"
    os.environ["BITRIX_COOKIE_PATH"] = str(config_dir() / "bitrix_cookies.json")
    os.environ["BITRIX_DOWNLOAD_DIR"] = str(config_dir() / "downloads")
    os.environ["GOOGLE_DRIVE_FOLDER_ID"] = cfg.google_drive_folder_id.strip()
    if cfg.bitrix_normativ_folder.strip():
        os.environ["BITRIX_NORMATIV_FOLDER"] = cfg.bitrix_normativ_folder.strip()

    dest = config_dir() / "google_service_account.json"
    src = Path(cfg.google_key_path)
    if src.is_file():
        shutil.copy2(src, dest)
    os.environ["GOOGLE_SERVICE_ACCOUNT_PATH"] = str(dest)
    return dest


def log_path() -> Path:
    return config_dir() / "sync.log"
