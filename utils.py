from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

ROSTER_PATH = Path(__file__).resolve().parent / "data" / "employees_roster.csv"


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


def load_uploaded_employees(uploaded_files, uploaded_by: str = ""):
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

            row = {
                "Сотрудник": name,
                "KPI": percent,
                "Категория": kpi_category(percent),
                "Файл": fname,
            }
            if uploaded_by:
                row["Кто загрузил"] = uploaded_by
            employees.append(row)
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


def _normalize_person_text(value: str | None) -> str:
    text = str(value or "").casefold()
    text = (
        text.replace("ё", "е")
        .replace("ʻ", "'")
        .replace("ʼ", "'")
        .replace("`", "'")
        .replace("'", "'")
        .replace("–", "-")
        .replace("—", "-")
    )
    text = re.sub(r"[^a-zа-я0-9\s\-]+", " ", text, flags=re.IGNORECASE)
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokens(value: str | None) -> set[str]:
    return {t for t in _normalize_person_text(value).split() if len(t) > 1}


def load_employees_roster(path: str | Path | None = None) -> pd.DataFrame:
    """Полный список сотрудников: ФИО + Должность."""
    source = Path(path) if path else ROSTER_PATH
    if not source.is_file():
        return pd.DataFrame(columns=["ФИО", "Должность"])

    if source.suffix.lower() in {".xlsx", ".xls"}:
        raw = pd.read_excel(source)
    else:
        raw = pd.read_csv(source)

    cols = {str(c).strip().casefold(): c for c in raw.columns}
    fio_col = cols.get("фио") or cols.get("сотрудник") or cols.get("name") or list(raw.columns)[0]
    role_col = (
        cols.get("должность")
        or cols.get("position")
        or cols.get("lavozim")
        or (list(raw.columns)[1] if len(raw.columns) > 1 else None)
    )

    rows = []
    for _, row in raw.iterrows():
        fio = str(row.get(fio_col) or "").strip()
        if not fio or fio.casefold() in {"фио", "nan", "none"}:
            continue
        role = str(row.get(role_col) or "").strip() if role_col is not None else ""
        if role.casefold() in {"должность", "nan", "none"}:
            role = ""
        rows.append({"ФИО": fio, "Должность": role})
    return pd.DataFrame(rows)


def _match_score(upload_name: str, fio: str, role: str) -> float:
    """Насколько имя из Excel (файл Normativ_…) похоже на человека из списка."""
    u = _normalize_person_text(upload_name)
    f = _normalize_person_text(fio)
    r = _normalize_person_text(role)
    if not u:
        return 0.0

    if u == f:
        return 100.0
    if r and u == r:
        return 92.0

    ut, ft, rt = _tokens(upload_name), _tokens(fio), _tokens(role)
    score = 0.0

    if ft and ut == ft:
        score = max(score, 98.0)
    if rt and ut == rt:
        score = max(score, 90.0)

    # Фамилия / первое слово ФИО
    if ft and next(iter(sorted(ft, key=len, reverse=True)[:1]) or [""]) in ut:
        # берём самое «длинное» слово ФИО (часто фамилия латиницей)
        longest = max(ft, key=len)
        if longest in ut and len(longest) >= 4:
            score = max(score, 78.0)

    if ft and ut:
        overlap_f = len(ut & ft) / max(len(ft), 1)
        if overlap_f >= 0.66:
            score = max(score, 70.0 + 25.0 * overlap_f)
        elif overlap_f >= 0.34:
            score = max(score, 55.0 + 20.0 * overlap_f)

    if rt and ut:
        overlap_r = len(ut & rt) / max(len(rt), 1)
        if r and (u in r or r in u):
            score = max(score, 85.0)
        if overlap_r >= 0.5:
            score = max(score, 65.0 + 30.0 * overlap_r)
        elif overlap_r > 0:
            score = max(score, 40.0 + 30.0 * overlap_r)

    return score


def build_roster_attendance(
    roster: pd.DataFrame,
    submitted: pd.DataFrame | None,
    min_score: float = 48.0,
) -> pd.DataFrame:
    """
    Полный список: кто сдал норматив (есть Excel), кто нет.
    Сопоставление по ФИО и должности с именем из файла отчёта.
    """
    if roster is None or roster.empty:
        return pd.DataFrame(
            columns=["ФИО", "Должность", "Статус", "KPI", "Категория", "Файл", "Сотрудник_в_отчёте"]
        )

    base = roster.copy().reset_index(drop=True)
    base["Статус"] = "❌ Не сдал"
    base["KPI"] = 0.0
    base["Категория"] = kpi_category(None)
    base["Файл"] = ""
    base["Сотрудник_в_отчёте"] = ""
    base["_matched"] = False

    if submitted is None or submitted.empty or "Сотрудник" not in submitted.columns:
        out = base.drop(columns=["_matched"])
        out.attrs["total"] = len(out)
        out.attrs["submitted"] = 0
        out.attrs["missing"] = len(out)
        out.attrs["unmatched_uploads"] = []
        return out

    uploads = []
    for _, row in submitted.iterrows():
        uploads.append(
            {
                "name": str(row.get("Сотрудник") or ""),
                "kpi": float(row.get("KPI") or 0),
                "file": str(row.get("Файл") or ""),
                "used": False,
            }
        )

    # жадно: сначала самые уверенные пары
    pairs: list[tuple[float, int, int]] = []
    for ui, up in enumerate(uploads):
        for ri, row in base.iterrows():
            sc = _match_score(up["name"], str(row["ФИО"]), str(row["Должность"]))
            if sc >= min_score:
                pairs.append((sc, ui, int(ri)))
    pairs.sort(key=lambda x: x[0], reverse=True)

    for sc, ui, ri in pairs:
        if uploads[ui]["used"] or bool(base.at[ri, "_matched"]):
            continue
        up = uploads[ui]
        base.at[ri, "_matched"] = True
        uploads[ui]["used"] = True
        kpi = up["kpi"]
        base.at[ri, "Статус"] = "✅ Сдал" if kpi > 0 else "⚫ 0%"
        base.at[ri, "KPI"] = kpi
        base.at[ri, "Категория"] = kpi_category(kpi if kpi > 0 else None)
        base.at[ri, "Файл"] = up["file"]
        base.at[ri, "Сотрудник_в_отчёте"] = up["name"]

    unmatched = [u["name"] for u in uploads if not u["used"] and u["name"]]
    out = base.drop(columns=["_matched"])
    status_order = {"✅ Сдал": 0, "⚫ 0%": 1, "❌ Не сдал": 2}
    out["_s"] = out["Статус"].map(status_order).fillna(9)
    out = out.sort_values(["_s", "Должность", "ФИО"]).drop(columns=["_s"]).reset_index(drop=True)

    submitted_n = int((out["Статус"] != "❌ Не сдал").sum())
    out.attrs["total"] = len(out)
    out.attrs["submitted"] = submitted_n
    out.attrs["missing"] = len(out) - submitted_n
    out.attrs["unmatched_uploads"] = unmatched
    return out
