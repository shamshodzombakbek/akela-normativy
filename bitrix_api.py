"""Загрузка KPI сотрудников из Битрикс24 (Учёт рабочего времени → Отчёты)."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

from utils import kpi_category

_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")


def _webhook_url() -> str:
    load_dotenv(_ENV_PATH, override=True)
    url = os.getenv("BITRIX_WEBHOOK_URL", "").strip()
    if not url:
        raise ValueError(
            "Не задан BITRIX_WEBHOOK_URL. Добавьте его в файл .env."
        )
    return url.rstrip("/") + "/"


def bitrix_call(method: str, params: dict | None = None) -> Any:
    """Вызов REST-метода Битрикс24 через входящий вебхук."""
    return bitrix_call_full(method, params).get("result")


def bitrix_call_full(method: str, params: dict | None = None) -> dict:
    """Вызов REST-метода с полным ответом (включая next для пагинации)."""
    response = requests.post(
        f"{_webhook_url()}{method}",
        json=params or {},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()

    if "error" in payload:
        error = payload.get("error")
        description = payload.get("error_description", "")
        raise RuntimeError(f"{error}: {description}")

    return payload


def _user_display_name(user: dict) -> str:
    name = " ".join(
        part
        for part in [
            user.get("LAST_NAME") or user.get("last_name") or "",
            user.get("NAME") or user.get("first_name") or "",
        ]
        if part
    ).strip()
    return name or user.get("name") or f"ID {user.get('ID') or user.get('id')}"


def get_departments() -> list[dict]:
    result = bitrix_call("department.get")
    return result or []


def get_report_settings() -> dict:
    return bitrix_call("timeman.timecontrol.reports.settings.get") or {}


def get_active_users(department_id: int | None = None) -> list[dict]:
    users: list[dict] = []
    start = 0
    filt: dict[str, Any] = {"ACTIVE": True}
    if department_id is not None:
        filt["UF_DEPARTMENT"] = department_id

    while True:
        payload = bitrix_call_full(
            "user.get",
            {
                "FILTER": filt,
                "start": start,
            },
        )
        batch = payload.get("result") or []
        if not isinstance(batch, list) or not batch:
            break

        users.extend(batch)

        next_start = payload.get("next")
        if next_start is None:
            break
        start = int(next_start)

    return users


def get_department_users(department_id: int | None = None) -> list[dict]:
    params: dict[str, Any] = {}
    if department_id is not None:
        params["DEPARTMENT_ID"] = department_id

    result = bitrix_call("timeman.timecontrol.reports.users.get", params)
    return result or []


def get_user_month_report(user_id: int, month: int, year: int) -> dict:
    result = bitrix_call(
        "timeman.timecontrol.reports.get",
        {
            "USER_ID": user_id,
            "MONTH": month,
            "YEAR": year,
            "WORKDAY_HOURS": 8,
        },
    )
    return result or {}


def get_user_month_reports_batch(
    user_ids: list[int],
    month: int,
    year: int,
    chunk_size: int = 50,
) -> dict[int, dict]:
    """Массовая загрузка отчётов через batch (до 50 за запрос)."""
    reports: dict[int, dict] = {}

    for i in range(0, len(user_ids), chunk_size):
        chunk = user_ids[i : i + chunk_size]
        cmd = {
            str(uid): (
                "timeman.timecontrol.reports.get"
                f"?USER_ID={uid}&MONTH={month}&YEAR={year}&WORKDAY_HOURS=8"
            )
            for uid in chunk
        }
        result = bitrix_call("batch", {"halt": 0, "cmd": cmd}) or {}
        result_map = result.get("result") or result

        if not isinstance(result_map, dict):
            continue

        for key, payload in result_map.items():
            try:
                reports[int(key)] = payload or {}
            except (TypeError, ValueError):
                continue

    return reports


def _extract_days(report_payload: dict) -> list[dict]:
    """Дни лежат в result.report.days (обёртка API Битрикс)."""
    if not report_payload:
        return []
    if isinstance(report_payload.get("days"), list):
        return report_payload["days"]
    nested = report_payload.get("report") or {}
    if isinstance(nested, dict) and isinstance(nested.get("days"), list):
        return nested["days"]
    return []


def calc_efficiency_percent(report_payload: dict) -> float | None:
    """
    Эффективность за месяц ≈ Σ(факт) / Σ(длительность смены) * 100.

    В Bitrix:
    - workday_duration — длительность смены по графику
    - workday_duration_final — фактическое время с учётом простоев
    - workday_time_leaks_real — простой/отсутствие
    """
    days = _extract_days(report_payload)
    if not days:
        return None

    total_final = 0
    total_schedule = 0

    for day in days:
        if not day.get("workday_date_start") and not day.get("workday_duration_final"):
            continue

        schedule = int(day.get("workday_duration") or 0)
        final = int(day.get("workday_duration_final") or 0)
        leaks_real = day.get("workday_time_leaks_real")

        if schedule <= 0:
            continue

        if leaks_real is not None:
            effective = max(schedule - int(leaks_real), 0)
        else:
            effective = min(final, schedule) if final else 0

        total_final += effective
        total_schedule += schedule

    if total_schedule <= 0:
        return None

    percent = total_final / total_schedule * 100
    return round(min(max(percent, 0), 100), 2)


def calc_day_efficiency_percent(day: dict | None) -> float | None:
    """Эффективность за один день."""
    if not day:
        return None
    if not day.get("workday_date_start") and not day.get("workday_duration_final"):
        return None

    schedule = int(day.get("workday_duration") or 0)
    final = int(day.get("workday_duration_final") or 0)
    leaks_real = day.get("workday_time_leaks_real")

    if schedule <= 0:
        return None

    if leaks_real is not None:
        effective = max(schedule - int(leaks_real), 0)
    else:
        effective = min(final, schedule) if final else 0

    percent = effective / schedule * 100
    return round(min(max(percent, 0), 100), 2)


def find_day(report_payload: dict, target: date) -> dict | None:
    """Находит день в месячном отчёте по дате."""
    want = target.strftime("%Y%m%d")
    title = target.strftime("%d.%m.%Y")
    for day in _extract_days(report_payload):
        if str(day.get("index") or "") == want:
            return day
        if str(day.get("day_title") or "") == title:
            return day
    return None


def _child_department_ids(root_id: int, departments: list[dict]) -> set[int]:
    """root + все дочерние подразделения из структуры."""
    by_parent: dict[int, list[int]] = {}
    for dept in departments:
        dept_id = int(dept.get("ID") or dept.get("id") or 0)
        parent_id = int(dept.get("PARENT") or dept.get("parent") or 0)
        if dept_id:
            by_parent.setdefault(parent_id, []).append(dept_id)

    result = {root_id}
    stack = [root_id]
    while stack:
        current = stack.pop()
        for child in by_parent.get(current, []):
            if child not in result:
                result.add(child)
                stack.append(child)
    return result


def _is_real_department_employee(user: dict) -> bool:
    """Отсекает системные/общие аккаунты, оставляет сотрудников отделов."""
    uid = int(user.get("id") or user.get("ID") or 0)
    if not uid or uid == 1:
        return False
    if user.get("active") is False or user.get("ACTIVE") is False:
        return False

    position = (
        user.get("work_position")
        or user.get("WORK_POSITION")
        or ""
    ).strip()
    # у реальных сотрудников в структуре обычно заполнена должность
    if not position:
        return False

    full_name = (
        user.get("name")
        or " ".join(
            part
            for part in [
                user.get("LAST_NAME") or user.get("last_name") or "",
                user.get("NAME") or user.get("first_name") or "",
            ]
            if part
        )
    ).strip().lower()

    blocked_tokens = (
        "bitrix",
        "backup",
        "akela group",
        "group info",
        "procurement agent",
    )
    if any(token in full_name for token in blocked_tokens):
        return False

    return True


def _collect_users(department_id: int | None = None) -> tuple[list[dict], list[str], bool, bool]:
    """
    Только сотрудники из структуры компании (подразделения):
    список из timeman по отделам, без служебных и общих ящиков.
    """
    warnings: list[str] = []
    settings = {}
    try:
        settings = get_report_settings()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"settings: {exc}")

    is_admin = bool(settings.get("user_admin"))
    is_head = bool(settings.get("user_head"))

    try:
        departments = get_departments()
    except RuntimeError as exc:
        warnings.append(str(exc))
        return [], warnings, is_admin, is_head

    if department_id is not None:
        target_dept_ids = _child_department_ids(department_id, departments)
    else:
        target_dept_ids = {
            int(d.get("ID") or d.get("id") or 0)
            for d in departments
            if d.get("ID") or d.get("id")
        }
        target_dept_ids.discard(0)

    seen_ids: set[int] = set()
    users: list[dict] = []

    for dept_id in sorted(target_dept_ids):
        try:
            for user in get_department_users(dept_id):
                uid = int(user.get("id") or user.get("ID") or 0)
                if not uid or uid in seen_ids:
                    continue
                if not _is_real_department_employee(user):
                    continue
                seen_ids.add(uid)
                users.append(user)
        except RuntimeError as exc:
            warnings.append(f"отдел {dept_id}: {exc}")

    if not users:
        warnings.append(
            "В выбранной структуре подразделений не найдено сотрудников."
        )
    elif not is_admin and not is_head and len(users) <= 1:
        warnings.append(
            "Вебхук не от администратора/руководителя — "
            "могут быть видны не все сотрудники структуры."
        )

    return users, warnings, is_admin, is_head


def _sec_to_hhmm(seconds: int | None) -> str:
    if not seconds or seconds < 0:
        return "—"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


def load_employees_for_day(
    target_day: date | None = None,
    department_id: int | None = None,
) -> pd.DataFrame:
    """
    Отчёт за один день: кто сдал (есть рабочий день), кто нет.
    """
    target = target_day or date.today()
    users, warnings, is_admin, is_head = _collect_users(department_id)

    user_by_id: dict[int, dict] = {}
    for user in users:
        user_id = int(user.get("id") or user.get("ID") or 0)
        if user_id:
            user_by_id[user_id] = user

    reports = get_user_month_reports_batch(
        list(user_by_id.keys()),
        month=target.month,
        year=target.year,
    )

    employees = []
    errors: list[str] = []

    for user_id, user in user_by_id.items():
        name = _user_display_name(user)
        try:
            day = find_day(reports.get(user_id) or {}, target)
            has_day = bool(
                day
                and (day.get("workday_date_start") or day.get("workday_duration_final"))
            )

            if has_day:
                percent = calc_day_efficiency_percent(day)
                status = "✅ Сдал"
                if day.get("workday_complete") is False:
                    status = "🟡 Незакрыт"
                complete = bool(day.get("workday_complete"))
                start = day.get("workday_date_start") or "—"
                finish = day.get("workday_date_finish") or "—"
                duration = _sec_to_hhmm(int(day.get("workday_duration_final") or 0))
            else:
                percent = None
                status = "❌ Не сдал"
                complete = False
                start = "—"
                finish = "—"
                duration = "—"

            employees.append(
                {
                    "Сотрудник": name,
                    "Статус": status,
                    "KPI": percent if percent is not None else 0.0,
                    "Категория": kpi_category(percent),
                    "Начало": str(start)[11:16] if start not in (None, "—") else "—",
                    "Конец": str(finish)[11:16] if finish not in (None, "—") else "—",
                    "Отработано": duration,
                    "Закрыт": "Да" if complete else "Нет",
                    "ID": user_id,
                    "_has_report": has_day,
                }
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")

    df = pd.DataFrame(employees)
    if not df.empty:
        # сначала сдавшие с высоким KPI, потом несдавшие
        df["_sort"] = df["Статус"].map(
            {"✅ Сдал": 0, "🟡 Незакрыт": 1, "❌ Не сдал": 2}
        ).fillna(3)
        df = (
            df.sort_values(["_sort", "KPI"], ascending=[True, False])
            .drop(columns=["_sort"])
            .reset_index(drop=True)
        )

    submitted = int(df["_has_report"].sum()) if not df.empty else 0
    total = len(df)

    df.attrs["errors"] = errors
    df.attrs["warnings"] = warnings
    df.attrs["is_admin"] = is_admin
    df.attrs["is_head"] = is_head
    df.attrs["target_day"] = target.isoformat()
    df.attrs["submitted"] = submitted
    df.attrs["missing"] = total - submitted
    return df


def load_employees_from_bitrix(
    month: int | None = None,
    year: int | None = None,
    department_id: int | None = None,
) -> pd.DataFrame:
    """
    Загружает сотрудников и их KPI (%) из раздела отчётов Битрикс24
    (timeman / контроль времени) за месяц.
    """
    today = date.today()
    month = month or today.month
    year = year or today.year

    users, warnings, is_admin, is_head = _collect_users(department_id)

    employees = []
    errors: list[str] = []
    skipped_no_data = 0

    user_by_id: dict[int, dict] = {}
    for user in users:
        user_id = int(user.get("id") or user.get("ID") or 0)
        if user_id:
            user_by_id[user_id] = user

    reports = get_user_month_reports_batch(
        list(user_by_id.keys()),
        month=month,
        year=year,
    )

    for user_id, user in user_by_id.items():
        name = _user_display_name(user)
        try:
            report = reports.get(user_id) or {}
            percent = calc_efficiency_percent(report)
            if percent is None:
                skipped_no_data += 1
                continue

            employees.append(
                {
                    "Сотрудник": name,
                    "KPI": percent,
                    "Категория": kpi_category(percent),
                    "ID": user_id,
                }
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")

    df = pd.DataFrame(employees)
    if not df.empty:
        df = df.sort_values("KPI", ascending=False).reset_index(drop=True)

    df.attrs["errors"] = errors
    df.attrs["warnings"] = warnings
    df.attrs["skipped_no_data"] = skipped_no_data
    df.attrs["is_admin"] = is_admin
    df.attrs["is_head"] = is_head
    return df
