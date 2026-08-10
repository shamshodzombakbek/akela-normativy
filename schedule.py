"""Расписание окна обновления (Ташкент): 16:00–20:00, без воскресенья."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tashkent")
WINDOW_START = time(16, 0)
WINDOW_END = time(20, 0)


def now_tashkent() -> datetime:
    return datetime.now(TZ)


def is_sunday(d: date) -> bool:
    return d.weekday() == 6  # Mon=0 … Sun=6


def skip_sunday(d: date) -> date:
    """Если день — воскресенье, берём субботу."""
    if is_sunday(d):
        return d - timedelta(days=1)
    return d


def previous_work_day(d: date) -> date:
    """Вчера относительно d, воскресенье пропускаем → суббота."""
    return skip_sunday(d - timedelta(days=1))


def active_window_day(now: datetime | None = None) -> date:
    """
    Текущий слот отчёта:
    - воскресенье → всегда суббота;
    - до 16:00 → предыдущий рабочий слот (вс пропускаем);
    - с 16:00 → сегодняшний день (вс не бывает).
    """
    now = now or now_tashkent()
    today = now.date()
    t = now.timetz().replace(tzinfo=None)

    # Воскресенье: слота нет — показываем субботу
    if is_sunday(today):
        return today - timedelta(days=1)

    if t < WINDOW_START:
        # Пн утро → вс → сб; остальные → вчера
        return previous_work_day(today)

    return today


def is_fetch_window(now: datetime | None = None) -> bool:
    """16:00–20:00, в воскресенье обновления нет."""
    now = now or now_tashkent()
    if is_sunday(now.date()):
        return False
    t = now.timetz().replace(tzinfo=None)
    return WINDOW_START <= t <= WINDOW_END


def is_after_upload_deadline(now: datetime | None = None) -> bool:
    """После 20:00 по Ташкенту (в этот календарный день)."""
    now = now or now_tashkent()
    t = now.timetz().replace(tzinfo=None)
    return t > WINDOW_END


def can_upload_for_day(day: date, now: datetime | None = None) -> tuple[bool, str]:
    """
    Можно ли добавить Excel в слот day.
    После 20:00 (Ташкент) — нельзя добавлять за сегодняшний день.
    """
    now = now or now_tashkent()
    today = now.date()
    t = now.timetz().replace(tzinfo=None)

    if is_sunday(today):
        return False, "В воскресенье загрузка отчётов закрыта."

    if day == today and t > WINDOW_END:
        return (
            False,
            "После 20:00 (Ташкент) нельзя добавить отчёты за сегодня. "
            "Слот закроется до следующего рабочего дня (с 16:00).",
        )

    # прошлые слоты не трогаем после наступления нового активного дня
    active = active_window_day(now)
    if day < active:
        return (
            False,
            f"День {day.strftime('%d.%m.%Y')} уже закрыт для загрузки. "
            f"Активный слот: {active.strftime('%d.%m.%Y')}.",
        )

    return True, ""


def bitrix_target_day(window_day: date) -> date:
    """
    За какой день качать Normativ.
    Окно D → вчера; если вчера воскресенье → суббота.
    Пример: понедельник 16:00 → Битрикс за субботу.
    """
    return previous_work_day(window_day)


def status_label(now: datetime | None = None) -> str:
    now = now or now_tashkent()
    day = active_window_day(now)
    if is_sunday(now.date()):
        return f"Воскресенье · обновлений нет · показ субботы {day.strftime('%d.%m.%Y')}"
    if is_fetch_window(now):
        return (
            f"Идёт обновление · слот {day.strftime('%d.%m.%Y')} · "
            f"Битрикс за {bitrix_target_day(day).strftime('%d.%m.%Y')}"
        )
    if now.date() == day and now.timetz().replace(tzinfo=None) > WINDOW_END:
        return f"Окно закрыто · показ результата за {day.strftime('%d.%m.%Y')} до 16:00 следующего рабочего дня"
    return f"Показ сохранённого результата · слот {day.strftime('%d.%m.%Y')}"
