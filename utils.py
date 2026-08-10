from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd


def kpi_category(percent: float | None) -> str:
    if percent is None or percent <= 0:
        return "⚫ 0 / не сдал"
    if percent >= 75:
        return "🟢 75+"
    if percent >= 50:
        return "🟡 50+"
    if percent >= 20:
        return "🟠 20+"
    return "🔴 1+"


def extract_overall_percent(excel_source) -> float | None:
    """
    Общий процент из Excel-отчёта по нормативам.
    Берём ячейку A1 (iloc[0, 0]).
    """
    try:
        df = pd.read_excel(excel_source, header=None)
        value = df.iloc[0, 0]

        if isinstance(value, str):
            value = (
                value.replace("%", "")
                     .replace(",", ".")
                     .strip()
            )

        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None

        percent = float(value)
        if percent <= 1:
            percent *= 100
        return round(percent, 2)
    except Exception:
        return None


def is_normativ_report_filename(name: str) -> bool:
    """Отчёты по нормативам: Normativ_....xlsx / .xls"""
    low = (name or "").lower().replace(" ", "")
    return "normativ" in low and (low.endswith(".xlsx") or low.endswith(".xls"))


def employee_name_from_normativ_file(name: str) -> str:
    """
    Normativ_системный_администратор_06_08. oylik.xlsx
    -> системный администратор (или исходное имя без префикса/даты)
    """
    stem = Path(name).stem
    # убрать Normativ_ / норматив_
    stem = re.sub(r"(?i)^normativ[_\-\s]*", "", stem).strip(" ._")
    # убрать хвост даты вида _06_08 / _06_08. oylik / oylik
    stem = re.sub(r"(?i)[_\-\s]*\d{1,2}[_\-.]\d{1,2}.*$", "", stem).strip(" ._")
    stem = re.sub(r"(?i)[_\-\s]*oylik.*$", "", stem).strip(" ._")
    stem = stem.replace("_", " ").strip()
    return stem or Path(name).stem


def load_uploaded_employees(uploaded_files):
    employees = []

    for file in uploaded_files:
        try:
            fname = getattr(file, "name", "unknown")
            # общий % из A1
            percent = extract_overall_percent(file)
            if percent is None:
                print(fname, "не удалось прочитать общий %")
                continue

            if is_normativ_report_filename(fname):
                name = employee_name_from_normativ_file(fname)
            else:
                name = os.path.splitext(fname)[0]

            employees.append({
                "Сотрудник": name,
                "KPI": percent,
                "Категория": kpi_category(percent),
                "Файл": fname,
            })
        except Exception as e:
            print(getattr(file, "name", file), e)

    return pd.DataFrame(employees)


def load_excel_reports_from_dir(folder: str | Path) -> pd.DataFrame:
    """
    Читает Excel-отчёты Normativ_*.
    Если таких нет — пробует любые xlsx с общим % в A1.
    """
    folder = Path(folder)
    employees = []
    skipped = []

    files = sorted(
        [*folder.glob("*.xlsx"), *folder.glob("*.xls")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    normativ_files = [p for p in files if is_normativ_report_filename(p.name)]
    candidates = normativ_files or files

    for path in candidates:
        # чужие файлы без Normativ_ в имени — только если нет ни одного Normativ
        if normativ_files and not is_normativ_report_filename(path.name):
            skipped.append(path.name)
            continue

        percent = extract_overall_percent(path)
        if percent is None:
            skipped.append(path.name)
            continue

        employees.append({
            "Сотрудник": employee_name_from_normativ_file(path.name),
            "KPI": percent,
            "Категория": kpi_category(percent),
            "Файл": path.name,
            "Путь": str(path),
        })

    df = pd.DataFrame(employees)
    if not df.empty:
        df = df.sort_values("KPI", ascending=False).reset_index(drop=True)
    df.attrs["skipped_non_reports"] = skipped
    return df
