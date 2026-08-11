from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

ROSTER_PATH = Path(__file__).resolve().parent / "data" / "employees_roster.csv"
STAFFING_PATH = Path(__file__).resolve().parent / "data" / "staffing.csv"

# Простая транслитерация для сопоставления ФИО (кириллица ↔ латиница)
_CYR_LAT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sh",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
    "қ": "q",
    "ғ": "g",
    "ҳ": "h",
    "ў": "o",
}


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
        .replace("ў", "у")
        .replace("ғ", "г")
        .replace("қ", "к")
        .replace("ҳ", "х")
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


def _to_latin_fold(value: str | None) -> str:
    text = _normalize_person_text(value)
    return "".join(_CYR_LAT.get(ch, ch) for ch in text)


def _latin_fuzzy(value: str | None) -> str:
    """Уравнивает частые варианты латиницы (zh/j, kh/h, ' апострофы)."""
    text = _to_latin_fold(value)
    text = text.replace("ʻ", "").replace("ʼ", "").replace("'", "").replace("`", "")
    repl = (
        ("shch", "sh"),
        ("ayeva", "aeva"),
        ("ayev", "aev"),
        ("yeva", "eva"),
        ("yev", "ev"),
        ("zh", "j"),
        ("kh", "h"),
        ("gh", "g"),
        ("ts", "c"),
        ("yo", "e"),
        ("yu", "u"),
        ("ya", "a"),
        ("iy", "i"),
        ("yy", "y"),
    )
    for a, b in repl:
        text = text.replace(a, b)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _latin_tokens(value: str | None) -> set[str]:
    return {t for t in _latin_fuzzy(value).split() if len(t) > 1}


def _tokens(value: str | None) -> set[str]:
    return {t for t in _normalize_person_text(value).split() if len(t) > 1}


def _token_variants(value: str | None) -> set[str]:
    raw = _tokens(value)
    lat = {t for t in _to_latin_fold(value).split() if len(t) > 1}
    fuzzy = _latin_tokens(value)
    return raw | lat | fuzzy


def load_staffing(
    path: str | Path | None = None,
    overrides: dict | None = None,
) -> pd.DataFrame:
    """Штатная расстановка: места (занято / вакансия). «юклатилган» = занято."""
    source = Path(path) if path else STAFFING_PATH
    if not source.is_file():
        return pd.DataFrame(
            columns=["№", "Код", "Должность", "Штатных_единиц", "ФИО", "Статус_места", "Пометка"]
        )
    raw = pd.read_csv(source) if source.suffix.lower() == ".csv" else pd.read_excel(source)
    if raw.empty:
        return raw
    # нормализуем имена колонок
    rename = {}
    cols = {str(c).strip().casefold(): c for c in raw.columns}
    for want, aliases in {
        "№": ("№", "no", "n", "num"),
        "Код": ("код", "code"),
        "Должность": ("должность", "position", "lavozim"),
        "Штатных_единиц": ("штатных_единиц", "units", "кол-во"),
        "ФИО": ("фио", "сотрудник", "name"),
        "Статус_места": ("статус_места", "status", "seat_status"),
        "Пометка": ("пометка", "note", "tag"),
    }.items():
        for a in aliases:
            if a in cols:
                rename[cols[a]] = want
                break
    out = raw.rename(columns=rename)
    for col in ["№", "Код", "Должность", "Штатных_единиц", "ФИО", "Статус_места", "Пометка"]:
        if col not in out.columns:
            out[col] = "" if col != "Штатных_единиц" else 1
    out["ФИО"] = out["ФИО"].fillna("").astype(str).str.strip()
    out["Должность"] = out["Должность"].fillna("").astype(str).str.strip()
    out["Пометка"] = out["Пометка"].fillna("").astype(str).str.strip()
    out["Код"] = out["Код"].fillna("").astype(str).str.strip()

    # юклатилган в ФИО или пометке — это сотрудник, не вакансия
    yuk_mask = (
        out["Пометка"].str.contains("юклатилган", case=False, na=False)
        | out["ФИО"].str.contains("юклатилган", case=False, na=False)
        | out["Пометка"].str.contains("yuklatilgan", case=False, na=False)
    )
    out.loc[yuk_mask, "Пометка"] = "юклатилган"
    # убрать хвост из ФИО, если вдруг остался
    out["ФИО"] = out["ФИО"].str.replace(
        r"\(?\s*юклатилган\s*\)?", "", regex=True, case=False
    )
    out["ФИО"] = out["ФИО"].str.replace(r"\s+", " ", regex=True).str.strip(" -()")

    status = out["Статус_места"].fillna("").astype(str)
    vacant_mask = (
        status.str.contains("вакан", case=False, na=False)
        | out["ФИО"].eq("")
        | out["ФИО"].str.casefold().isin({"nan", "none", "вакант"})
    ) & ~yuk_mask
    # если есть ФИО или юклатилган — место занято
    out.loc[vacant_mask, "Статус_места"] = "Вакансия"
    out.loc[~vacant_mask, "Статус_места"] = "Занято"
    out.loc[out["Статус_места"] == "Вакансия", "Пометка"] = ""

    # Живые кадровые правки из store (по Код), поверх CSV
    if overrides and isinstance(overrides, dict):
        out["_ov"] = False
        for code, ov in overrides.items():
            if not isinstance(ov, dict):
                continue
            code_key = str(code or "").strip()
            if not code_key:
                continue
            mask = out["Код"] == code_key
            if not mask.any():
                continue
            if "ФИО" in ov:
                out.loc[mask, "ФИО"] = str(ov.get("ФИО") or "").strip()
            if "Пометка" in ov:
                out.loc[mask, "Пометка"] = str(ov.get("Пометка") or "").strip()
            seat_st = str(ov.get("Статус_места") or "").strip()
            if seat_st in {"Занято", "Вакансия"}:
                out.loc[mask, "Статус_места"] = seat_st
            if seat_st == "Вакансия":
                out.loc[mask, "ФИО"] = ""
                out.loc[mask, "Пометка"] = ""
            out.loc[mask, "_ov"] = True
        # пересчёт статусов для строк без override
        fio = out["ФИО"].fillna("").astype(str).str.strip()
        auto_vacant = (
            ~out["_ov"]
            & (
                fio.eq("")
                | fio.str.casefold().isin({"nan", "none", "вакант"})
                | out["Статус_места"].astype(str).str.contains("вакан", case=False, na=False)
            )
            & ~out["Пометка"].astype(str).str.contains("юклатилган", case=False, na=False)
        )
        out.loc[auto_vacant, "Статус_места"] = "Вакансия"
        out.loc[~auto_vacant & ~out["_ov"] & fio.ne(""), "Статус_места"] = "Занято"
        out = out.drop(columns=["_ov"])

    out.attrs["seats_total"] = int(len(out))
    out.attrs["seats_filled"] = int((out["Статус_места"] == "Занято").sum())
    out.attrs["seats_vacant"] = int((out["Статус_места"] == "Вакансия").sum())
    out.attrs["seats_yuklatilgan"] = int((out["Пометка"] == "юклатилган").sum())
    out.attrs["staffing_overrides"] = dict(overrides or {}) if isinstance(overrides, dict) else {}
    return out


def load_employees_roster(path: str | Path | None = None) -> pd.DataFrame:
    """Уникальные сотрудники (занятые места), включая «юклатилган»."""
    source = Path(path) if path else ROSTER_PATH
    if source.is_file():
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
        note_col = cols.get("пометка") or cols.get("note") or cols.get("tag")

        rows = []
        for _, row in raw.iterrows():
            fio = str(row.get(fio_col) or "").strip()
            # юклатилган в ячейке ФИО — тоже сотрудник
            note = ""
            if re.search(r"юклатилган|yuklatilgan", fio, flags=re.I):
                note = "юклатилган"
                fio = re.sub(r"\(?\s*юклатилган\s*\)?", "", fio, flags=re.I)
                fio = re.sub(r"\s+", " ", fio).strip(" -()")
            if note_col is not None:
                n2 = str(row.get(note_col) or "").strip()
                if re.search(r"юклатилган|yuklatilgan", n2, flags=re.I):
                    note = "юклатилган"
            if not fio or fio.casefold() in {"фио", "nan", "none", "вакант"}:
                continue
            role = str(row.get(role_col) or "").strip() if role_col is not None else ""
            if role.casefold() in {"должность", "nan", "none"}:
                role = ""
            rows.append({"ФИО": fio, "Должность": role, "Пометка": note})
        if rows:
            return pd.DataFrame(rows)

    # fallback: уникальные ФИО из staffing.csv
    staff = load_staffing()
    if staff.empty:
        return pd.DataFrame(columns=["ФИО", "Должность", "Пометка"])
    filled = staff[staff["Статус_места"] == "Занято"].copy()
    rows = []
    seen: set[str] = set()
    for _, row in filled.iterrows():
        fio = str(row.get("ФИО") or "").strip()
        key = _normalize_person_text(fio)
        if not fio or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "ФИО": fio,
                "Должность": str(row.get("Должность") or "").strip(),
                "Пометка": str(row.get("Пометка") or "").strip(),
            }
        )
    return pd.DataFrame(rows)


def _match_score(upload_name: str, fio: str, role: str) -> float:
    """Насколько имя из Excel (файл Normativ_…) похоже на человека из списка."""
    # Латиница (Normativ) ↔ кириллица (штатка)
    role_aliases = {
        "ofis menejeri": "офис менеджер",
        "ofis menejer": "офис менеджер",
        "ofis administrator": "офис менеджер",
        "ofis admin": "офис менеджер",
        "office administrator": "офис менеджер",
        "office manager": "офис менеджер",
        "office admin": "офис менеджер",
        "haydovchi": "водитель",
        "xavfsizlik xodimi": "сотрудник охраны",
        "elektronshik muhandis": "инженер электронщик",
        "elektr muhandisi": "инженер электрик",
        "mexanik muhandis": "инженер механик",
        "ombor mudiri": "заведующий складом",
        "sistemnyy administrator": "системный администратор",
        "system administrator": "системный администратор",
        "xarid menejer": "менеджер по закупу",
        "logistika menejeri": "менеджер по логистике",
        "hr menejer": "hr менеджер",
        "moliya direktori": "директор по финансам",
        "boshqaruvchi direktor": "управляющий директор",
    }

    def role_fold(value: str | None) -> str:
        key_lat = _to_latin_fold(value)
        key = _normalize_person_text(value)
        # точное совпадение алиаса важнее substring
        for src, dst in role_aliases.items():
            if key_lat == src or key == src:
                return _normalize_person_text(dst)
        for src, dst in role_aliases.items():
            if len(src) >= 8 and src in key_lat:
                return _normalize_person_text(dst)
        key = re.sub(r"\b(ceo|ceoo|cmo|chro|cpro|agm)\b", " ", key)
        return re.sub(r"\s+", " ", key).strip()

    u = _normalize_person_text(upload_name)
    f = _normalize_person_text(fio)
    r = _normalize_person_text(role)
    u_lat, f_lat, r_lat = _to_latin_fold(upload_name), _to_latin_fold(fio), _to_latin_fold(role)
    u_fuzzy, f_fuzzy = _latin_fuzzy(upload_name), _latin_fuzzy(fio)
    u_role, r_role = role_fold(upload_name), role_fold(role)
    if not u:
        return 0.0

    score = 0.0
    if u == f or u_lat == f_lat or u_fuzzy == f_fuzzy:
        return 100.0
    if r and (u == r or u_lat == r_lat):
        return 92.0
    if u_role and r_role and u_role == r_role:
        return 95.0

    # Имя / фамилия: латиница ↔ кириллица
    u_name_toks = _latin_tokens(upload_name)
    f_name_toks = _latin_tokens(fio)
    u_parts = [t for t in u_fuzzy.split() if len(t) > 1]
    f_parts = [t for t in f_fuzzy.split() if len(t) > 1]
    if u_parts and f_parts:
        if u_parts[0] == f_parts[0] and len(u_parts[0]) >= 4:
            score = max(score, 88.0 if len(u_parts) == 1 else 96.0)
        if len(u_parts) == 1 and u_parts[0] in f_name_toks and len(u_parts[0]) >= 4:
            score = max(score, 80.0)
        if u_name_toks and u_name_toks <= f_name_toks:
            score = max(score, 94.0 if len(u_name_toks) >= 2 else 80.0)
        elif u_name_toks and f_name_toks:
            overlap_n = len(u_name_toks & f_name_toks) / max(len(u_name_toks), 1)
            if overlap_n >= 0.5:
                score = max(score, 70.0 + 28.0 * overlap_n)

    # ofis + administrator ↔ офис-менеджер / офис администратор
    if {"ofis", "office"} & set(u_lat.split()) and "administr" in u_lat.replace(" ", ""):
        if "офис" in r and ("менеджер" in r or "администратор" in r or "админ" in r):
            score = max(score, 93.0)
        if "ofis" in r_lat and ("menejer" in r_lat or "administr" in r_lat):
            score = max(score, 93.0)

    ut = _token_variants(upload_name)
    ft = _token_variants(fio)
    # важно: НЕ добавлять токены upload в rt — иначе матч 88 ко всем подряд
    rt = _token_variants(role) | _tokens(r_role)

    if ft and ut == ft:
        score = max(score, 98.0)
    if rt and ut and len(ut) >= 2 and ut <= rt:
        score = max(score, 88.0)
    if rt and ut == rt:
        score = max(score, 90.0)

    if ft:
        longest = max(ft, key=len)
        if longest in ut and len(longest) >= 4:
            score = max(score, 78.0)

    if u_name_toks and f_name_toks:
        overlap_f = len(u_name_toks & f_name_toks) / max(len(f_name_toks), 1)
        if overlap_f >= 0.66:
            score = max(score, 70.0 + 25.0 * overlap_f)
        elif overlap_f >= 0.34:
            score = max(score, 55.0 + 20.0 * overlap_f)
    elif ft and ut:
        overlap_f = len(ut & ft) / max(len(ft), 1)
        if overlap_f >= 0.66:
            score = max(score, 70.0 + 25.0 * overlap_f)
        elif overlap_f >= 0.34:
            score = max(score, 55.0 + 20.0 * overlap_f)

    if rt and ut:
        overlap_r = len(ut & rt) / max(len(rt), 1)
        if r and (u in r or r in u or u_lat in r_lat or r_lat in u_lat):
            score = max(score, 85.0)
        if u_role and r_role and (u_role in r_role or r_role in u_role):
            score = max(score, 86.0)
        if overlap_r >= 0.5:
            score = max(score, 65.0 + 30.0 * overlap_r)
        elif overlap_r > 0:
            score = max(score, 45.0 + 35.0 * overlap_r)

    u_core = {t for t in ut if len(t) >= 4}
    r_core = {t for t in (_tokens(r_role) | _token_variants(role)) if len(t) >= 4}
    if u_core and r_core and (u_core & r_core):
        score = max(score, 70.0 + 20.0 * (len(u_core & r_core) / max(len(r_core), 1)))

    return score


def build_roster_attendance(
    roster: pd.DataFrame,
    submitted: pd.DataFrame | None,
    min_score: float = 42.0,
) -> pd.DataFrame:
    """
    Полный список: кто сдал норматив (есть Excel), кто нет.
    Сопоставление по ФИО и должности с именем из файла отчёта.
    """
    if roster is None or roster.empty:
        return pd.DataFrame(
            columns=[
                "ФИО",
                "Должность",
                "Пометка",
                "Статус",
                "KPI",
                "Категория",
                "Файл",
                "Сотрудник_в_отчёте",
            ]
        )

    base = roster.copy().reset_index(drop=True)
    if "Пометка" not in base.columns:
        base["Пометка"] = ""
    base["Пометка"] = base["Пометка"].fillna("").astype(str)
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
        out.attrs["yuklatilgan"] = int((out["Пометка"] == "юклатилган").sum())
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
    out.attrs["yuklatilgan"] = int((out["Пометка"] == "юклатилган").sum())
    out.attrs["unmatched_uploads"] = unmatched
    return out


def is_report_exempt_role(role: str | None) -> bool:
    """
    Директора не сдают норматив, но остаются в списке штата.
    Ассистент директора — сдаёт (не исключение).
    """
    text = _normalize_person_text(role)
    if not text:
        return False
    if "ассистент" in text:
        return False
    # генеральный / исполнительный / управляющий / финансовый / … директор, CEO/CFO/…
    if "директор" in text:
        return True
    if any(x in text for x in (" ceo", "ceo ", " cfoo", " cfo", " cmo", " cmso", " coo", " chro")):
        return True
    # без пробелов в нормализации — проверить токены
    tokens = set(text.split())
    if tokens & {"ceo", "ceoo", "cfo", "cmo", "cmso", "coo", "chro"}:
        return True
    return False


def build_filled_staffing_with_reports(
    staffing: pd.DataFrame,
    attendance: pd.DataFrame | None,
    submitted: pd.DataFrame | None = None,
    min_score: float = 42.0,
    seat_overrides: dict | None = None,
) -> pd.DataFrame:
    """Занятые места штатки + статус сдачи. Директора в списке, но вне графиков."""
    if staffing is None or staffing.empty:
        return pd.DataFrame(
            columns=[
                "№",
                "Код",
                "Должность",
                "ФИО",
                "Пометка",
                "Статус",
                "KPI",
                "Категория",
                "Файл",
            ]
        )

    filled = staffing[staffing["Статус_места"] == "Занято"].copy().reset_index(drop=True)
    if "Пометка" not in filled.columns:
        filled["Пометка"] = ""
    filled["Статус"] = "❌ Не сдал"
    filled["KPI"] = 0.0
    filled["Категория"] = kpi_category(None)
    filled["Файл"] = ""
    filled["_matched"] = False
    filled["_exempt"] = filled["Должность"].map(is_report_exempt_role)
    filled.loc[filled["_exempt"], "Статус"] = "➖ Не обязан"
    filled.loc[filled["_exempt"], "Категория"] = "➖ Не обязан"
    filled.loc[filled["_exempt"], "_matched"] = True

    uploads = []
    if submitted is not None and not submitted.empty and "Сотрудник" in submitted.columns:
        for _, row in submitted.iterrows():
            uploads.append(
                {
                    "name": str(row.get("Сотрудник") or ""),
                    "kpi": float(row.get("KPI") or 0),
                    "file": str(row.get("Файл") or ""),
                    "used": False,
                }
            )

    pairs: list[tuple[float, int, int]] = []
    for ui, up in enumerate(uploads):
        for ri, row in filled.iterrows():
            if bool(filled.at[ri, "_exempt"]):
                continue
            sc = _match_score(up["name"], str(row.get("ФИО") or ""), str(row.get("Должность") or ""))
            if sc >= min_score:
                pairs.append((sc, ui, int(ri)))
    pairs.sort(key=lambda x: x[0], reverse=True)

    for sc, ui, ri in pairs:
        if uploads[ui]["used"] or bool(filled.at[ri, "_matched"]):
            continue
        up = uploads[ui]
        uploads[ui]["used"] = True
        filled.at[ri, "_matched"] = True
        kpi = up["kpi"]
        filled.at[ri, "Статус"] = "✅ Сдал" if kpi > 0 else "⚫ 0%"
        filled.at[ri, "KPI"] = kpi
        filled.at[ri, "Категория"] = kpi_category(kpi if kpi > 0 else None)
        filled.at[ri, "Файл"] = up["file"]

    if attendance is not None and not attendance.empty:
        for _, row in attendance.iterrows():
            if str(row.get("Статус") or "") == "❌ Не сдал":
                continue
            fio_key = _normalize_person_text(str(row.get("ФИО") or ""))
            lat = _to_latin_fold(str(row.get("ФИО") or ""))
            role = str(row.get("Должность") or "")
            payload_status = row.get("Статус") or "✅ Сдал"
            payload_kpi = float(row.get("KPI") or 0)
            payload_cat = row.get("Категория") or kpi_category(
                payload_kpi if payload_kpi > 0 else None
            )
            payload_file = row.get("Файл") or ""
            best_ri, best_sc = None, -1.0
            for ri, seat in filled.iterrows():
                if bool(filled.at[ri, "_matched"]) or bool(filled.at[ri, "_exempt"]):
                    continue
                seat_key = _normalize_person_text(str(seat.get("ФИО") or ""))
                seat_lat = _to_latin_fold(str(seat.get("ФИО") or ""))
                sc = 0.0
                if fio_key and seat_key == fio_key:
                    sc = 100.0
                elif lat and seat_lat == lat:
                    sc = 95.0
                else:
                    continue
                sc += min(
                    20.0,
                    _match_score(role, str(seat.get("ФИО") or ""), str(seat.get("Должность") or ""))
                    * 0.1,
                )
                if sc > best_sc:
                    best_sc, best_ri = sc, int(ri)
            if best_ri is not None:
                filled.at[best_ri, "_matched"] = True
                filled.at[best_ri, "Статус"] = payload_status
                filled.at[best_ri, "KPI"] = payload_kpi
                filled.at[best_ri, "Категория"] = payload_cat
                filled.at[best_ri, "Файл"] = payload_file

    # Ручные статусы админа по Код — поверх матчинга (кроме «Не обязан»)
    if seat_overrides and isinstance(seat_overrides, dict) and "Код" in filled.columns:
        for ri, row in filled.iterrows():
            if bool(filled.at[ri, "_exempt"]):
                continue
            code_key = str(row.get("Код") or "").strip()
            ov = seat_overrides.get(code_key)
            if not isinstance(ov, dict):
                continue
            status = str(ov.get("Статус") or "").strip()
            if status not in {"✅ Сдал", "⚫ 0%", "❌ Не сдал"}:
                continue
            filled.at[ri, "Статус"] = status
            try:
                kpi_ov = float(ov.get("KPI") or 0)
            except Exception:
                kpi_ov = 0.0
            if status == "❌ Не сдал":
                filled.at[ri, "KPI"] = 0.0
                filled.at[ri, "Категория"] = kpi_category(None)
                filled.at[ri, "Файл"] = ""
            elif status == "⚫ 0%":
                filled.at[ri, "KPI"] = 0.0
                filled.at[ri, "Категория"] = kpi_category(0.0)
                if ov.get("Файл"):
                    filled.at[ri, "Файл"] = str(ov.get("Файл") or "")
            else:
                filled.at[ri, "KPI"] = kpi_ov
                filled.at[ri, "Категория"] = ov.get("Категория") or kpi_category(
                    kpi_ov if kpi_ov > 0 else None
                )
                if ov.get("Файл"):
                    filled.at[ri, "Файл"] = str(ov.get("Файл") or "")
            filled.at[ri, "_matched"] = True

    filled = filled.drop(columns=["_matched", "_exempt"])
    order = {"✅ Сдал": 0, "⚫ 0%": 1, "❌ Не сдал": 2, "➖ Не обязан": 3}
    filled["_s"] = filled["Статус"].map(order).fillna(9)
    filled = filled.sort_values(["_s", "№"]).drop(columns=["_s"]).reset_index(drop=True)

    required = filled[filled["Статус"] != "➖ Не обязан"]
    submitted_seats = int((required["Статус"] != "❌ Не сдал").sum())
    total_required = int(len(required))

    filled.attrs["total"] = total_required
    filled.attrs["submitted"] = submitted_seats
    filled.attrs["missing"] = total_required - submitted_seats
    filled.attrs["people_total"] = total_required
    filled.attrs["exempt"] = int((filled["Статус"] == "➖ Не обязан").sum())
    filled.attrs["seats_filled_all"] = int(len(filled))
    unmatched = [u["name"] for u in uploads if not u["used"] and u["name"]]
    filled.attrs["unmatched_uploads"] = unmatched
    filled.attrs["seat_overrides"] = dict(seat_overrides or {}) if isinstance(seat_overrides, dict) else {}
    return filled
