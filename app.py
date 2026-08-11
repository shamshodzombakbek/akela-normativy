from datetime import date, datetime, timedelta
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
    kpi_category,
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

/* —— Mobile —— */
@media (max-width: 768px) {
  .block-container {
    padding-top: 0.7rem !important;
    padding-left: 0.65rem !important;
    padding-right: 0.65rem !important;
    padding-bottom: 2rem !important;
    max-width: 100% !important;
  }

  div[data-testid="stMetric"] {
    padding: 0.7rem 0.75rem 0.6rem !important;
  }
  div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-size: 1.25rem !important;
  }
  div[data-testid="stMetric"] label {
    font-size: 0.68rem !important;
  }

  /* таблицы можно листать горизонтально */
  div[data-testid="stDataFrame"] {
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch;
  }

  /* на таче не раздуваем hover-scale */
  div[data-testid="stPlotlyChart"]:hover {
    transform: none !important;
    box-shadow: none !important;
  }

  /* не трогаем кнопки шапки/календаря общим min-height */
  .stButton > button {
    box-shadow: none !important;
  }

  div[role="radiogroup"] {
    flex-wrap: wrap !important;
    gap: 0.35rem !important;
  }
  div[role="radiogroup"] label {
    padding: 0.4rem 0.65rem !important;
  }


  .cal-wrap { max-width: 100% !important; }
  .cal-cell { height: 24px !important; }

  iframe {
    max-width: 100% !important;
  }
}

@media (max-width: 420px) {
  div[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-size: 1.1rem !important;
  }
}

/* compact header styles */
.akela-top {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  margin-bottom: 0.6rem;
}
.akela-logo-sm img { max-width: 132px !important; }
.lang-center {
  text-align: right;
  margin: 0;
}
.lang-row {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  justify-content: flex-end;
}
.lang-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  border: 2px solid #D5E0EA;
  text-decoration: none !important;
  overflow: hidden;
  background: #fff;
  box-sizing: border-box;
  padding: 0;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.lang-btn.active {
  border-color: #3E4197;
  box-shadow: 0 0 0 2px rgba(62,65,151,0.25);
}
.lang-btn:hover {
  filter: brightness(0.97);
}
.lang-btn svg {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
  transform: scale(1.35);
}
.cal-center {
  width: 100%;
  max-width: 240px;
  margin: 0 auto;
}
.cal-wrap {
  width: 100%;
  max-width: 240px;
  margin: 0 auto;
}
.cal-grid {
  display: grid;
  grid-template-columns: 24px repeat(7, 1fr);
  gap: 2px;
  font-size: 10px;
}
.cal-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 20px;
  border-radius: 3px;
  text-decoration: none !important;
  color: #1A2332;
  background: #EEF2F6;
  border: 1px solid transparent;
  font-weight: 600;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
a.cal-cell:hover { filter: brightness(0.96); color: inherit; }
.cal-head {
  text-align: center;
  font-size: 10px;
  color: #7A8B9C;
  font-weight: 600;
}
.cal-cell.has-data {
  background: #C6F6D5 !important;
  border-color: #1F7A4C;
  color: #14532d;
}
.cal-cell.selected {
  background: #3E4197 !important;
  color: #fff !important;
  border-color: #2A2D7A;
}
.cal-cell.muted {
  background: transparent;
  color: transparent;
  pointer-events: none;
}
/* стили только внутри колонки шапки — не всего main (иначе :has ломает страницу после rerun) */
div[data-testid="column"]:has(.akela-cal-panel) div[data-testid="stHorizontalBlock"] {
  gap: 2px !important;
  flex-wrap: nowrap !important;
}
div[data-testid="column"]:has(.akela-cal-panel) div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
  min-width: 0 !important;
  flex: 1 1 0 !important;
}
div[data-testid="column"]:has(.akela-cal-panel) button[data-testid="baseButton-secondary"],
div[data-testid="column"]:has(.akela-cal-panel) button[data-testid="baseButton-primary"],
div[data-testid="column"]:has(.akela-cal-panel) .stButton > button {
  min-height: 24px !important;
  height: 24px !important;
  max-height: 24px !important;
  padding: 0 !important;
  font-size: 11px !important;
  border-radius: 4px !important;
  box-shadow: none !important;
  line-height: 1 !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  letter-spacing: 0 !important;
  transform: none !important;
}
div[data-testid="column"]:has(.akela-cal-panel) button[data-testid="baseButton-secondary"] {
  background: #EEF2F6 !important;
  border: 1px solid transparent !important;
  color: #1A2332 !important;
}
div[data-testid="column"]:has(.akela-cal-panel) button[kind="primary"],
div[data-testid="column"]:has(.akela-cal-panel) button[data-testid="baseButton-primary"] {
  background: #3E4197 !important;
  border: 1px solid #2A2D7A !important;
  color: #fff !important;
  background-image: none !important;
}
div[data-testid="column"]:has(.akela-cal-panel) button[data-testid="baseButton-secondary"][aria-label*="report"],
div[data-testid="column"]:has(.akela-cal-panel) button[title*="report"],
div[data-testid="column"]:has(.akela-cal-panel) .stTooltipHoverTarget:has([aria-label*="report"]) button[data-testid="baseButton-secondary"] {
  background: #C6F6D5 !important;
  border: 1px solid #1F7A4C !important;
  color: #14532d !important;
}

.lang-flags-html {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: center;
  margin-top: 0.15rem;
}
.lang-flags-html .lang-btn {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  border: 2px solid #D5E0EA;
  overflow: hidden;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-decoration: none !important;
  background: #fff;
  flex: 0 0 34px;
}
.lang-flags-html .lang-btn.active {
  border-color: #3E4197;
  box-shadow: 0 0 0 2px rgba(62,65,151,0.25);
}
.lang-flags-html .lang-btn svg {
  width: 100%;
  height: 100%;
  display: block;
  transform: scale(1.35);
  pointer-events: none;
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
  border-radius: 4px !important;
  letter-spacing: 0.02em;
  transition: transform 0.15s ease, box-shadow 0.2s ease !important;
}

button[data-testid="baseButton-primary"],
.stButton > button[kind="primary"] {
  border: none !important;
  background: linear-gradient(135deg, var(--teal) 0%, var(--teal-deep) 100%) !important;
  color: #fff !important;
  padding: 0.55rem 1.25rem !important;
  box-shadow: 0 8px 20px rgba(62, 65, 151, 0.22);
}

button[data-testid="baseButton-primary"]:hover,
.stButton > button[kind="primary"]:hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 28px rgba(62, 65, 151, 0.3) !important;
}

button[data-testid="baseButton-secondary"],
.stButton > button[kind="secondary"] {
  border: 1px solid #D5E0EA !important;
  background: #EEF2F6 !important;
  color: #1A2332 !important;
  box-shadow: none !important;
  padding: 0.45rem 0.8rem !important;
}

/* не раздуваем все кнопки на мобилке — календарь/флаги остаются компактными */

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
  transition: transform 0.28s ease, box-shadow 0.28s ease;
  transform-origin: center center;
}
div[data-testid="stPlotlyChart"]:hover {
  transform: scale(1.05);
  box-shadow: 0 14px 36px rgba(26, 35, 50, 0.16);
  z-index: 30;
  position: relative;
}

.stAlert {
  border-radius: 2px !important;
  border-left-width: 3px !important;
}
</style>
""",
    unsafe_allow_html=True,
)

from urllib.parse import urlencode

from i18n import t, month_name, weekday_labels
from schedule import (
    active_window_day,
    now_tashkent,
    can_upload_for_day,
    week_id,
    month_id,
    week_start,
    week_end,
    weeks_in_month,
    month_days,
    parse_week_id,
    viewer_upload_status,
)
from shared_store import (
    load_day,
    load_period,
    publish_day_snapshot,
    publish_period_snapshot,
    remove_employees_from_day,
    load_staffing_overrides,
    upsert_seat_override,
    clear_seat_override,
    set_staffing_override,
    clear_staffing_override,
    admin_upsert_employee,
    days_in_week_with_data,
    days_in_month_with_data,
    weeks_in_month_with_data,
    list_available_weeks,
    list_available_months,
)

import streamlit.components.v1 as components

# Plotly theme
PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Onest, sans-serif", color="#1A2332", size=13),
    margin=dict(l=24, r=16, t=48, b=24),
    title=dict(font=dict(family="Unbounded, sans-serif", size=14, color="#3E4197")),
    colorway=["#3E4197", "#1F7A4C", "#B7791F", "#C53030", "#7A8B9C", "#1A2332"],
)


def _admin_delete_token() -> str:
    try:
        if hasattr(st, "secrets") and st.secrets.get("ADMIN_DELETE_TOKEN"):
            return str(st.secrets["ADMIN_DELETE_TOKEN"]).strip()
    except Exception:
        pass
    return os.getenv("ADMIN_DELETE_TOKEN", "").strip()


_admin_token = _admin_delete_token()
_admin_unlocked = bool(
    _admin_token
    and str(st.query_params.get("admin") or "").strip() == _admin_token
)

now = now_tashkent()
current_slot = active_window_day(now)
upload_ok, upload_reason = can_upload_for_day(current_slot, now)


def _is_mobile() -> bool:
    try:
        ua = ""
        if hasattr(st, "context") and getattr(st.context, "headers", None):
            ua = str(st.context.headers.get("User-Agent") or "")
        ua = ua.lower()
        return any(
            x in ua
            for x in (
                "iphone",
                "ipod",
                "ipad",
                "android",
                "mobile",
                "opera mini",
                "iemobile",
            )
        )
    except Exception:
        return False


_mobile = _is_mobile()

# ---- язык (uz / ru / en) ----
if "lang" not in st.session_state:
    st.session_state.lang = str(st.query_params.get("lang") or "ru").strip().lower()
    if st.session_state.lang not in {"ru", "uz", "en"}:
        st.session_state.lang = "ru"
lang = st.session_state.lang
if "lang" in st.query_params:
    qp_lang = str(st.query_params.get("lang") or "").strip().lower()
    if qp_lang in {"ru", "uz", "en"} and qp_lang != lang:
        st.session_state.lang = qp_lang
        lang = qp_lang


# ---- календарь: по умолчанию сегодняшний активный день ----
if "cal_initialized" not in st.session_state:
    st.session_state.cal_year = current_slot.year
    st.session_state.cal_month = current_slot.month
    st.session_state.cal_day = current_slot
    st.session_state.cal_week = week_id(current_slot)
    st.session_state.cal_initialized = True

# query sync for day clicks from HTML calendar
if "cal_day" in st.query_params:
    try:
        qd = date.fromisoformat(str(st.query_params["cal_day"]))
        st.session_state.cal_day = qd
        st.session_state.cal_week = week_id(qd)
        st.session_state.cal_year = qd.year
        st.session_state.cal_month = qd.month
    except Exception:
        pass
if "cal_week" in st.query_params and "cal_day" not in st.query_params:
    qw = str(st.query_params.get("cal_week") or "").strip()
    if qw:
        st.session_state.cal_week = qw
        st.session_state.cal_day = None
        try:
            ws, _ = parse_week_id(qw)
            st.session_state.cal_year = ws.year
            st.session_state.cal_month = ws.month
        except Exception:
            pass
if st.query_params.get("cal_view") == "month":
    st.session_state.cal_week = None
    st.session_state.cal_day = None

shared_error = None
available_days: list = []
try:
    _, boot_meta = load_day(current_slot)
    available_days = [date.fromisoformat(x) for x in boot_meta.get("available_days") or []]
except Exception as exc:
    shared_error = str(exc)

# ---- шапка: логотип | календарь по центру | флаги справа ----
top_logo, top_cal, top_lang = st.columns([1.0, 1.55, 0.95])

with top_logo:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=88 if _mobile else 120)
    st.caption(t(lang, "subtitle"))

_flag_svgs = {
    "uz": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200" preserveAspectRatio="xMidYMid slice">'
        '<rect width="300" height="200" fill="#1EB53A"/>'
        '<rect width="300" height="133.33" fill="#FFFFFF"/>'
        '<rect width="300" height="66.67" fill="#0099B5"/>'
        '<rect y="60" width="300" height="6.67" fill="#CE1126"/>'
        '<rect y="133.33" width="300" height="6.67" fill="#CE1126"/>'
        '<circle cx="48" cy="33" r="18" fill="#fff"/>'
        '<circle cx="55" cy="33" r="14" fill="#0099B5"/>'
        "</svg>"
    ),
    "ru": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 9 6" preserveAspectRatio="xMidYMid slice">'
        '<rect fill="#fff" width="9" height="6"/>'
        '<rect fill="#0039A6" y="2" width="9" height="4"/>'
        '<rect fill="#D52B1E" y="4" width="9" height="2"/>'
        "</svg>"
    ),
    "en": (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 60 30" preserveAspectRatio="xMidYMid slice">'
        '<rect width="60" height="30" fill="#012169"/>'
        '<path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" stroke-width="6"/>'
        '<path d="M0,0 L60,30 M60,0 L0,30" stroke="#C8102E" stroke-width="3"/>'
        '<path d="M30,0 v30 M0,15 h60" stroke="#fff" stroke-width="10"/>'
        '<path d="M30,0 v30 M0,15 h60" stroke="#C8102E" stroke-width="6"/>'
        "</svg>"
    ),
}


def _lang_href(code: str) -> str:
    """Смена языка через query — флаги HTML, без Streamlit-кнопок (не ломаются после клика)."""
    flat: dict[str, str] = {}
    for k in st.query_params:
        v = st.query_params.get(k)
        if isinstance(v, list):
            v = v[0] if v else ""
        flat[str(k)] = str(v)
    flat["lang"] = code
    return "?" + urlencode(flat)


with top_lang:
    st.markdown(
        f'<p class="akela-section-label" style="margin:0 0 0.25rem;text-align:center">'
        f'{t(lang, "lang")}</p>',
        unsafe_allow_html=True,
    )
    _flag_links = []
    for code in ("uz", "ru", "en"):
        active = " active" if lang == code else ""
        _flag_links.append(
            f'<a class="lang-btn{active}" href="{_lang_href(code)}" '
            f'title="{code.upper()}" aria-label="{code.upper()}">{_flag_svgs[code]}</a>'
        )
    st.markdown(
        f'<div class="lang-flags-html">{"".join(_flag_links)}</div>',
        unsafe_allow_html=True,
    )

with top_cal:
    st.markdown(
        f'<p class="akela-section-label" style="margin:0 0 0.2rem;text-align:center;'
        f'font-size:0.75rem">{t(lang, "calendar")}</p>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="akela-cal-nav">', unsafe_allow_html=True)
    nav_l, nav_c, nav_r = st.columns([1, 4, 1])
    with nav_l:
        if st.button("←", use_container_width=True, key="cal_prev"):
            m = st.session_state.cal_month - 1
            y = st.session_state.cal_year
            if m < 1:
                m, y = 12, y - 1
            st.session_state.cal_month = m
            st.session_state.cal_year = y
            st.session_state.cal_week = None
            st.session_state.cal_day = None
            for k in ("cal_day", "cal_week", "cal_view"):
                if k in st.query_params:
                    del st.query_params[k]
            st.rerun()
    with nav_c:
        month_label = f"{month_name(lang, st.session_state.cal_month)} {st.session_state.cal_year}"
        month_view_active = (
            st.session_state.cal_week is None and st.session_state.cal_day is None
        )
        if st.button(
            month_label,
            use_container_width=True,
            key="cal_month_title",
            type="primary" if month_view_active else "secondary",
        ):
            st.session_state.cal_week = None
            st.session_state.cal_day = None
            for k in ("cal_day", "cal_week", "cal_view"):
                if k in st.query_params:
                    del st.query_params[k]
            st.rerun()
    with nav_r:
        if st.button("→", use_container_width=True, key="cal_next"):
            m = st.session_state.cal_month + 1
            y = st.session_state.cal_year
            if m > 12:
                m, y = 1, y + 1
            st.session_state.cal_month = m
            st.session_state.cal_year = y
            st.session_state.cal_week = None
            st.session_state.cal_day = None
            for k in ("cal_day", "cal_week", "cal_view"):
                if k in st.query_params:
                    del st.query_params[k]
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    cal_y, cal_m = st.session_state.cal_year, st.session_state.cal_month
    month_key = f"{cal_y:04d}-{cal_m:02d}"
    data_days_set = {d for d in available_days if d.year == cal_y and d.month == cal_m}

    st.markdown('<div class="akela-cal-panel cal-wrap">', unsafe_allow_html=True)
    wd = weekday_labels(lang)
    head = st.columns([0.75] + [1] * 7)
    head[0].caption(t(lang, "week_col"))
    for i, lab in enumerate(wd):
        head[i + 1].caption(lab)

    for wid, ws, we in weeks_in_month(cal_y, cal_m):
        row = st.columns([0.75] + [1] * 7)
        week_sel = st.session_state.cal_week == wid and st.session_state.cal_day is None
        with row[0]:
            if st.button(
                wid.split("-W")[-1],
                key=f"cal_w_{wid}",
                use_container_width=True,
                type="primary" if week_sel else "secondary",
                help=f"{ws.strftime('%d.%m')}–{we.strftime('%d.%m')}",
            ):
                st.session_state.cal_week = wid
                st.session_state.cal_day = None
                for k in ("cal_day", "cal_week", "cal_view"):
                    if k in st.query_params:
                        del st.query_params[k]
                st.rerun()
        cur = ws
        for di in range(7):
            in_month = cur.month == cal_m and cur.year == cal_y
            with row[di + 1]:
                if not in_month:
                    st.button(
                        "·",
                        key=f"cal_pad_{wid}_{di}",
                        use_container_width=True,
                        disabled=True,
                    )
                else:
                    has_data = cur in data_days_set
                    is_sel = st.session_state.cal_day == cur
                    if st.button(
                        str(cur.day),
                        key=f"cal_d_{cur.isoformat()}",
                        use_container_width=True,
                        type="primary" if is_sel else "secondary",
                        help=("report" if has_data else None),
                    ):
                        st.session_state.cal_day = cur
                        st.session_state.cal_week = week_id(cur)
                        st.session_state.cal_year = cur.year
                        st.session_state.cal_month = cur.month
                        for k in ("cal_day", "cal_week", "cal_view"):
                            if k in st.query_params:
                                del st.query_params[k]
                        st.rerun()
            cur += timedelta(days=1)
    st.markdown("</div>", unsafe_allow_html=True)
    st.caption(t(lang, "cal_hint"))



cal_y, cal_m = st.session_state.cal_year, st.session_state.cal_month
month_key = f"{cal_y:04d}-{cal_m:02d}"

selected_day = st.session_state.cal_day
selected_week = st.session_state.cal_week
if selected_day is not None:
    view_mode = "day"
elif selected_week:
    view_mode = "week"
else:
    view_mode = "month"

if view_mode == "day":
    view_title = f"{t(lang, 'day')} {selected_day.strftime('%d.%m.%Y')}"
elif view_mode == "week":
    try:
        w0, w1 = parse_week_id(selected_week)
        view_title = (
            f"{t(lang, 'week')} {selected_week} · "
            f"{w0.strftime('%d.%m')}–{w1.strftime('%d.%m.%Y')}"
        )
    except Exception:
        view_title = f"{t(lang, 'week')} {selected_week}"
else:
    view_title = f"{t(lang, 'month')} {month_name(lang, cal_m)} {cal_y}"

st.info(f"{t(lang, 'viewing')}: **{view_title}**")

if not _admin_unlocked:
    if view_mode == "day" and selected_day is not None:
        _vnote = viewer_upload_status(kind="day", day=selected_day)
    elif view_mode == "week" and selected_week:
        _vnote = viewer_upload_status(kind="week", week_key=selected_week)
    else:
        _vnote = viewer_upload_status(kind="month", year=cal_y, month=cal_m)
    # map known RU notes if status returns RU hardcoded — viewer_upload_status already RU;
    # use status text as-is for now (backend messages); prefer i18n keys when closed/not_yet
    if _vnote:
        if "ещё не наступил" in _vnote or "hali" in _vnote:
            st.caption(f"· {t(lang, 'not_yet')}")
        elif "закрыта" in _vnote or "yopilgan" in _vnote or "closed" in _vnote:
            st.caption(f"· {t(lang, 'closed')}")
        elif "приём" in _vnote or "qabul" in _vnote or "accepting" in _vnote:
            st.caption(f"· {t(lang, 'receiving')}")
        else:
            st.caption(f"· {_vnote}")

# ---- Загрузка Excel (только админ ?admin=, без ограничений по дате) ----
if _admin_unlocked:
    st.markdown(
        f'<p class="akela-section-label">{t(lang, "upload")}</p>',
        unsafe_allow_html=True,
    )
    upload_kind = st.radio(
        t(lang, "report_type"),
        options=["day", "week", "month"],
        format_func=lambda k: {
            "day": t(lang, "type_day"),
            "week": t(lang, "type_week"),
            "month": t(lang, "type_month"),
        }[k],
        horizontal=True,
        key="upload_kind",
    )
    if upload_kind == "day":
        target_ref = selected_day or current_slot
        st.caption(
            f"Слот дня: {target_ref.strftime('%d.%m.%Y')} · админ — без ограничений по времени"
        )
    elif upload_kind == "week":
        if selected_week:
            target_ref, _ = parse_week_id(selected_week)
        elif selected_day:
            target_ref = selected_day
        else:
            target_ref = current_slot
        st.caption(f"Недельный слот: {week_id(target_ref)} · админ — без ограничений")
    else:
        target_ref = date(cal_y, cal_m, 1)
        st.caption(f"Месячный слот: {month_id(target_ref)} · админ — без ограничений")

    if shared_error:
        st.warning(
            "Google Drive пока недоступен.\n\n"
            f"`{shared_error}`"
        )

    uploaded_files = st.file_uploader(
        "Excel-отчёты",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key=f"uploader_{upload_kind}",
    )

    if uploaded_files and st.button("Показать всем", type="primary"):
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
                if upload_kind == "day":
                    df_pub, meta = publish_day_snapshot(
                        incoming,
                        window_day=target_ref,
                        replace=False,
                        allow_outside_window=True,
                        force=True,
                    )
                else:
                    df_pub, meta = publish_period_snapshot(
                        incoming,
                        kind=upload_kind,
                        ref=target_ref,
                        replace=False,
                        allow_outside_window=True,
                        force=True,
                    )
            st.success(
                f"Сохранено ({upload_kind_label.lower()}): "
                f"{meta.get('count', len(df_pub))} записей · "
                f"{meta.get('period_label') or meta.get('window_day')}"
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Не удалось сохранить. `{exc}`")
            st.stop()

# ---- Загрузка данных периода ----
nested_weekly: list[tuple[str, pd.DataFrame]] = []
nested_daily: list[tuple[date, pd.DataFrame]] = []

try:
    if view_mode == "day":
        df, shared_meta = load_period("day", selected_day)
    elif view_mode == "week":
        df, shared_meta = load_period("week", selected_week)
        for d in days_in_week_with_data(selected_week):
            ddf, _ = load_period("day", d)
            if not ddf.empty:
                nested_daily.append((d, ddf))
    else:
        df, shared_meta = load_period("month", month_key)
        for wkey in weeks_in_month_with_data(month_key):
            wdf, _ = load_period("week", wkey)
            if not wdf.empty:
                nested_weekly.append((wkey, wdf))
        for d in days_in_month_with_data(month_key):
            ddf, _ = load_period("day", d)
            if not ddf.empty:
                nested_daily.append((d, ddf))
except Exception as exc:
    if shared_error:
        st.info("Пока нет данных за этот период. Загрузите Excel выше.")
        st.stop()
    st.error(f"Не удалось загрузить период: `{exc}`")
    st.stop()

if df is None:
    df = pd.DataFrame()

# Для штата/графиков primary = df периода.
# Админ seat overrides и Excel-правки дня — только в режиме дня.
admin_day = selected_day if view_mode == "day" and selected_day is not None else None
if admin_day is None and view_mode == "day":
    admin_day = current_slot
# selected_day используется ниже в админке — подставляем день только если он выбран
selected_day_for_admin = admin_day

# =========================
# Админ-панель (скрыто: ?admin=ТОКЕН из Secrets)
# =========================
staffing_ov: dict = {}
try:
    staffing_ov = load_staffing_overrides()
except Exception:
    staffing_ov = {}

seat_ov = shared_meta.get("seat_overrides") or {}
if not isinstance(seat_ov, dict):
    seat_ov = {}

staffing = load_staffing(overrides=staffing_ov)
roster = load_employees_roster()
# Живая штатка важнее CSV roster, если есть кадровые overrides
if staffing_ov and not staffing.empty:
    occ = staffing[staffing["Статус_места"] == "Занято"].copy()
    if not occ.empty:
        cols = [c for c in ["ФИО", "Должность", "Пометка"] if c in occ.columns]
        roster = occ[cols].copy().reset_index(drop=True)

attendance = build_roster_attendance(roster, df if not df.empty else None)
filled_staff = build_filled_staffing_with_reports(
    staffing,
    attendance,
    submitted=df if not df.empty else None,
    seat_overrides=seat_ov,
)
vacancies = (
    staffing[staffing["Статус_места"] == "Вакансия"].copy()
    if not staffing.empty
    else pd.DataFrame()
)

if _admin_unlocked:
    with st.expander("Админ · статусы и штатка", expanded=True):
        st.caption(f"{view_title} · правки сохраняются в shared_kpi.json.")
        if shared_error:
            st.warning(f"Google Drive: `{shared_error}`")
        tab_status, tab_staff, tab_excel = st.tabs(
            ["Статусы сдачи", "Штатка", "Excel-записи"]
        )

        with tab_status:
            if not selected_day_for_admin:
                st.info("Выберите день в календаре, чтобы править статусы сдачи.")
            else:
                editable = (
                    filled_staff[filled_staff["Статус"] != "➖ Не обязан"].copy()
                    if not filled_staff.empty
                    else pd.DataFrame()
                )
                if editable.empty:
                    st.info("Нет мест, по которым можно править статус.")
                else:
                    seat_labels = []
                    seat_codes = []
                    for _, row in editable.iterrows():
                        code = str(row.get("Код") or "")
                        label = (
                            f"{code} · {row.get('Должность') or ''} · "
                            f"{row.get('ФИО') or ''} · сейчас: {row.get('Статус') or ''}"
                        )
                        seat_labels.append(label)
                        seat_codes.append(code)
                    pick_label = st.selectbox(
                        "Место",
                        seat_labels,
                        key="admin_status_seat",
                    )
                    pick_idx = seat_labels.index(pick_label) if pick_label in seat_labels else 0
                    pick_code = seat_codes[pick_idx]
                    cur = editable.iloc[pick_idx]
                    has_manual = pick_code in seat_ov
                    if has_manual:
                        st.caption("На этом месте уже есть ручная правка статуса.")

                    new_status = st.selectbox(
                        "Статус",
                        ["✅ Сдал", "⚫ 0%", "❌ Не сдал"],
                        index=["✅ Сдал", "⚫ 0%", "❌ Не сдал"].index(
                            str(cur.get("Статус") or "❌ Не сдал")
                        )
                        if str(cur.get("Статус") or "") in {"✅ Сдал", "⚫ 0%", "❌ Не сдал"}
                        else 2,
                        key="admin_status_value",
                    )
                    new_kpi = st.number_input(
                        "KPI %",
                        min_value=0.0,
                        max_value=100.0,
                        value=float(cur.get("KPI") or 0),
                        step=1.0,
                        key="admin_status_kpi",
                        disabled=new_status != "✅ Сдал",
                    )
                    c1, c2 = st.columns(2)
                    if c1.button("Сохранить статус", type="primary", key="admin_save_status"):
                        try:
                            with st.spinner("Сохраняю…"):
                                upsert_seat_override(
                                    pick_code,
                                    new_status,
                                    kpi=new_kpi if new_status == "✅ Сдал" else 0.0,
                                    window_day=selected_day_for_admin,
                                )
                            st.success("Статус сохранён.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Не удалось сохранить: `{exc}`")
                    if c2.button(
                        "Сбросить ручную правку",
                        key="admin_clear_status",
                        disabled=not has_manual,
                    ):
                        try:
                            with st.spinner("Сбрасываю…"):
                                clear_seat_override(
                                    pick_code, window_day=selected_day_for_admin
                                )
                            st.success("Ручная правка снята.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Не удалось сбросить: `{exc}`")

        with tab_staff:
            if staffing.empty:
                st.info("Штатка пуста.")
            else:
                staff_labels = []
                staff_codes = []
                for _, row in staffing.iterrows():
                    code = str(row.get("Код") or "")
                    mark = " · override" if code in staffing_ov else ""
                    staff_labels.append(
                        f"{code} · {row.get('Должность') or ''} · "
                        f"{row.get('ФИО') or '— вакансия'} · {row.get('Статус_места') or ''}{mark}"
                    )
                    staff_codes.append(code)
                s_label = st.selectbox("Место штатки", staff_labels, key="admin_staff_seat")
                s_idx = staff_labels.index(s_label) if s_label in staff_labels else 0
                s_code = staff_codes[s_idx]
                s_row = staffing.iloc[s_idx]
                s_fio = str(s_row.get("ФИО") or "")
                s_status = str(s_row.get("Статус_места") or "")
                s_note = str(s_row.get("Пометка") or "")
                if s_code in staffing_ov:
                    st.caption("Есть кадровая правка поверх staffing.csv.")

                action = st.radio(
                    "Действие",
                    ["Уволить (вакансия)", "Заменить / занять", "Сбросить к CSV"],
                    horizontal=True,
                    key="admin_staff_action",
                )
                new_fio = st.text_input(
                    "Новое ФИО",
                    value=s_fio,
                    key="admin_staff_fio",
                    disabled=action != "Заменить / занять",
                )
                new_note = st.text_input(
                    "Пометка (например юклатилган)",
                    value=s_note if action == "Заменить / занять" else "",
                    key="admin_staff_note",
                    disabled=action != "Заменить / занять",
                )
                if st.button("Применить к штатке", type="primary", key="admin_staff_apply"):
                    try:
                        with st.spinner("Сохраняю штатку…"):
                            if action == "Уволить (вакансия)":
                                set_staffing_override(
                                    s_code,
                                    fio="",
                                    status="Вакансия",
                                    note="",
                                    action="quit",
                                    prev_fio=s_fio or None,
                                )
                            elif action == "Заменить / занять":
                                set_staffing_override(
                                    s_code,
                                    fio=new_fio,
                                    status="Занято",
                                    note=new_note,
                                    action="replace" if s_status == "Занято" else "hire",
                                    prev_fio=s_fio or None,
                                )
                            else:
                                clear_staffing_override(s_code)
                        st.success("Штатка обновлена.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Не удалось обновить штатку: `{exc}`")

        with tab_excel:
            if not selected_day_for_admin:
                st.info("Выберите день в календаре, чтобы править Excel-записи дня.")
            else:
                st.caption("Прямые строки Excel-слоя дня (имя из файла отчёта).")
                if not df.empty and "Сотрудник" in df.columns:
                    options = []
                    for _, row in df.iterrows():
                        name = str(row.get("Сотрудник") or "")
                        fname = str(row.get("Файл") or "")
                        kpi = row.get("KPI")
                        label = f"{name} · KPI {kpi}" + (f" · {fname}" if fname else "")
                        options.append((label, name))
                    labels = [o[0] for o in options]
                    picked = st.multiselect(
                        "Удалить записи",
                        labels,
                        placeholder="например ofis-administrator…",
                        key="admin_excel_del",
                    )
                    if st.button("Удалить выбранные", type="secondary", key="admin_excel_del_btn"):
                        names = [name for label, name in options if label in picked]
                        if not names:
                            st.warning("Ничего не выбрано.")
                        else:
                            try:
                                with st.spinner("Удаляю…"):
                                    _, meta_del = remove_employees_from_day(
                                        names, window_day=selected_day_for_admin
                                    )
                                st.success(f"Удалено: {meta_del.get('removed', 0)}")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Не удалось удалить: `{exc}`")
                else:
                    st.caption("За выбранный день Excel-записей нет.")

                with st.form("admin_excel_add"):
                    st.markdown("**Добавить строку вручную**")
                    add_name = st.text_input("Сотрудник / имя из файла")
                    add_kpi = st.number_input(
                        "KPI %", min_value=0.0, max_value=100.0, value=0.0
                    )
                    add_file = st.text_input("Файл", value="(admin)")
                    if st.form_submit_button("Добавить", type="primary"):
                        try:
                            with st.spinner("Добавляю…"):
                                admin_upsert_employee(
                                    add_name,
                                    kpi=add_kpi,
                                    file_name=add_file,
                                    window_day=selected_day_for_admin,
                                )
                            st.success("Добавлено.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Не удалось добавить: `{exc}`")

bits = [view_title]
if shared_meta.get("updated_at"):
    bits.append(f"Обновлено: {shared_meta['updated_at']}")
if not staffing.empty:
    bits.append(
        f"Штат: {staffing.attrs.get('seats_filled', 0)}/"
        f"{staffing.attrs.get('seats_total', len(staffing))} занято"
    )
elif not roster.empty:
    bits.append(f"В списке: {attendance.attrs.get('total', len(attendance))}")
if _admin_unlocked:
    st.caption(" · ".join(bits))

# =========================
# Metrics + charts (Excel или «все не сдали»)
# =========================
from utils import kpi_category as _kpi_cat

has_uploads = not (df is None or df.empty or "KPI" not in getattr(df, "columns", []))

# Для диаграмм: если загрузок нет — весь штат (уникальные) как «не сдал»
if has_uploads:
    chart_df = df.copy()
    if "Категория" not in chart_df.columns:
        chart_df["Категория"] = chart_df["KPI"].map(
            lambda x: kpi_category(float(x) if x is not None else None)
        )
else:
    # сплошной чёрный «не сдал» только по обязанным должностям (без директоров)
    if not filled_staff.empty:
        required = filled_staff[filled_staff["Статус"] != "➖ Не обязан"]
        labels = [
            f"{str(r.get('Должность') or '').strip()} · {str(r.get('ФИО') or '').strip()}".strip(" ·")
            for _, r in required.iterrows()
        ]
    else:
        labels = ["Должность 1"]
    seats_n = len(labels) or 1
    if not labels:
        labels = ["Должность 1"]
        seats_n = 1
    chart_df = pd.DataFrame(
        {
            "Сотрудник": labels,
            "KPI": [0.0] * seats_n,
            "Категория": ["⚫ 0 / не сдал"] * seats_n,
        }
    )

st.markdown(
    f'<p class="akela-section-label">{t(lang, "dashboard")}</p>',
    unsafe_allow_html=True,
)

# Вложенные отчёты периода (неделя/день внутри месяца или дни внутри недели)
if view_mode == "month" and (nested_weekly or nested_daily):
    st.markdown(
        f'<p class="akela-section-label">{t(lang, "month")}</p>', unsafe_allow_html=True
    )
    if nested_weekly:
        with st.expander(f"Недельные отчёты ({len(nested_weekly)})", expanded=False):
            for wkey, wdf in nested_weekly:
                try:
                    ws, we = parse_week_id(wkey)
                    label = f"{wkey} · {ws.strftime('%d.%m')}–{we.strftime('%d.%m')}"
                except Exception:
                    label = wkey
                st.markdown(f"**{label}** · записей: {len(wdf)}")
                show = [c for c in ["Сотрудник", "KPI", "Категория", "Файл"] if c in wdf.columns]
                st.dataframe(wdf[show], use_container_width=True, hide_index=True)
    if nested_daily:
        with st.expander(f"Дневные отчёты ({len(nested_daily)})", expanded=False):
            for d, ddf in nested_daily:
                st.markdown(f"**{d.strftime('%d.%m.%Y')}** · записей: {len(ddf)}")
                show = [c for c in ["Сотрудник", "KPI", "Категория", "Файл"] if c in ddf.columns]
                st.dataframe(ddf[show], use_container_width=True, hide_index=True)
elif view_mode == "week" and nested_daily:
    st.markdown(
        '<p class="akela-section-label">Дни этой недели</p>', unsafe_allow_html=True
    )
    with st.expander(f"Дневные отчёты ({len(nested_daily)})", expanded=True):
        for d, ddf in nested_daily:
            st.markdown(f"**{d.strftime('%d.%m.%Y')}** · записей: {len(ddf)}")
            show = [c for c in ["Сотрудник", "KPI", "Категория", "Файл"] if c in ddf.columns]
            st.dataframe(ddf[show], use_container_width=True, hide_index=True)

if not has_uploads and _admin_unlocked:
    st.caption("Пока нет загруженных Excel — статистика: 100% не сдали.")

with_kpi = chart_df[chart_df["KPI"] > 0] if "KPI" in chart_df.columns else chart_df

c1, c2, c3, c4 = st.columns(4)
if has_uploads:
    c1.metric(t(lang, "excel_records"), len(df))
    c2.metric(t(lang, "avg"), f"{df['KPI'].mean():.1f}%")
    c3.metric(t(lang, "max"), f"{df['KPI'].max():.1f}%")
    c4.metric(t(lang, "min"), f"{df['KPI'].min():.1f}%")
else:
    c1.metric(t(lang, "excel_records"), 0)
    c2.metric(t(lang, "avg"), "0%")
    c3.metric(t(lang, "submitted"), "0%")
    c4.metric(t(lang, "missing"), "100%")

st.divider()

# =========================
# Charts
# =========================
st.markdown(
    f'<p class="akela-section-label">{t(lang, "charts")}</p>',
    unsafe_allow_html=True,
)

cat_order = ["🟢 75+", "🟡 50+", "🟠 20+", "🔴 1+", "⚫ 0 / не сдал"]
cat_colors = {
    "🟢 75+": "#22A06B",
    "🟡 50+": "#E2B203",
    "🟠 20+": "#E06C00",
    "🔴 1+": "#E34935",
    "⚫ 0 / не сдал": "#1A1A1A",
}

# Отдельная круговая: сдали / не сдали (когда нет загрузок — сплошной чёрный 100%)
submit_label = t(lang, "filter_bad")
ok_label = t(lang, "filter_ok")
if has_uploads and not filled_staff.empty:
    sub_n_chart = int(filled_staff.attrs.get("submitted") or 0)
    miss_n_chart = int(filled_staff.attrs.get("missing") or 0)
elif has_uploads:
    sub_n_chart = int((chart_df["KPI"] > 0).sum())
    miss_n_chart = int((chart_df["KPI"] <= 0).sum())
else:
    sub_n_chart = 0
    miss_n_chart = int(len(chart_df))

submit_stats = pd.DataFrame(
    {
        "Статус": [ok_label, submit_label],
        "Количество": [sub_n_chart, miss_n_chart],
    }
)
submit_stats = submit_stats[submit_stats["Количество"] > 0]
submit_stats = submit_stats.assign(
    _code=submit_stats["Статус"].map({ok_label: "ok", submit_label: "bad"})
)
submit_colors = {ok_label: "#22A06B", submit_label: "#1A1A1A"}
_pie_layout = {k: v for k, v in PLOTLY_LAYOUT.items() if k not in {"margin", "title"}}


def _map_drill_label(lab: str) -> str | None:
    lab = (lab or "").strip()
    if not lab:
        return None
    if lab in {"ok", "bad"} or lab in cat_order:
        return lab
    if lab == ok_label or lab in {
        "✅ Сдали",
        "✅ Сдал",
        "✅ Topshirdi",
        "✅ Submitted",
    }:
        return "ok"
    if lab == submit_label or lab in {
        "❌ Не сдали",
        "❌ Не сдал",
        "❌ Topshirmadi",
        "❌ Missing",
    }:
        return "bad"
    return None


def _scroll_to_staff():
    components.html(
        """
        <script>
        (function () {
          const doc = window.parent.document;
          const el = doc.getElementById("akela-staff-anchor");
          if (el) {
            setTimeout(function () {
              el.scrollIntoView({ behavior: "smooth", block: "start" });
            }, 220);
          }
        })();
        </script>
        """,
        height=0,
    )


def _clickable_pie(fig, *, key: str, height: int = 380) -> None:
    """Pie with real plotly_click — Streamlit on_select does not work on pies."""
    fig.update_layout(height=height, autosize=True)
    fig_json = fig.to_json()
    dom_id = "".join(ch if ch.isalnum() else "_" for ch in key)
    hover_scale = "none" if _mobile else "scale(1.05)"
    html = f"""
<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  html, body {{ margin:0; padding:0; background:transparent; overflow:hidden; }}
  .wrap {{
    transition: transform 0.28s ease, box-shadow 0.28s ease;
    transform-origin: center center;
    border-radius: 2px;
    padding: 4px;
    width: 100%;
    box-sizing: border-box;
  }}
  .wrap:hover {{
    transform: {hover_scale};
    box-shadow: {"none" if _mobile else "0 14px 36px rgba(26,35,50,0.16)"};
  }}
  #{dom_id} {{ width: 100%; height: {height}px; cursor: pointer; }}
</style>
</head><body>
<div class="wrap"><div id="{dom_id}"></div></div>
<script>
const fig = {fig_json};
const layout = Object.assign({{}}, fig.layout || {{}}, {{
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  height: {height},
  autosize: true,
  margin: Object.assign({{l:8,r:8,t:40,b:40}}, (fig.layout && fig.layout.margin) || {{}})
}});
Plotly.newPlot("{dom_id}", fig.data, layout, {{
  displayModeBar: false,
  responsive: true,
  staticPlot: false
}}).then(function(gd) {{
  window.addEventListener("resize", function() {{ Plotly.Plots.resize(gd); }});
  gd.on("plotly_click", function(data) {{
    if (!data || !data.points || !data.points.length) return;
    const p = data.points[0];
    let code = "";
    if (Array.isArray(p.customdata) && p.customdata.length) {{
      code = (p.customdata[0] || "").toString();
    }} else if (p.customdata != null) {{
      code = String(p.customdata);
    }} else {{
      code = (p.label || p.name || "").toString();
    }}
    if (!code) return;
    const u = new URL(window.parent.location.href);
    u.searchParams.set("drill", code);
    u.searchParams.set("drill_go", "1");
    window.parent.location.href = u.toString();
  }});
}});
</script>
</body></html>
"""
    components.html(html, height=height + 16, scrolling=False)


# клик по диаграмме → фильтр штата + прокрутка к таблице штата
_just_clicked = str(st.query_params.get("drill_go") or "") == "1"
if "drill" in st.query_params:
    mapped = _map_drill_label(str(st.query_params.get("drill") or ""))
    if mapped in {"ok", "bad"}:
        st.session_state.staff_status_filter = mapped
        st.session_state.staff_kpi_cat = None
        st.session_state.chart_drill = mapped
    elif mapped in cat_order:
        st.session_state.staff_status_filter = "all"
        st.session_state.staff_kpi_cat = mapped
        st.session_state.chart_drill = mapped
if _just_clicked:
    st.session_state["_scroll_staff"] = True
    if "drill_go" in st.query_params:
        try:
            del st.query_params["drill_go"]
        except Exception:
            pass

_pie_h = 300 if _mobile else 380
_pie_cols = st.columns(1) if _mobile else st.columns(2)

with _pie_cols[0]:
    pie = px.pie(
        submit_stats,
        names="Статус",
        values="Количество",
        hole=0.58,
        title=t(lang, "pie_submit"),
        color="Статус",
        color_discrete_map=submit_colors,
        custom_data=["_code"],
    )
    pie.update_traces(
        textposition="outside",
        textinfo="percent+label",
        textfont_size=12,
        textfont_color="#1A2332",
        pull=[0.035] * max(len(submit_stats), 1),
        hovertemplate="<b>%{label}</b><br>%{percent}<br>%{value}<extra></extra>",
        hoverlabel=dict(bgcolor="#ffffff", font_size=15, font_color="#1A2332"),
    )
    pie.update_layout(
        **_pie_layout,
        showlegend=True,
        legend=dict(orientation="h", y=-0.12),
        margin=dict(l=16, r=16, t=48, b=48),
        hovermode="closest",
    )
    _clickable_pie(pie, key="pie_submit_click", height=_pie_h)

with (_pie_cols[0] if _mobile else _pie_cols[1]):
    stats = chart_df["Категория"].value_counts().reindex(cat_order).dropna().reset_index()
    stats.columns = ["Категория", "Количество"]
    if stats.empty:
        stats = pd.DataFrame({"Категория": ["⚫ 0 / не сдал"], "Количество": [len(chart_df) or 1]})
    stats = stats.assign(_code=stats["Категория"])
    pie2 = px.pie(
        stats,
        names="Категория",
        values="Количество",
        hole=0.58,
        title=t(lang, "pie_cats"),
        color="Категория",
        color_discrete_map=cat_colors,
        custom_data=["_code"],
    )
    pie2.update_traces(
        textposition="outside",
        textinfo="percent+label",
        textfont_size=12,
        textfont_color="#1A2332",
        pull=[0.035] * max(len(stats), 1),
        hovertemplate="<b>%{label}</b><br>%{percent}<br>%{value}<extra></extra>",
        hoverlabel=dict(bgcolor="#ffffff", font_size=15, font_color="#1A2332"),
    )
    pie2.update_layout(
        **_pie_layout,
        showlegend=True,
        legend=dict(orientation="h", y=-0.12),
        margin=dict(l=16, r=16, t=48, b=56),
        hovermode="closest",
    )
    _clickable_pie(pie2, key="pie_cats_click", height=_pie_h)

if not has_uploads:
    if _admin_unlocked:
        st.caption("Диаграммы: 100% «не сдал» — пока никто не загрузил Excel за этот день.")

if has_uploads:
    sort_cols = st.columns([2.2, 1.2])
    with sort_cols[0]:
        st.markdown(
            f'<p style="font-family:Unbounded,sans-serif;font-size:0.95rem;'
            f'color:#3E4197;margin:0.85rem 0 0.35rem;">{t(lang, "people_chart")}</p>',
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
            key="people_sort_mode",
        )

    ordered = df.copy()
    ordered["_sort_name"] = ordered["Сотрудник"].astype(str).str.strip().str.casefold()

    if sort_mode == "По алфавиту":
        ordered = ordered.sort_values(["_sort_name", "Сотрудник"], ascending=[True, True])
    elif sort_mode == "По процентам: с высокого":
        ordered = ordered.sort_values(["KPI", "_sort_name"], ascending=[False, True])
    else:
        ordered = ordered.sort_values(["KPI", "_sort_name"], ascending=[True, True])

    ordered = ordered.drop(columns=["_sort_name"])
    names_top_to_bottom = ordered["Сотрудник"].tolist()
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
    people.update_traces(
        texttemplate="%{x:.1f}%",
        textposition="outside",
        textfont=dict(color="#1A2332", size=12, family="Onest, sans-serif"),
        cliponaxis=False,
        insidetextanchor="middle",
    )
    layout = {k: v for k, v in PLOTLY_LAYOUT.items() if k != "title"}
    layout["margin"] = dict(l=12, r=80, t=16, b=24)
    xmax = float(ordered["KPI"].max()) if not ordered.empty else 100.0
    people.update_layout(
        **layout,
        title=None,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        height=max(360, 32 * len(ordered) + 100),
        bargap=0.25,
    )
    people.update_xaxes(
        showgrid=True,
        gridcolor="rgba(26,35,50,0.08)",
        title="",
        range=[0, max(120.0, xmax * 1.18 + 8)],
        ticksuffix="%",
    )
    people.update_yaxes(
        showgrid=False,
        title="",
        categoryorder="array",
        categoryarray=names_bottom_to_top,
        autorange=True,
        tickfont=dict(size=12, color="#1A2332"),
    )
    st.plotly_chart(people, use_container_width=True)

    st.divider()

    # =========================
    # Filters + table
    # =========================
    st.markdown(
        f'<p class="akela-section-label">{t(lang, "table")}</p>',
        unsafe_allow_html=True,
    )

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

    st.divider()

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

    st.markdown(
        '<div id="akela-staff-anchor" style="height:1px;scroll-margin-top:1rem;"></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="akela-section-label">{t(lang, "staff")}</p>',
        unsafe_allow_html=True,
    )
    s1, s2, s3, s4 = st.columns(4)
    s1.metric(t(lang, "seats"), seats_total or "—")
    s2.metric(
        t(lang, "must_submit"),
        int(filled_staff.attrs.get("total") or seats_filled),
    )
    s3.metric(t(lang, "submitted"), sub_n)
    s4.metric(t(lang, "missing"), miss_n)
    denom = int(filled_staff.attrs.get("people_total") or seats_filled or 0)
    exempt_n = int(filled_staff.attrs.get("exempt") or 0)
    if _admin_unlocked:
        st.caption(
            f"Сдали {people_rate:.0f}% от должностей, которые обязаны сдавать"
            + (f" ({denom})" if denom else "")
            + (f" · директора вне графика: {exempt_n}" if exempt_n else "")
            + (f" · вакансий отдельно: {seats_vacant}" if seats_vacant else "")
        )

    status_filter = st.radio(
        "Фильтр штата",
        options=["all", "ok", "bad", "exempt"],
        format_func=lambda k: {
            "all": t(lang, "filter_all"),
            "ok": t(lang, "filter_ok"),
            "bad": t(lang, "filter_bad"),
            "exempt": t(lang, "filter_exempt"),
        }[k],
        horizontal=True,
        label_visibility="collapsed",
        key="staff_status_filter",
    )
    search_staff = st.text_input(
        t(lang, "search_staff"),
        placeholder="ФИО…",
        key="staff_search",
    )

    staff_view = filled_staff.copy()
    if status_filter == "ok":
        staff_view = staff_view[staff_view["Статус"] != "❌ Не сдал"]
        staff_view = staff_view[staff_view["Статус"] != "➖ Не обязан"]
    elif status_filter == "bad":
        staff_view = staff_view[staff_view["Статус"] == "❌ Не сдал"]
    elif status_filter == "exempt":
        staff_view = staff_view[staff_view["Статус"] == "➖ Не обязан"]

    kpi_cat = st.session_state.get("staff_kpi_cat")
    if kpi_cat:
        if "Категория" not in staff_view.columns:
            staff_view = staff_view.copy()
            staff_view["Категория"] = staff_view["KPI"].map(
                lambda x: kpi_category(float(x) if x is not None and str(x) != "" else None)
            )
        staff_view = staff_view[staff_view["Категория"] == kpi_cat]
        st.caption(f"{kpi_cat}")

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

    if st.session_state.pop("_scroll_staff", False):
        _scroll_to_staff()

    unmatched = list(filled_staff.attrs.get("unmatched_uploads") or []) or list(
        attendance.attrs.get("unmatched_uploads") or []
    )
    if unmatched and _admin_unlocked:
        st.caption(
            "Отчёты вне списка (не сопоставлены с ФИО/должностью): "
            + ", ".join(unmatched[:12])
            + ("…" if len(unmatched) > 12 else "")
        )

    # =========================
    # Вакансии — отдельный раздел
    # =========================
    st.markdown(
        f'<p class="akela-section-label">{t(lang, "vacancies")}</p>',
        unsafe_allow_html=True,
    )
    if vacancies.empty:
        if _admin_unlocked:
            st.caption(t(lang, "no_vac"))
    else:
        if _admin_unlocked:
            st.caption(f"{t(lang, 'open_vac')}: {len(vacancies)}")
        search_vac = st.text_input(
            t(lang, "search_vac"),
            placeholder="…",
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

