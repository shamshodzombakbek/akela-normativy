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
APP_VERSION = "1.5"

# Windows keycodes (не зависят от RU/EN раскладки)
_KC_A, _KC_C, _KC_V, _KC_X = 65, 67, 86, 88

_REASON_RU = {
    "no_download_link": "нет файла / не успел",
    "open_failed": "не открылся отчёт",
    "popup_missing": "попап не появился",
    "download_failed": "скачивание не удалось",
    "not_found": "не найден в таблице",
    "error": "ошибка",
}


def _bind_clipboard(entry: ttk.Entry) -> None:
    """Ctrl+V/C/X/A и ПКМ-меню. На Windows с русской раскладкой keysym не работает — берём keycode."""

    def paste(_event=None):
        try:
            text = entry.clipboard_get()
        except tk.TclError:
            return "break"
        try:
            if entry.selection_present():
                entry.delete(tk.SEL_FIRST, tk.SEL_LAST)
            entry.insert(tk.INSERT, text)
        except tk.TclError:
            pass
        return "break"

    def copy(_event=None):
        try:
            if entry.selection_present():
                text = entry.selection_get()
                entry.clipboard_clear()
                entry.clipboard_append(text)
                entry.update()
        except tk.TclError:
            pass
        return "break"

    def cut(_event=None):
        copy()
        try:
            if entry.selection_present():
                entry.delete(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            pass
        return "break"

    def select_all(_event=None):
        entry.select_range(0, tk.END)
        entry.icursor(tk.END)
        return "break"

    def on_ctrl_key(event):
        code = int(getattr(event, "keycode", 0) or 0)
        if code == _KC_V:
            return paste(event)
        if code == _KC_C:
            return copy(event)
        if code == _KC_X:
            return cut(event)
        if code == _KC_A:
            return select_all(event)
        return None

    entry.bind("<Control-KeyPress>", on_ctrl_key)
    entry.bind("<Shift-Insert>", paste)
    entry.bind("<<Paste>>", paste)
    entry.bind("<<Copy>>", copy)
    entry.bind("<<Cut>>", cut)

    menu = tk.Menu(entry, tearoff=0)
    menu.add_command(label="Вырезать", command=cut)
    menu.add_command(label="Копировать", command=copy)
    menu.add_command(label="Вставить", command=paste)
    menu.add_separator()
    menu.add_command(label="Выделить всё", command=select_all)

    def show_menu(event):
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    entry.bind("<Button-3>", show_menu)
    entry.bind("<Button-2>", show_menu)


class SyncApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("720x780")
        self.minsize(600, 620)

        self._cfg = load_config()
        self._auto_running = False
        self._auto_thread: threading.Thread | None = None
        self._busy = False
        self._skipped_rows: list[dict] = []

        self._build_ui()
        self._load_fields()

        if is_configured(self._cfg):
            self._append_log("Настройки загружены. Авто: 16:00–18:30 (Ташкент).")
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
            text="Авто: каждые N мин в окне 16:00–18:30 (Ташкент). "
            "Кнопка «Сейчас» — в любой момент. Ниже — кто не успел сдать файл.",
            wraplength=680,
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
        ttk.Button(
            act_row,
            text="Синхронизировать сейчас",
            command=self._sync_now,
        ).pack(side=tk.LEFT)
        self._auto_btn = ttk.Button(act_row, text="Запустить авто", command=self._toggle_auto)
        self._auto_btn.pack(side=tk.LEFT, padx=8)
        self._status = ttk.Label(act_row, text="Статус: ожидание")
        self._status.pack(side=tk.LEFT, padx=8)

        missing = ttk.LabelFrame(
            frm,
            text="Не загружены (можно выбрать и добавить на сайт)",
        )
        missing.pack(fill=tk.BOTH, expand=False, **pad)

        ttk.Label(
            missing,
            text="После синхронизации здесь — сотрудники без Excel. "
            "Выделите нужных (Ctrl/Shift) и нажмите «Добавить выбранных».",
            wraplength=680,
        ).pack(anchor=tk.W, padx=8, pady=2)

        list_wrap = ttk.Frame(missing)
        list_wrap.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        scroll = ttk.Scrollbar(list_wrap)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._missing_list = tk.Listbox(
            list_wrap,
            selectmode=tk.EXTENDED,
            height=8,
            exportselection=False,
            yscrollcommand=scroll.set,
        )
        self._missing_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=self._missing_list.yview)

        miss_btns = ttk.Frame(missing)
        miss_btns.pack(fill=tk.X, padx=8, pady=6)
        ttk.Button(miss_btns, text="Выбрать всех", command=self._select_all_missing).pack(
            side=tk.LEFT
        )
        ttk.Button(miss_btns, text="Снять выбор", command=self._clear_missing_selection).pack(
            side=tk.LEFT, padx=6
        )
        self._add_btn = ttk.Button(
            miss_btns,
            text="Добавить выбранных",
            command=self._add_selected,
        )
        self._add_btn.pack(side=tk.LEFT, padx=6)
        self._missing_count = ttk.Label(miss_btns, text="0 чел.")
        self._missing_count.pack(side=tk.LEFT, padx=8)

        log_frame = ttk.LabelFrame(frm, text="Журнал")
        log_frame.pack(fill=tk.BOTH, expand=True, **pad)
        self._log = scrolledtext.ScrolledText(log_frame, height=10, state=tk.DISABLED)
        self._log.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _row(self, parent: ttk.LabelFrame, label: str, var: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(row, text=label, width=22).pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        _bind_clipboard(entry)

    def _row_password(self, parent: ttk.LabelFrame) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(row, text="Пароль Битрикс24", width=22).pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=self._password, show="•")
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        _bind_clipboard(entry)

    def _row_key(self, parent: ttk.LabelFrame) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(row, text="Google JSON ключ", width=22).pack(side=tk.LEFT)
        entry = ttk.Entry(row, textvariable=self._key_path)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        _bind_clipboard(entry)
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

    def _reason_label(self, reason: str) -> str:
        return _REASON_RU.get(str(reason or ""), str(reason or "—"))

    def _set_missing(self, rows: list[dict], *, merge: bool = False) -> None:
        """Обновить список «не загружены»."""
        if merge and self._skipped_rows:
            by_id = {int(r.get("report_id") or 0): r for r in self._skipped_rows}
            for r in rows:
                rid = int(r.get("report_id") or 0)
                if rid:
                    by_id[rid] = r
            rows = list(by_id.values())

        # убрать тех, кого только что успешно скачали — делается отдельно
        self._skipped_rows = [
            r for r in rows if int(r.get("report_id") or 0) > 0
        ]
        self._skipped_rows.sort(
            key=lambda r: str(r.get("employee") or "").casefold()
        )

        self._missing_list.delete(0, tk.END)
        for r in self._skipped_rows:
            name = str(r.get("employee") or "—")
            why = self._reason_label(str(r.get("reason") or ""))
            detail = str(r.get("detail") or "").strip()
            line = f"{name}  ·  {why}"
            if detail and detail not in why:
                line += f" ({detail[:60]})"
            self._missing_list.insert(tk.END, line)
        self._missing_count.configure(text=f"{len(self._skipped_rows)} чел.")

    def _remove_downloaded_from_missing(self, downloaded: list[dict]) -> None:
        done = {int(r.get("report_id") or 0) for r in downloaded}
        done.discard(0)
        if not done:
            return
        left = [
            r for r in self._skipped_rows if int(r.get("report_id") or 0) not in done
        ]
        self._set_missing(left)

    def _select_all_missing(self) -> None:
        self._missing_list.select_set(0, tk.END)

    def _clear_missing_selection(self) -> None:
        self._missing_list.selection_clear(0, tk.END)

    def _selected_report_ids(self) -> list[int]:
        idxs = self._missing_list.curselection()
        ids: list[int] = []
        for i in idxs:
            if 0 <= i < len(self._skipped_rows):
                rid = int(self._skipped_rows[i].get("report_id") or 0)
                if rid:
                    ids.append(rid)
        return ids

    def _sync_now(self) -> None:
        if self._busy:
            return
        if not is_configured(self._cfg):
            messagebox.showwarning("Настройки", "Сначала сохраните настройки.")
            return
        threading.Thread(
            target=self._run_sync, kwargs={"force": True}, daemon=True
        ).start()

    def _add_selected(self) -> None:
        if self._busy:
            return
        if not is_configured(self._cfg):
            messagebox.showwarning("Настройки", "Сначала сохраните настройки.")
            return
        ids = self._selected_report_ids()
        if not ids:
            messagebox.showinfo(
                "Выбор",
                "Выделите в списке сотрудников, которых нужно добавить.",
            )
            return
        names = [
            str(self._skipped_rows[i].get("employee") or "")
            for i in self._missing_list.curselection()
            if 0 <= i < len(self._skipped_rows)
        ]
        ok = messagebox.askyesno(
            "Добавить выбранных",
            f"Докачать и добавить на сайт ({len(ids)}):\n"
            + "\n".join(f"• {n}" for n in names[:12])
            + ("\n…" if len(names) > 12 else ""),
        )
        if not ok:
            return
        threading.Thread(
            target=self._run_sync,
            kwargs={"force": True, "only_report_ids": ids, "replace": False},
            daemon=True,
        ).start()

    def _run_sync(
        self,
        *,
        force: bool = False,
        only_report_ids: list[int] | None = None,
        replace: bool | None = None,
    ) -> None:
        self._busy = True
        self.after(0, lambda: self._set_status("синхронизация…"))
        self.after(0, lambda: self._add_btn.configure(state=tk.DISABLED))

        def on_log(m: str) -> None:
            self.after(0, lambda msg=m: self._append_log(msg))

        result = run_sync_once(
            force=force,
            on_log=on_log,
            only_report_ids=only_report_ids,
            replace=replace,
        )
        self.after(0, lambda: self._finish_sync(result, selective=bool(only_report_ids)))

    def _finish_sync(self, result: dict, *, selective: bool = False) -> None:
        self._busy = False
        self._add_btn.configure(state=tk.NORMAL)
        ok = bool(result.get("ok"))
        outside = bool(result.get("outside_window"))
        if outside:
            self._set_status("ожидание окна 16:00–18:30")
            return

        skipped = list(result.get("skipped_reports") or [])
        downloaded = list(result.get("downloaded_reports") or [])

        if selective:
            self._remove_downloaded_from_missing(downloaded)
            # тех, кого снова не удалось — обновить/оставить
            if skipped:
                self._set_missing(skipped, merge=True)
            self._set_status(
                f"добавлено {len(downloaded)}" if downloaded else "не добавлено"
            )
            if downloaded:
                messagebox.showinfo(
                    "Готово",
                    f"Добавлено на сайт: {len(downloaded)}.\n"
                    f"Осталось без файла: {len(self._skipped_rows)}.",
                )
        else:
            self._set_missing(skipped)
            self._set_status("OK" if ok else "есть не загруженные / ошибка")
            if skipped:
                self._append_log(
                    f"Не загружено: {len(skipped)} — выберите в списке и нажмите "
                    "«Добавить выбранных»."
                )

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
        self._set_status("авто · 16:00–18:30")
        self._append_log("Автосинхронизация запущена (только 16:00–18:30).")
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
