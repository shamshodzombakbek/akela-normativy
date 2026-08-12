"""Фоновый режим: python AkelaNormativSync.exe --background (автозапуск Windows)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

if getattr(sys, "frozen", False):
    _ROOT = Path(sys._MEIPASS)
else:
    _ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from desktop_sync.config_store import apply_config_to_env, is_configured, load_config, log_path
from desktop_sync.worker import run_sync_once


def run_background() -> None:
    cfg = load_config()
    if not is_configured(cfg):
        with log_path().open("a", encoding="utf-8") as f:
            f.write("background: нет настроек — откройте программу и сохраните конфиг\n")
        return

    interval = max(5, int(cfg.interval_minutes or 10)) * 60
    with log_path().open("a", encoding="utf-8") as f:
        f.write("background: старт автосинхронизации\n")

    while True:
        run_sync_once(force=False)
        time.sleep(interval)


if __name__ == "__main__":
    run_background()
