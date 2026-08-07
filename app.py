import streamlit as st
import plotly.express as px
from utils import load_uploaded_employees

st.set_page_config(
    page_title="KPI Dashboard",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Панель ключевых показателей эффективности")

uploaded_files = st.file_uploader(
    "📂 Выберите Excel-файлы сотрудников",
    type=["xlsx", "xls"],
    accept_multiple_files=True
)

if not uploaded_files:
    st.info("Выберите один или несколько Excel-файлов.")
    st.stop()

df = load_uploaded_employees(uploaded_files)

if df.empty:
    st.warning("Не удалось считать KPI из выбранных файлов.")
    st.stop()

# =========================
# KPI
# =========================

c1, c2, c3, c4 = st.columns(4)

c1.metric("👥 Сотрудников", len(df))
c2.metric("📈 Средний KPI", f"{df['KPI'].mean():.1f}%")
c3.metric("🏆 Максимум", f"{df['KPI'].max():.1f}%")
c4.metric("📉 Минимум", f"{df['KPI'].min():.1f}%")

st.divider()

# =========================
# Диаграммы
# =========================

stats = df["Категория"].value_counts()

pie_df = stats.reset_index()
pie_df.columns = ["Категория", "Количество"]

col1, col2 = st.columns(2)

with col1:

    pie = px.pie(
        pie_df,
        names="Категория",
        values="Количество",
        hole=0.55
    )

    pie.update_traces(
        textposition="inside",
        textinfo="percent+label"
    )

    st.plotly_chart(
        pie,
        use_container_width=True
    )

with col2:

    bar = px.bar(
        pie_df,
        x="Категория",
        y="Количество",
        text_auto=True
    )

    st.plotly_chart(
        bar,
        use_container_width=True
    )

st.divider()

# =========================
# Фильтр
# =========================

category = st.selectbox(
    "Выберите категорию",
    [
        "Все",
        "🟢 75–100",
        "🟡 50–74",
        "🟠 20–49",
        "🔴 0–19"
    ]
)

filtered_df = df.copy()

if category != "Все":
    filtered_df = filtered_df[
        filtered_df["Категория"] == category
    ]

search = st.text_input("🔍 Поиск сотрудника")

if search:
    filtered_df = filtered_df[
        filtered_df["Сотрудник"].str.contains(
            search,
            case=False,
            na=False
        )
    ]

filtered_df = filtered_df.sort_values(
    "KPI",
    ascending=False
)

st.dataframe(
    filtered_df.style.background_gradient(
        subset=["KPI"],
        cmap="RdYlGn"
    ),
    use_container_width=True,
    hide_index=True
)
