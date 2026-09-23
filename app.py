"""Career Quest: synthetic-data hackathon application."""
import hashlib
import json
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from services.dataset import Dataset
from services.recommendations import hr_summary, no_step_reason, readiness, recommend
from services.store import ROOT, Store

load_dotenv(ROOT / ".env")
st.set_page_config(page_title="Career Quest", page_icon="🌿", layout="wide")
STATUS = {"completed": "Выполнено", "started": "В работе", "missed": "Пропущено", "declined": "Отказ"}


@st.cache_resource
def get_store(path):
    return Store(path)


def logout(store):
    if st.session_state.get("token"):
        store.logout(st.session_state.token)
    st.session_state.clear()
    st.rerun()


def login(store):
    st.caption("CAREER QUEST / ПЕРСОНАЛЬНОЕ РАЗВИТИЕ")
    intro, form = st.columns([1.3, 1], gap="large")
    with intro:
        st.title("Твой следующий шаг.\nТвоя новая высота.")
        st.markdown("Развитие начинается с понятной цели. Собери свой маршрут, укрепляй навыки и замечай каждый шаг вперёд.")
        with st.container(border=True):
            st.subheader("От интереса — к новому грейду", icon=":material/route:")
            st.markdown("**01 · Узнай свою точку роста**\n\nПрофиль, навыки и требования следующего уровня.")
            st.markdown("**02 · Выбери подходящий шаг**\n\nРекомендация учитывает твой опыт и предпочтения.")
            st.markdown("**03 · Увидь результат**\n\nНовые навыки, личные достижения и XP.")
        st.caption("Участие добровольное. Здесь нет публичных рейтингов сотрудников.")
    with form:
        with st.container(border=True):
            st.subheader("Добро пожаловать")
            st.caption("Войди в свой кабинет")
            role = st.segmented_control("Я вхожу как", ["Сотрудник", "HR"], default="Сотрудник", key="login_role")
            with st.form("login", clear_on_submit=True):
                username = st.text_input("Логин", placeholder="employee1 или hr", max_chars=100)
                password = st.text_input("Пароль", type="password", max_chars=200)
                submitted = st.form_submit_button("Войти", type="primary", width="stretch")
            if submitted:
                token = store.authenticate(username, password, "hr" if role == "HR" else "employee")
                if token:
                    st.session_state.clear()
                    st.session_state.token = token
                    st.rerun()
                st.error("Неверный логин, пароль или роль. После пяти неудачных попыток подождите минуту.")
            st.caption("Хакатон-демо · только синтетические профили")
        with st.expander("Доступы для демонстрации"):
            st.text("Сотрудник: employee1, employee2 или employee3\nПароль: Quest2026!\n\nHR: hr\nПароль: HrQuest2026!")
            st.caption("Это публичное демо. Для корпоративной среды требуется SSO и отключение демо-аккаунтов.")


def do_action(store, token, activity_id, action):
    try:
        st.session_state.flash = store.activity_action(token, activity_id, action)
        st.session_state.pop("recommendation", None)
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))


def profile_header(p):
    st.title(p["name"])
    st.text(f"{p['role']} · стаж {p['tenure_months']} мес.")
    with st.container(border=True):
        st.subheader(f"{p['grade']} → {p['next_grade']}", icon=":material/route:")
        st.progress(readiness(p) / 100, text=f"Готовность по навыкам: {readiness(p)}%")
        st.caption("Это оценка освоения навыков, а не автоматическое повышение в должности.")
        with st.expander("Как рассчитана траектория"):
            st.markdown("Готовность = 100 × сумма **min(уровень / цель, 1) × вес** / сумма весов. "
                        "Веса задаются требованиями следующего грейда. XP не влияет на этот показатель.")
            st.caption("Выполнение — самоотчёт в демо. В рабочем продукте результат должен подтверждаться оценкой или наставником.")


def skill_map(p):
    st.subheader("Карта навыков")
    for skill, value in p["skills"].items():
        req = p["requirements"].get(skill)
        with st.container(border=True):
            st.text(skill + (" · ключевой для перехода" if req and req["critical"] else ""))
            st.progress(value / 100, text=f"{value}/100" + (f" · цель {req['target']} · разрыв {max(0, req['target'] - value)} п.п. · вес {req['weight']}" if req else " · вне требований грейда"))


def history_table(activities, history):
    st.subheader("История участия")
    names = {a["id"]: a["title"] for a in activities}
    if not history:
        st.info("История пока пуста. Первый шаг можно выбрать в рекомендациях.")
        return
    st.dataframe(pd.DataFrame([{"Активность": names[h["activity_id"]], "Статус": STATUS[h["status"]],
        "Дата": h["date"], "Дедлайн": h["due_date"] or "—"} for h in history]).sort_values("Дата", ascending=False), hide_index=True)


def recommendation_cards(p, activities, history, store, token, readonly=False):
    st.subheader("Следующие шаги", icon=":material/explore:")
    fingerprint = hashlib.sha256(json.dumps([p, activities, history], sort_keys=True).encode()).hexdigest()
    response = recommend(p, activities, history)
    cached = st.session_state.get("recommendation")
    if cached and cached[0] == fingerprint:
        response = cached[1]
    if not readonly and p["opted_in"] and response["items"]:
        with st.expander("Подобрать с AI"):
            st.caption("При запросе в OpenAI передаются синтетические навыки, грейды и сводка истории. Имя и логин не передаются. По умолчанию внешние запросы отключены.")
            consent = st.checkbox("Разрешаю отправить эти синтетические данные в OpenAI", key="ai_consent")
            if st.button("Получить AI-рекомендации", disabled=not consent, key="ai_request"):
                with st.spinner("Сопоставляем цель, навыки и опыт…"):
                    response = recommend(p, activities, history, use_ai=True)
                st.session_state.recommendation = (fingerprint, response)
    st.caption(response["source"])
    if response["notice"]:
        st.info(response["notice"])
    if not response["items"]:
        st.info(no_step_reason(p, activities, history))
    for i, r in enumerate(response["items"], 1):
        a = r["activity"]
        with st.container(border=True):
            st.caption(f"ШАГ {i:02d} · {a['format']} · {a['minutes']} мин.")
            st.subheader(a["title"])
            st.text(f"+{a['xp']} XP · +20% XP в срок · {a['due_days']} дней после начала")
            st.markdown("**Почему этот шаг подходит**")
            for factor in r["factors"]:
                st.text(factor)
            with st.expander("Расчёт приоритета"):
                st.text(r["calculation"])
                st.caption("Доступные шаги по критичным разрывам идут первыми. Внутри группы учитываются прирост, формат и история. Это оценка активности, не рейтинг человека.")
            if not readonly:
                with st.container(horizontal=True):
                    if st.button("Начать", key=f"start_{a['id']}", type="primary"):
                        do_action(store, token, a["id"], "start")
                    if st.button("Не подходит", key=f"decline_{a['id']}"):
                        do_action(store, token, a["id"], "decline")


def employee_view(store, token):
    p, activities, history = store.employee_data(token)
    profile_header(p)
    xp = sum(h["xp"] for h in history if h["status"] == "completed")
    completed = sum(h["status"] == "completed" for h in history)
    with st.container(horizontal=True):
        st.metric("Личный уровень", 1 + xp // 300, border=True)
        st.metric("Опыт развития", f"{xp} XP", border=True)
        st.metric("Завершено шагов", completed, border=True)
    st.progress((xp % 300) / 300, text=f"До следующего уровня: {300 - xp % 300} XP")
    if completed:
        st.badge("Первый шаг" if completed < 3 else "Исследователь", icon=":material/workspace_premium:", color="green")
    enabled = st.toggle("Участвовать в программе развития", value=p["opted_in"], key="participation")
    if enabled != p["opted_in"]:
        store.set_participation(token, enabled)
        st.session_state.pop("recommendation", None)
        st.rerun()
    st.caption("Можно поставить участие на паузу или отказаться от шага. Прогресс и XP сохраняются. История видна только тебе и HR.")
    route, skills, journal = st.tabs(["Мой маршрут", "Навыки и цель", "История"])
    with route:
        active = [h for h in history if h["status"] == "started"]
        if active:
            st.subheader("В работе")
        by_id = {a["id"]: a for a in activities}
        for h in active:
            a = by_id[h["activity_id"]]
            with st.container(border=True):
                st.subheader(a["title"])
                st.text(f"Срок: {h['due_date'] or 'не задан'}")
                st.caption("Прирост при выполнении: " + ", ".join(f"{s} +{v} п.п. (до 100)" for s, v in a["gains"].items()))
                with st.container(horizontal=True):
                    if st.button("Отметить выполненной", type="primary", key=f"complete_{a['id']}", disabled=not enabled):
                        do_action(store, token, a["id"], "complete")
                    if st.button("Отказаться", key=f"cancel_{a['id']}", disabled=not enabled):
                        do_action(store, token, a["id"], "decline")
        recommendation_cards(p, activities, history, store, token)
    with skills:
        skill_map(p)
    with journal:
        history_table(activities, history)


def import_view(store, token):
    st.subheader("Проверочные профили жюри")
    st.caption("JSON до 2 МБ: профили, требования грейда, каталог активностей и история. Только синтетические данные. Импорт добавляет новые профили.")
    with st.container(horizontal=True):
        st.download_button("Пример датасета", (ROOT / "data/jury-example.json").read_bytes(), "jury-example.json", "application/json")
        st.download_button("JSON Schema", json.dumps(Dataset.model_json_schema(), ensure_ascii=False, indent=2), "dataset.schema.json", "application/json")
    with st.form("import"):
        upload = st.file_uploader("Датасет JSON", type=["json"], max_upload_size=2)
        synthetic = st.checkbox("Подтверждаю: все профили вымышлены и не содержат реальных персональных данных")
        submitted = st.form_submit_button("Проверить и загрузить", type="primary")
    if submitted:
        if not upload or not synthetic:
            st.error("Выберите JSON и подтвердите синтетическое происхождение данных.")
        else:
            try:
                st.session_state.import_credentials = store.import_dataset(token, upload.getvalue())
                st.session_state.flash = "Датасет загружен. Профили доступны в HR-кабинете. Сохраните выданные доступы."
                st.rerun()
            except ValidationError as exc:
                st.error("Датасет не прошёл проверку. Изменения не сохранены.")
                for error in exc.errors()[:8]:
                    st.text(f"{'.'.join(map(str, error['loc']))}: {error['msg']}")
            except (ValueError, UnicodeError) as exc:
                st.error("Импорт отменён: " + str(exc))
    if st.session_state.get("import_credentials"):
        st.success("Созданы личные учётные записи. Пароли показаны только в этой сессии HR.")
        frame = pd.DataFrame(st.session_state.import_credentials)
        st.dataframe(frame, hide_index=True)
        st.download_button("Сохранить доступы", frame.to_csv(index=False).encode("utf-8-sig"), "demo-accounts.csv", "text/csv")
        if st.button("Скрыть выданные пароли"):
            del st.session_state.import_credentials
            st.rerun()


def hr_view(store, token):
    data = store.hr_data(token)
    st.title("Пульс развития")
    st.caption("HR-кабинет · поддержка сотрудников и планирование обучения")
    gaps, no_steps, participation = hr_summary(data)
    with st.container(horizontal=True):
        st.metric("Профилей", len(data["employees"]), border=True)
        st.metric("Без нового шага", len(no_steps), border=True)
        st.metric("Завершений", sum(r["Выполнено"] for r in participation), border=True)
    overview, profiles, datasets = st.tabs(["Обзор команды", "Профили и траектории", "Загрузка датасета"])
    with overview:
        st.subheader("Где нужна поддержка")
        st.caption("Число сотрудников с уровнем навыка ниже требований их следующего грейда.")
        if gaps:
            st.bar_chart(pd.DataFrame([{"Навык": s, "Сотрудников": n} for s, n in gaps.items()]).set_index("Навык"), color="#087F58")
        else:
            st.success("Разрывов по целевым навыкам нет.")
        st.subheader("Кому пока не предложен новый шаг")
        if no_steps:
            st.dataframe(pd.DataFrame(no_steps), hide_index=True)
        else:
            st.success("Для всех участников есть доступные шаги.")
        st.subheader("Участие по активностям")
        st.caption("Участников — уникальные сотрудники, начавшие или завершившие шаг; пропуски — число событий в истории.")
        st.dataframe(pd.DataFrame(participation), hide_index=True)
    with profiles:
        people = {p["id"]: p for p in data["employees"]}
        selected = st.selectbox("Открыть профиль", list(people), format_func=lambda i: people[i]["name"], key="hr_profile")
        p, activities, history = store.employee_data(token, selected)
        profile_header(p)
        skill_map(p)
        recommendation_cards(p, activities, history, store, token, readonly=True)
        history_table(activities, history)
    with datasets:
        import_view(store, token)


def main():
    store = get_store(os.getenv("CAREER_QUEST_DB", str(ROOT / "data/career_quest.sqlite3")))
    st.session_state.setdefault("token", None)
    if not st.session_state.token:
        login(store)
        return
    try:
        actor = store.identity(st.session_state.token)
        with st.sidebar:
            st.title("🌿 Career Quest")
            st.caption("Твой рост начинается здесь")
            st.divider()
            st.text("HR-кабинет" if actor["role"] == "hr" else "Личный кабинет")
            st.caption(actor["login"])
            if st.button("Обновить данные", icon=":material/refresh:"):
                st.rerun()
            if st.button("Выйти", key="logout", icon=":material/logout:"):
                logout(store)
            st.divider()
            st.caption("Демо для хакатона. Все профили вымышлены.")
        if st.session_state.get("flash"):
            st.success(st.session_state.pop("flash"))
        if actor["role"] == "hr":
            hr_view(store, st.session_state.token)
        else:
            employee_view(store, st.session_state.token)
    except PermissionError:
        st.session_state.clear()
        st.rerun()


if __name__ == "__main__":
    main()
