"""Akela Normativ Sync — десктопная программа синхронизации с сайтом."""

from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

# Корень проекта (для импорта bitrix_fetch и т.д.)
if getattr(sys, "frozen", False):
    _ROOT = Path(sys._MEIPASS)
else:
    _ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from desktop_sync.config_store import (  # noqa: E402
    AppConfig,
    config_dir,
    is_configured,
    load_config,
    save_config,
)
from desktop_sync.worker import run_sync_once  # noqa: E402

APP_TITLE = "Akela · Синхронизация нормативов"
APP_VERSION = "1.0"


class SyncApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("680x640")
        self.minsize(560, 500)

        self._cfg = load_config()
        self._auto_running = False
        self._auto_thread: threading.Thread | None = None
        self._busy = False

        self._build_ui()
        self._load_fields()

        if is_configured(self._cfg):
            self._append_log("Настройки загружены. Можно запустить автосинхронизацию.")
            if self._cfg.auto_sync:
                self.after(800, self._start_auto)
        else:
            self._append_log("Заполните настройки и нажмите «Сохранить».")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        ttk.Label(frm, text=f"{APP_TITLE}  v{APP_VERSION}", font=("", 12, "bold")).pack(
            anchor=tk.W, **pad
        )
        ttk.Label(
            frm,
            text="Качает Excel из «Отчёты о работе» в Битрикс24, кладёт на Диск "
            "(папка Akela Normativy / дата), сайт берёт файлы оттуда.",
            wraplength=620,
        ).pack(anchor=tk.W, padx=10)

        settings = ttk.LabelFrame(frm, text="Настройки (один раз)")
        settings.pack(fill=tk.X, **pad)

        self._webhook = tk.StringVar()
        self._login = tk.StringVar()
        self._password = tk.StringVar()
        self._portal = tk.StringVar(value="https://akelagroup.bitrix24.ru")
        self._folder_id = tk.StringVar()
        self._key_path = tk.StringVar()
        self._normativ_folder = tk.StringVar(value="Akela Normativy")
        self._interval = tk.IntVar(value=10)
        self._auto_var = tk.BooleanVar(value=True)
        self._show_browser = tk.BooleanVar(value=False)

        self._row(settings, "BITRIX webhook URL", self._webhook)
        self._row(settings, "Логин Битрикс24", self._login)
        self._row_password(settings)
        self._row(settings, "Портал", self._portal)
        self._row(settings, "Google Drive folder ID", self._folder_id)
        self._row_key(settings)
        self._row(settings, "Папка на Диске", self._normativ_folder)

        row_iv = ttk.Frame(settings)
        row_iv.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(row_iv, text="Интервал (мин)", width=22).pack(side=tk.LEFT)
        ttk.Spinbox(row_iv, from_=5, to=60, textvariable=self._interval, width=8).pack(
            side=tk.LEFT
        )
        ttk.Checkbutton(row_iv, text="Автосинхронизация при запуске", variable=self._auto_var).pack(
            side=tk.LEFT, padx=12
        )
        ttk.Checkbutton(row_iv, text="Показать браузер", variable=self._show_browser).pack(
            side=tk.LEFT, padx=8
        )

        btn_row = ttk.Frame(settings)
        btn_row.pack(fill=tk.X, padx=8, pady=6)
        ttk.Button(btn_row, text="Сохранить настройки", command=self._save).pack(side=tk.LEFT)
        ttk.Label(btn_row, text=f"Конфиг: {config_dir()}", foreground="gray").pack(
            side=tk.LEFT, padx=8
        )

        actions = ttk.LabelFrame(frm, text="Синхронизация")
        actions.pack(fill=tk.X, **pad)

        act_row = ttk.Frame(actions)
        act_row.pack(fill=tk.X, padx=8, pady=6)
        ttk.Button(act_row, text="Синхронизировать сейчас", command=self._sync_now).pack(
            side=tk.LEFT
        )
        self._auto_btn = ttk.Button(act_row, text="Запустить авто", command=self._toggle_auto)
        self._auto_btn.pack(side=tk.LEFT, padx=8)
        self._status = ttk.Label(act_row, text="Статус: ожидание")
        self._status.pack(side=tk.LEFT, padx=8)

        log_frame = ttk.LabelFrame(frm, text="Журнал")
        log_frame.pack(fill=tk.BOTH, expand=True, **pad)
        self._log = scrolledtext.ScrolledText(log_frame, height=12, state=tk.DISABLED)
        self._log.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _row(self, parent: ttk.LabelFrame, label: str, var: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(row, text=label, width=22).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _row_password(self, parent: ttk.LabelFrame) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(row, text="Пароль Битрикс24", width=22).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self._password, show="•").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

    def _row_key(self, parent: ttk.LabelFrame) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(row, text="Google JSON ключ", width=22).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self._key_path).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Обзор…", command=self._browse_key).pack(side=tk.LEFT, padx=4)

    def _browse_key(self) -> None:
        path = filedialog.askopenfilename(
            title="Файл ключа Google Service Account",
            filetypes=[("JSON", "*.json"), ("Все файлы", "*.*")],
        )
        if path:
            self._key_path.set(path)

    def _load_fields(self) -> None:
        c = self._cfg
        self._webhook.set(c.bitrix_webhook_url)
        self._login.set(c.bitrix_login)
        self._password.set(c.bitrix_password)
        self._portal.set(c.bitrix_portal or "https://akelagroup.bitrix24.ru")
        self._folder_id.set(c.google_drive_folder_id)
        self._key_path.set(c.google_key_path)
        self._normativ_folder.set(c.bitrix_normativ_folder or "Akela Normativy")
        self._interval.set(max(5, min(60, int(c.interval_minutes or 10))))
        self._auto_var.set(bool(c.auto_sync))
        self._show_browser.set(bool(c.show_browser))

    def _save(self) -> None:
        self._cfg = AppConfig(
            bitrix_webhook_url=self._webhook.get().strip(),
            bitrix_login=self._login.get().strip(),
            bitrix_password=self._password.get().strip(),
            bitrix_portal=self._portal.get().strip() or "https://akelagroup.bitrix24.ru",
            google_drive_folder_id=self._folder_id.get().strip(),
            google_key_path=self._key_path.get().strip(),
            bitrix_normativ_folder=self._normativ_folder.get().strip() or "Akela Normativy",
            auto_sync=bool(self._auto_var.get()),
            interval_minutes=int(self._interval.get() or 10),
            show_browser=bool(self._show_browser.get()),
        )
        if not is_configured(self._cfg):
            messagebox.showwarning(
                "Не хватает данных",
                "Укажите webhook, логин/пароль Битрикс, ID папки Google и JSON-ключ.",
            )
            return
        save_config(self._cfg)
        self._append_log("Настройки сохранены.")
        messagebox.showinfo("Сохранено", "Настройки сохранены. Запускаю автосинхронизацию.")
        if not self._auto_running:
            self.after(500, self._start_auto)

    def _append_log(self, msg: str) -> None:
        self._log.configure(state=tk.NORMAL)
        self._log.insert(tk.END, msg + "\n")
        self._log.see(tk.END)
        self._log.configure(state=tk.DISABLED)

    def _set_status(self, text: str) -> None:
        self._status.configure(text=f"Статус: {text}")

    def _sync_now(self) -> None:
        if self._busy:
            return
        if not is_configured(self._cfg):
            messagebox.showwarning("Настройки", "Сначала сохраните настройки.")
            return
        threading.Thread(target=self._run_sync, kwargs={"force": True}, daemon=True).start()

    def _run_sync(self, *, force: bool = False) -> None:
        self._busy = True
        self._set_status("синхронизация…")

        def on_log(m: str) -> None:
            self.after(0, lambda: self._append_log(m))

        ok, msg = run_sync_once(force=force, on_log=on_log)
        self.after(0, lambda: self._finish_sync(ok, msg))

    def _finish_sync(self, ok: bool, msg: str) -> None:
        self._busy = False
        self._set_status("OK" if ok else "ошибка / нет файлов")
        if not ok and "Вне окна" not in msg:
            self.after(0, lambda: None)  # log already has details

    def _toggle_auto(self) -> None:
        if self._auto_running:
            self._stop_auto()
        else:
            self._start_auto()

    def _start_auto(self) -> None:
        if not is_configured(self._cfg):
            messagebox.showwarning("Настройки", "Сначала сохраните настройки.")
            return
        if self._auto_running:
            return
        self._auto_running = True
        self._auto_btn.configure(text="Остановить авто")
        self._set_status("авто · работает")
        self._append_log("Автосинхронизация запущена.")
        self._auto_thread = threading.Thread(target=self._auto_loop, daemon=True)
        self._auto_thread.start()

    def _stop_auto(self) -> None:
        self._auto_running = False
        self._auto_btn.configure(text="Запустить авто")
        self._set_status("авто остановлена")
        self._append_log("Автосинхронизация остановлена.")

    def _auto_loop(self) -> None:
        interval = max(5, int(self._interval.get() or 10)) * 60
        while self._auto_running:
            if not self._busy:
                self._run_sync(force=False)
            for _ in range(interval):
                if not self._auto_running:
                    break
                time.sleep(1)

    def _on_close(self) -> None:
        self._auto_running = False
        self._cfg.auto_sync = bool(self._auto_var.get())
        save_config(self._cfg)
        self.destroy()


def main() -> None:
    if "--background" in sys.argv:
        from desktop_sync.background import run_background

        run_background()
        return
    app = SyncApp()
    app.mainloop()


if __name__ == "__main__":
    main()
