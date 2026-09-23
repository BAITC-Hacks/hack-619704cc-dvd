import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


st.set_page_config(
    page_title="Career Quest",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data
def demo_data():
    activities = pd.DataFrame([
        {"Активность": "Практикум: клиентский диалог", "Навык": "Клиентоцентричность", "Дедлайн": date.today() + timedelta(days=3), "XP": 180, "Статус": "В процессе", "Тип": "Практика"},
        {"Активность": "Микрокурс: аналитическое мышление", "Навык": "Аналитика", "Дедлайн": date.today() + timedelta(days=8), "XP": 120, "Статус": "Рекомендовано", "Тип": "Обучение"},
        {"Активность": "Shadowing с наставником", "Навык": "Коммуникация", "Дедлайн": date.today() + timedelta(days=14), "XP": 220, "Статус": "Рекомендовано", "Тип": "Наставничество"},
        {"Активность": "Обратная связь по кейсу", "Навык": "Клиентоцентричность", "Дедлайн": date.today() - timedelta(days=2), "XP": 90, "Статус": "Выполнено", "Тип": "Практика"},
    ])
    skills = pd.DataFrame([
        {"Навык": "Клиентоцентричность", "Текущий уровень": 72, "Цель": 85, "Цвет": "#159447"},
        {"Навык": "Коммуникация", "Текущий уровень": 64, "Цель": 80, "Цвет": "#2FAE68"},
        {"Навык": "Аналитика", "Текущий уровень": 48, "Цель": 75, "Цвет": "#F3A847"},
        {"Навык": "Инициативность", "Текущий уровень": 81, "Цель": 85, "Цвет": "#0D7540"},
    ])
    return activities, skills


def inject_css():
    st.markdown("""
    <style>
    .stApp { background: #f5faf7; }
    [data-testid="stSidebar"] { background: linear-gradient(180deg,#073b24 0%,#0b5833 100%); }
    [data-testid="stSidebar"] * { color: #f6fff8 !important; }
    .brand { font-size: 1.65rem; font-weight: 800; color: #0b5833; letter-spacing: -.04em; }
    .hero { background: linear-gradient(135deg,#0b5833,#159447); border-radius: 22px; padding: 28px 34px; color: white; box-shadow: 0 14px 35px rgba(7,59,36,.15); }
    .hero h1 { margin: 0 0 8px; font-size: 2.25rem; }
    .hero p { margin: 0; opacity: .87; font-size: 1rem; }
    .metric-card { background: white; border: 1px solid #dcefe3; border-radius: 16px; padding: 18px; min-height: 104px; box-shadow: 0 5px 18px rgba(12,77,43,.05); }
    .metric-label { color: #6c8577; font-size: .82rem; }
    .metric-value { color: #123524; font-size: 1.75rem; font-weight: 800; margin-top: 4px; }
    .metric-note { color: #159447; font-size: .78rem; margin-top: 3px; }
    .section-title { color:#123524; font-size:1.25rem; font-weight:800; margin: 26px 0 12px; }
    .quest-card { background:white; border-radius:18px; border:1px solid #dcefe3; padding:20px; height:100%; }
    .quest-pill { display:inline-block; background:#e8f5ec; color:#0b5833; border-radius:999px; padding:5px 10px; font-size:.76rem; font-weight:700; }
    .quest-card h3 { margin:12px 0 6px; color:#123524; font-size:1.05rem; }
    .quest-card p { color:#547063; font-size:.9rem; line-height:1.45; }
    .reason { border-left: 4px solid #f3a847; background:#fffaf0; border-radius:10px; padding:12px 14px; color:#63491c; }
    .level { color:#f3a847; font-weight:800; }
    div[data-testid="stProgressBar"] > div > div { background: linear-gradient(90deg,#0b5833,#35c878); }
    </style>
    """, unsafe_allow_html=True)


def metric(label, value, note):
    st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div><div class="metric-note">{note}</div></div>', unsafe_allow_html=True)


def render_employee(activities, skills):
    st.markdown('<div class="hero"><h1>Твой маршрут развития 🌿</h1><p>Каждый шаг приближает к следующему грейду. Начни с рекомендации AI — она уже ждёт тебя.</p></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Твой прогресс</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1: metric("Уровень Career Quest", "Практик · 4", "+240 XP до следующего")
    with c2: metric("Общий прогресс", "68%", "+8% за месяц")
    with c3: metric("Серия без просрочек", "12 дней", "Лучший результат 🔥")
    with c4: metric("Бейджи", "7 / 12", "Ещё один уже близко")
    st.markdown('<div class="section-title">Твой уровень</div>', unsafe_allow_html=True)
    st.progress(0.72, text="Практик → Эксперт · 760 / 1000 XP")
    st.markdown("<span class='level'>🔥 Серия 12 дней</span> — выполняй задачи вовремя, чтобы сохранить множитель XP ×1.2", unsafe_allow_html=True)
    st.markdown('<div class="section-title">Следующий лучший шаг</div>', unsafe_allow_html=True)
    left, right = st.columns([1.35, 1])
    with left:
        st.markdown('<div class="quest-card"><span class="quest-pill">AI-рекомендация · 180 XP</span><h3>Практикум: клиентский диалог</h3><p>Разбери сложный диалог с клиентом и получи обратную связь от наставника.</p><div class="reason"><b>Почему сейчас?</b><br>Навык «Клиентоцентричность» отстаёт от цели на 13 п.п. Этот практикум даст быстрый прирост и приблизит тебя к требованиям грейда «Старший специалист».</div></div>', unsafe_allow_html=True)
        if st.button("Начать активность", type="primary", use_container_width=True):
            st.success("Активность добавлена в твой маршрут!")
    with right:
        st.markdown('<div class="quest-card"><span class="quest-pill">До следующего грейда</span><h3>Осталось 3 навыка</h3><p>Твоя готовность к грейду</p>', unsafe_allow_html=True)
        st.progress(0.68)
        st.markdown("**Фокус месяца:** аналитика и клиентский диалог\n\n🎯 Выполнить 2 активности\n\n🏆 Получить бейдж «В ритме»", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Карта навыков</div>', unsafe_allow_html=True)
    for _, row in skills.iterrows():
        col1, col2 = st.columns([1, 3])
        with col1: st.write(f"**{row['Навык']}**\n{row['Текущий уровень']} / {row['Цель']}%")
        with col2: st.progress(min(row['Текущий уровень'] / row['Цель'], 1.0))
    st.markdown('<div class="section-title">Мои активности</div>', unsafe_allow_html=True)
    st.dataframe(activities[["Активность", "Навык", "Дедлайн", "XP", "Статус"]], use_container_width=True, hide_index=True)


def render_hr(activities, skills):
    st.markdown('<div class="hero"><h1>Пульс развития команды</h1><p>Понимайте, где нужна поддержка, и направляйте бюджет туда, где он даст максимальный эффект.</p></div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1: metric("Сотрудников в маршруте", "248", "+14 за месяц")
    with c2: metric("Средний прогресс", "61%", "+6 п.п.")
    with c3: metric("Активности в срок", "84%", "+11 п.п.")
    with c4: metric("Бюджет использован", "68%", "Оптимальный темп")
    st.markdown('<div class="section-title">Дефицитные компетенции</div>', unsafe_allow_html=True)
    chart = skills[["Навык", "Текущий уровень", "Цель"]].copy()
    chart["Дефицит"] = chart["Цель"] - chart["Текущий уровень"]
    st.bar_chart(chart.set_index("Навык")["Дефицит"], color="#159447")
    st.info("AI-сигнал: аналитика — главная зона роста. Рекомендуется запустить практический кейс для операторов и связать его с наставничеством.")
    st.markdown('<div class="section-title">Активности и вовлечённость</div>', unsafe_allow_html=True)
    st.dataframe(activities[["Активность", "Навык", "Тип", "XP", "Статус"]], use_container_width=True, hide_index=True)


def main():
    inject_css()
    activities, skills = demo_data()
    with st.sidebar:
        st.markdown('<div style="font-size:2rem">🌿</div><div style="font-size:1.4rem;font-weight:800">Career Quest</div><div style="opacity:.75;margin-bottom:25px">AI-навигация развития</div>', unsafe_allow_html=True)
        mode = st.radio("Режим просмотра", ["Кабинет сотрудника", "Пульс команды"], label_visibility="collapsed")
        st.divider()
        st.caption("Демо-профиль")
        st.markdown("**Алексей Петров**\n\nСпециалист контакт-центра\n\nСтаж: 2 года 4 месяца")
        st.divider()
        st.caption("Career Quest MVP · 2026")
    st.markdown('<div class="brand">Добро пожаловать, Алексей 👋</div>', unsafe_allow_html=True)
    st.caption("Среда, 23 сентября · персональная подборка обновлена сегодня")
    if mode == "Кабинет сотрудника":
        render_employee(activities, skills)
    else:
        render_hr(activities, skills)


if __name__ == "__main__":
    main()

