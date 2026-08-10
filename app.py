from datetime import date, datetime
from pathlib import Path
import os

import pandas as pd
import streamlit as st
import plotly.express as px

from utils import (
    load_uploaded_employees,
    load_employees_roster,
    load_staffing,
    build_roster_attendance,
    build_filled_staffing_with_reports,
)

ROOT = Path(__file__).resolve().parent
LOGO_PATH = ROOT / "assets" / "akela-logo.png"
FAVICON_PATH = ROOT / "assets" / "akela-favicon.png"


def _is_streamlit_cloud() -> bool:
    return bool(
        os.getenv("STREAMLIT_RUNTIME_ENVIRONMENT") == "cloud"
        or os.getenv("IS_STREAMLIT_CLOUD")
        or Path("/mount/src").exists()
    )


def _bitrix_browser_ready() -> tuple[bool, str]:
    """Локально: Selenium + логин в .env. На Cloud — недоступно."""
    if _is_streamlit_cloud():
        return False, "На streamlit.app автозагрузка из Битрикс недоступна — загрузите Excel вручную."
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env", override=True)
    except Exception:
        pass
    login = os.getenv("BITRIX_LOGIN", "").strip()
    password = os.getenv("BITRIX_PASSWORD", "").strip()
    if not login or not password:
        return False, "В .env нужны BITRIX_LOGIN и BITRIX_PASSWORD."
    try:
        import selenium  # noqa: F401
        import webdriver_manager  # noqa: F401
    except ImportError:
        return False, "Установите локально: pip install -r requirements-local.txt"
    return True, ""

st.set_page_config(
    page_title="Akela · Отчёты по нормативам",
    page_icon=str(FAVICON_PATH if FAVICON_PATH.exists() else LOGO_PATH),
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Design system — steel + blue (industrial mist)
# ---------------------------------------------------------------------------

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Unbounded:wght@500;700&family=Onest:wght@400;500;600;700&display=swap');

:root {
  --ink: #1A2332;
  --ink-soft: #4A5568;
  --mist-0: #F4F7FA;
  --mist-1: #E8EEF4;
  --mist-2: #D5E0EA;
  --steel: #7A8B9C;
  --teal: #3E4197;
  --teal-deep: #2A2D7A;
  --teal-glow: rgba(62, 65, 151, 0.14);
  --line: rgba(26, 35, 50, 0.10);
  --ok: #1F7A4C;
  --warn: #B7791F;
  --bad: #C53030;
}

html, body, [class*="css"] {
  font-family: "Onest", sans-serif !important;
  color: var(--ink);
}

.stApp {
  background:
    radial-gradient(1000px 520px at 8% -10%, rgba(62, 65, 151, 0.16), transparent 55%),
    radial-gradient(900px 480px at 100% 0%, rgba(122, 139, 156, 0.22), transparent 50%),
    linear-gradient(165deg, var(--mist-0) 0%, var(--mist-1) 48%, var(--mist-2) 100%) !important;
}

[data-testid="stHeader"] {
  background: transparent !important;
}

#MainMenu, footer { visibility: hidden; }

.block-container {
  padding-top: 1.4rem !important;
  padding-bottom: 3rem !important;
  max-width: 1180px !important;
}

/* —— Brand hero —— */
.akela-hero {
  position: relative;
  padding: 0.2rem 0 1.4rem;
  margin-bottom: 0.4rem;
  animation: rise 0.7s ease-out both;
}

.akela-logo-wrap {
  max-width: 220px;
  margin: 0 0 0.85rem;
}

.akela-logo-wrap img {
  width: 100%;
  height: auto;
  display: block;
}

.akela-subtitle {
  margin: 0;
  font-family: "Unbounded", sans-serif;
  font-weight: 500;
  font-size: clamp(1.05rem, 2.2vw, 1.35rem);
  letter-spacing: 0.02em;
  line-height: 1.25;
  color: var(--teal);
}

.akela-rule {
  height: 3px;
  width: 72px;
  margin-top: 1.1rem;
  background: linear-gradient(90deg, var(--teal), transparent);
  border-radius: 2px;
  animation: grow 0.9s 0.2s ease-out both;
}

@keyframes rise {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes grow {
  from { width: 0; opacity: 0; }
  to { width: 72px; opacity: 1; }
}
@keyframes fadeup {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* —— Section —— */
.akela-section-label {
  font-family: "Unbounded", sans-serif;
  font-size: 0.72rem;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--teal);
  margin: 0 0 0.35rem;
}

/* —— Metrics —— */
div[data-testid="stMetric"] {
  background: rgba(244, 247, 250, 0.72);
  border: 1px solid var(--line);
  border-radius: 2px;
  padding: 1rem 1.1rem 0.85rem;
  backdrop-filter: blur(8px);
  animation: fadeup 0.55s ease-out both;
}

div[data-testid="stMetric"]:nth-of-type(1) { animation-delay: 0.05s; }
div[data-testid="stMetric"]:nth-of-type(2) { animation-delay: 0.12s; }
div[data-testid="stMetric"]:nth-of-type(3) { animation-delay: 0.18s; }
div[data-testid="stMetric"]:nth-of-type(4) { animation-delay: 0.24s; }

div[data-testid="stMetric"] label {
  font-family: "Onest", sans-serif !important;
  font-size: 0.78rem !important;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--steel) !important;
}

div[data-testid="stMetric"] [data-testid="stMetricValue"] {
  font-family: "Unbounded", sans-serif !important;
  font-weight: 700 !important;
  font-size: 1.85rem !important;
  color: var(--ink) !important;
}

/* —— Controls —— */
.stRadio > label, .stSelectbox label, .stTextInput label, .stFileUploader label,
.stDateInput label {
  font-family: "Onest", sans-serif !important;
  font-weight: 600 !important;
  color: var(--ink) !important;
}

div[role="radiogroup"] label {
  background: rgba(244, 247, 250, 0.8);
  border: 1px solid var(--line);
  padding: 0.35rem 0.85rem;
  border-radius: 2px;
  transition: border-color 0.2s, background 0.2s;
}

div[role="radiogroup"] label:hover {
  border-color: var(--teal);
  background: var(--teal-glow);
}

.stButton > button {
  font-family: "Onest", sans-serif !important;
  font-weight: 600 !important;
  border-radius: 2px !important;
  border: none !important;
  background: linear-gradient(135deg, var(--teal) 0%, var(--teal-deep) 100%) !important;
  color: #fff !important;
  padding: 0.55rem 1.25rem !important;
  letter-spacing: 0.02em;
  transition: transform 0.15s ease, box-shadow 0.2s ease !important;
  box-shadow: 0 8px 20px rgba(62, 65, 151, 0.22);
}

.stButton > button:hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 28px rgba(62, 65, 151, 0.3) !important;
}

hr {
  border: none !important;
  border-top: 1px solid var(--line) !important;
  margin: 1.4rem 0 !important;
}

/* —— Dataframe —— */
div[data-testid="stDataFrame"] {
  border: 1px solid var(--line);
  border-radius: 2px;
  overflow: hidden;
  background: rgba(244, 247, 250, 0.65);
  animation: fadeup 0.6s 0.15s ease-out both;
}

/* —— Plotly wrap —— */
div[data-testid="stPlotlyChart"] {
  background: rgba(244, 247, 250, 0.55);
  border: 1px solid var(--line);
  border-radius: 2px;
  padding: 0.4rem;
  animation: fadeup 0.6s 0.1s ease-out both;
}

.stAlert {
  border-radius: 2px !important;
  border-left-width: 3px !important;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown('<div class="akela-hero">', unsafe_allow_html=True)
if LOGO_PATH.exists():
    st.image(str(LOGO_PATH), width=240)
st.markdown(
    """
  <p class="akela-subtitle">отчёты по нормативам</p>
  <div class="akela-rule"></div>
</div>
""",
    unsafe_allow_html=True,
)

# Plotly theme
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Onest, sans-serif", color="#1A2332", size=13),
    margin=dict(l=24, r=16, t=48, b=24),
    title=dict(font=dict(family="Unbounded, sans-serif", size=14, color="#3E4197")),
    colorway=["#3E4197", "#1F7A4C", "#B7791F", "#C53030", "#7A8B9C", "#1A2332"],
)

st.markdown('<p class="akela-section-label">Загрузка Excel</p>', unsafe_allow_html=True)

from schedule import active_window_day, now_tashkent, can_upload_for_day
from shared_store import load_day, publish_day_snapshot

# Битрикс24-режим сохранён в git — временно только Excel + Google Drive.

now = now_tashkent()
current_slot = active_window_day(now)
upload_ok, upload_reason = can_upload_for_day(current_slot, now)

# Сначала рисуем заголовок загрузки, Google проверяем мягко
if upload_ok:
    st.caption(
        f"Загрузите Excel за {current_slot.strftime('%d.%m.%Y')} — "
        "диаграммы увидит любой по этой ссылке. После 20:00 (Ташкент) за сегодня добавить нельзя."
    )
else:
    st.warning(upload_reason)

shared_error = None
available_days: list = []
try:
    _, boot_meta = load_day(current_slot)
    available_days = [date.fromisoformat(x) for x in boot_meta.get("available_days") or []]
except Exception as exc:
    shared_error = str(exc)

if shared_error:
    st.warning(
        "Google Drive пока недоступен. Проверьте: папка расшарена "
        "Редактором на `akela-streamlit@...`, Secrets (`GOOGLE_DRIVE_FOLDER_ID` "
        "и ключ), файл `shared_kpi.json` в этой папке.\n\n"
        f"`{shared_error}`"
    )

if upload_ok:
    uploaded_files = st.file_uploader(
        "Excel-отчёты",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
else:
    uploaded_files = None
    st.info("Загрузка за этот день закрыта. Можно смотреть уже сохранённые отчёты ниже.")

if uploaded_files and st.button("Показать всем", type="primary"):
    ok_now, reason_now = can_upload_for_day(current_slot)
    if not ok_now:
        st.error(reason_now)
        st.stop()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    local_dir = ROOT / "downloads" / "uploads" / stamp
    local_dir.mkdir(parents=True, exist_ok=True)
    for f in uploaded_files:
        (local_dir / f.name).write_bytes(f.getvalue())
        try:
            f.seek(0)
        except Exception:
            pass

    incoming = load_uploaded_employees(uploaded_files)
    if incoming is None or incoming.empty:
        st.error("Не удалось прочитать % из A1.")
        st.stop()

    try:
        with st.spinner("Сохраняю для всех…"):
            df_pub, meta = publish_day_snapshot(
                incoming,
                window_day=current_slot,
                replace=False,
                allow_outside_window=True,
            )
        st.success(
            f"Готово. По этой ссылке все увидят данные "
            f"({meta.get('count', len(df_pub))} записей)."
        )
        st.rerun()
    except Exception as exc:
        st.error(
            "Не удалось сохранить. "
            f"`{exc}`"
        )
        st.stop()

day_options = sorted({current_slot, *available_days}, reverse=True) or [current_slot]
selected_day = st.selectbox(
    "Какой день смотреть",
    day_options,
    format_func=lambda d: d.strftime("%d.%m.%Y") + (" · текущий" if d == current_slot else " · архив"),
)

try:
    df, shared_meta = load_day(selected_day)
except Exception as exc:
    if shared_error:
        st.info("Пока нет общих данных. Загрузите Excel выше.")
        st.stop()
    st.error(f"Не удалось загрузить день: `{exc}`")
    st.stop()

if df is None:
    df = pd.DataFrame()

staffing = load_staffing()
roster = load_employees_roster()
attendance = build_roster_attendance(roster, df if not df.empty else None)
filled_staff = build_filled_staffing_with_reports(
    staffing, attendance, submitted=df if not df.empty else None
)
vacancies = (
    staffing[staffing["Статус_места"] == "Вакансия"].copy()
    if not staffing.empty
    else pd.DataFrame()
)

bits = [f"День: {selected_day.strftime('%d.%m.%Y')}"]
if shared_meta.get("updated_at"):
    bits.append(f"Обновлено: {shared_meta['updated_at']}")
if not staffing.empty:
    bits.append(
        f"Штат: {staffing.attrs.get('seats_filled', 0)}/"
        f"{staffing.attrs.get('seats_total', len(staffing))} занято"
    )
elif not roster.empty:
    bits.append(f"В списке: {attendance.attrs.get('total', len(attendance))}")
st.caption(" · ".join(bits))

# =========================
# Штат (без вакансий) + сдача
# =========================
if not filled_staff.empty or not vacancies.empty or not roster.empty:
    seats_total = int(staffing.attrs.get("seats_total") or len(staffing) or 0)
    seats_filled = int(staffing.attrs.get("seats_filled") or len(filled_staff) or 0)
    seats_vacant = int(staffing.attrs.get("seats_vacant") or len(vacancies) or 0)
    seats_yuk = int(staffing.attrs.get("seats_yuklatilgan") or 0)
    sub_n = int(filled_staff.attrs.get("submitted") or 0) if not filled_staff.empty else 0
    miss_n = int(filled_staff.attrs.get("missing") or 0) if not filled_staff.empty else 0
    people_rate = (
        (100.0 * sub_n / int(filled_staff.attrs.get("people_total") or sub_n or 1))
        if (not filled_staff.empty and int(filled_staff.attrs.get("people_total") or 0))
        else 0.0
    )

    st.markdown('<p class="akela-section-label">Штат</p>', unsafe_allow_html=True)
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Рабочих мест", seats_total or "—")
    s2.metric("В списке (занято)", seats_filled)
    s3.metric("Сдали отчёт", sub_n)
    s4.metric("Не сдали", miss_n)
    people_total = int(filled_staff.attrs.get("people_total") or 0) if not filled_staff.empty else 0
    st.caption(
        f"Сдали {people_rate:.0f}% от сотрудников"
        + (f" ({people_total} чел.)" if people_total else "")
        + (f" · вакансий отдельно: {seats_vacant}" if seats_vacant else "")
        + (f" · юклатилган: {seats_yuk}" if seats_yuk else "")
    )

    status_filter = st.radio(
        "Фильтр штата",
        ["Все занятые", "✅ Сдали", "❌ Не сдали"],
        horizontal=True,
        label_visibility="collapsed",
    )
    search_staff = st.text_input(
        "Поиск по штату",
        placeholder="ФИО, должность или код…",
        key="staff_search",
    )

    staff_view = filled_staff.copy()
    if status_filter == "✅ Сдали":
        staff_view = staff_view[staff_view["Статус"] != "❌ Не сдал"]
    elif status_filter == "❌ Не сдали":
        staff_view = staff_view[staff_view["Статус"] == "❌ Не сдал"]
    if search_staff:
        q = search_staff.strip()
        staff_view = staff_view[
            staff_view["ФИО"].astype(str).str.contains(q, case=False, na=False)
            | staff_view["Должность"].astype(str).str.contains(q, case=False, na=False)
            | staff_view["Код"].astype(str).str.contains(q, case=False, na=False)
        ]

    show_staff = [
        c
        for c in ["№", "Код", "Должность", "ФИО", "Пометка", "Статус", "KPI", "Категория", "Файл"]
        if c in staff_view.columns
    ]
    st.dataframe(staff_view[show_staff], use_container_width=True, hide_index=True)

    unmatched = list(filled_staff.attrs.get("unmatched_uploads") or []) or list(
        attendance.attrs.get("unmatched_uploads") or []
    )
    if unmatched:
        st.caption(
            "Отчёты вне списка (не сопоставлены с ФИО/должностью): "
            + ", ".join(unmatched[:12])
            + ("…" if len(unmatched) > 12 else "")
        )

    # =========================
    # Вакансии — отдельный раздел
    # =========================
    st.markdown('<p class="akela-section-label">Вакансии</p>', unsafe_allow_html=True)
    if vacancies.empty:
        st.caption("Вакансий нет.")
    else:
        st.caption(f"Открытых вакансий: {len(vacancies)}")
        search_vac = st.text_input(
            "Поиск по вакансиям",
            placeholder="Должность или код…",
            key="vacancy_search",
        )
        vac_view = vacancies.copy()
        if search_vac:
            q = search_vac.strip()
            vac_view = vac_view[
                vac_view["Должность"].astype(str).str.contains(q, case=False, na=False)
                | vac_view["Код"].astype(str).str.contains(q, case=False, na=False)
            ]
        show_vac = [c for c in ["№", "Код", "Должность"] if c in vac_view.columns]
        st.dataframe(vac_view[show_vac], use_container_width=True, hide_index=True)

    st.divider()

# =========================
# Metrics (по загруженным Excel)
# =========================
st.markdown('<p class="akela-section-label">Сводка по загруженным %</p>', unsafe_allow_html=True)

if df.empty or "KPI" not in getattr(df, "columns", []):
    st.info("Пока нет загруженных Excel за этот день — в таблице выше все со статусом «Не сдал».")
    st.stop()

with_kpi = df[df["KPI"] > 0] if "KPI" in df.columns else df

c1, c2, c3, c4 = st.columns(4)
c1.metric("Записей Excel", len(df))
c2.metric("Средний %", f"{df['KPI'].mean():.1f}%")
c3.metric("Максимум", f"{df['KPI'].max():.1f}%")
c4.metric("Минимум", f"{df['KPI'].min():.1f}%")

st.divider()

# =========================
# Charts
# =========================
st.markdown('<p class="akela-section-label">Диаграммы</p>', unsafe_allow_html=True)

col1, col2 = st.columns(2)

cat_order = ["🟢 75+", "🟡 50+", "🟠 20+", "🔴 1+", "⚫ 0 / не сдал"]
cat_colors = {
    "🟢 75+": "#22A06B",
    "🟡 50+": "#E2B203",
    "🟠 20+": "#E06C00",
    "🔴 1+": "#E34935",
    "⚫ 0 / не сдал": "#1A1A1A",
}

with col1:
    stats = df["Категория"].value_counts().reindex(cat_order).dropna().reset_index()
    stats.columns = ["Категория", "Количество"]
    pie = px.pie(
        stats,
        names="Категория",
        values="Количество",
        hole=0.58,
        title="По категориям",
        color="Категория",
        color_discrete_map=cat_colors,
    )
    pie.update_traces(textposition="inside", textinfo="percent+label", textfont_size=12)
    pie.update_layout(**PLOTLY_LAYOUT, showlegend=False)
    st.plotly_chart(pie, use_container_width=True)

with col2:
    stats = (
        with_kpi["Категория"].value_counts().reindex(cat_order).dropna().reset_index()
        if not with_kpi.empty
        else df["Категория"].value_counts().reindex(cat_order).dropna().reset_index()
    )
    stats.columns = ["Категория", "Количество"]
    bar = px.bar(
        stats,
        x="Категория",
        y="Количество",
        text_auto=True,
        title="Распределение",
        color="Категория",
        color_discrete_map=cat_colors,
        category_orders={"Категория": cat_order},
    )
    bar.update_layout(**PLOTLY_LAYOUT, showlegend=False)
    bar.update_xaxes(showgrid=False, title="")
    bar.update_yaxes(showgrid=True, gridcolor="rgba(26,35,50,0.08)", title="")
    st.plotly_chart(bar, use_container_width=True)

sort_cols = st.columns([2.2, 1.2])
with sort_cols[0]:
    st.markdown(
        '<p style="font-family:Unbounded,sans-serif;font-size:0.95rem;'
        'color:#3E4197;margin:0.85rem 0 0.35rem;">Сотрудники по % норматива</p>',
        unsafe_allow_html=True,
    )
with sort_cols[1]:
    sort_mode = st.selectbox(
        "Сортировка",
        [
            "По алфавиту",
            "По процентам: с высокого",
            "По процентам: с низкого",
        ],
        label_visibility="collapsed",
    )

ordered = df.copy()
ordered["_sort_name"] = ordered["Сотрудник"].astype(str).str.strip().str.casefold()

if sort_mode == "По алфавиту":
    # А → Б → В … сверху вниз
    ordered = ordered.sort_values(["_sort_name", "Сотрудник"], ascending=[True, True])
elif sort_mode == "По процентам: с высокого":
    ordered = ordered.sort_values(["KPI", "_sort_name"], ascending=[False, True])
else:
    ordered = ordered.sort_values(["KPI", "_sort_name"], ascending=[True, True])

ordered = ordered.drop(columns=["_sort_name"])
names_top_to_bottom = ordered["Сотрудник"].tolist()
# Plotly: categoryarray идёт снизу вверх → разворачиваем
names_bottom_to_top = list(reversed(names_top_to_bottom))

people = px.bar(
    ordered,
    x="KPI",
    y="Сотрудник",
    orientation="h",
    text="KPI",
    color="Категория",
    color_discrete_map=cat_colors,
    category_orders={"Категория": cat_order},
)
people.update_traces(texttemplate="%{x:.1f}%", textposition="outside", cliponaxis=False)
layout = {k: v for k, v in PLOTLY_LAYOUT.items() if k != "title"}
layout["margin"] = dict(l=24, r=48, t=16, b=24)
people.update_layout(
    **layout,
    title=None,
    showlegend=True,
    height=max(360, 28 * len(ordered) + 80),
)
people.update_xaxes(showgrid=True, gridcolor="rgba(26,35,50,0.08)", title="", range=[0, 110])
people.update_yaxes(
    showgrid=False,
    title="",
    categoryorder="array",
    categoryarray=names_bottom_to_top,
    autorange=True,
)
st.plotly_chart(people, use_container_width=True)

st.divider()

# =========================
# Filters + table
# =========================
st.markdown('<p class="akela-section-label">Таблица</p>', unsafe_allow_html=True)

category = st.selectbox(
    "Категория KPI",
    ["Все", "🟢 75+", "🟡 50+", "🟠 20+", "🔴 1+", "⚫ 0 / не сдал"],
)
search = st.text_input("Поиск сотрудника", placeholder="ФИО или должность…")

filtered_df = df.copy()
if category != "Все":
    filtered_df = filtered_df[filtered_df["Категория"] == category]
if search:
    filtered_df = filtered_df[
        filtered_df["Сотрудник"].str.contains(search, case=False, na=False)
    ]

display_cols = [
    c
    for c in ["Сотрудник", "KPI", "Категория", "Файл", "Обновлено"]
    if c in filtered_df.columns
]
table = filtered_df[display_cols]

if "KPI" in table.columns and not table.empty and table["KPI"].gt(0).any():
    try:
        styled = table.style.background_gradient(subset=["KPI"], cmap="GnBu")
        st.dataframe(styled, use_container_width=True, hide_index=True)
    except ImportError:
        st.dataframe(table, use_container_width=True, hide_index=True)
else:
    st.dataframe(table, use_container_width=True, hide_index=True)
