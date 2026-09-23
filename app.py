"""Career Quest: synthetic-data hackathon application."""
import hashlib
import json
import os
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from pydantic import ValidationError

from services.dataset import Dataset
from services.recommendations import hr_summary, no_step_reason, readiness, recommend
from services.store import ROOT, Store
from services.ai_config import ai_status
from services.progression import RANKS, XP_PER_LEVEL, achievements, deadline_status, rank_progress
from services.i18n import LANGUAGES, normalize_locale, translate

load_dotenv(ROOT / ".env", encoding="utf-8-sig")
st.set_page_config(page_title="Career Quest", page_icon="🌿", layout="wide")
STATUS = {"completed": "Выполнено", "started": "В работе", "missed": "Пропущено", "declined": "Отказ"}


def language():
    return normalize_locale(st.session_state.get("ui_language", st.query_params.get("lang", "ru")))


def t(message, **values):
    return translate(message, language(), **values)


def clear_private_session():
    for key in list(st.session_state):
        if key != "ui_language":
            del st.session_state[key]


def save_language():
    st.session_state.ui_language = normalize_locale(st.session_state.ui_language)
    st.query_params["lang"] = language()
    st.session_state.pop("recommendation", None)


def localized_frame(frame):
    result = frame.copy()
    for column in result.columns:
        if column not in {"Логин", "Пароль"}:
            result[column] = result[column].map(t)
    result.columns = [t(c) for c in result.columns]
    result.index = result.index.map(t)
    result.index.name = t(result.index.name)
    return result


@st.cache_resource
def get_store(path):
    return Store(path)


def logout(store):
    if st.session_state.get("token"):
        store.logout(st.session_state.token)
    clear_private_session()
    st.rerun()


def login(store):
    st.caption(t('CAREER QUEST / ПЕРСОНАЛЬНОЕ РАЗВИТИЕ'))
    intro, form = st.columns([1.3, 1], gap="large")
    with intro:
        st.title(t('Твой следующий шаг.\nТвоя новая высота.'))
        st.markdown(t('Развитие начинается с понятной цели. Собери свой маршрут, укрепляй навыки и замечай каждый шаг вперёд.'))
        with st.container(border=True):
            st.subheader(t('От интереса — к новому грейду'), icon=":material/route:")
            st.markdown(t('**01 · Узнай свою точку роста**\n\nПрофиль, навыки и требования следующего уровня.'))
            st.markdown(t('**02 · Выбери подходящий шаг**\n\nРекомендация учитывает твой опыт и предпочтения.'))
            st.markdown(t('**03 · Увидь результат**\n\nНовые навыки, личные достижения и XP.'))
        st.caption(t('Участие добровольное. Здесь нет публичных рейтингов сотрудников.'))
    with form:
        with st.container(border=True):
            st.subheader(t('Добро пожаловать'))
            st.caption(t('Войди в свой кабинет'))
            role_labels = {role: t(role) for role in ("Сотрудник", "HR")}
            role = st.segmented_control(t('Я вхожу как'), list(role_labels), default="Сотрудник",
                                        key="login_role", format_func=role_labels.get)
            with st.form("login", clear_on_submit=True):
                username = st.text_input(t('Логин'), placeholder=t('employee1 или hr'), max_chars=100)
                password = st.text_input(t('Пароль'), type="password", max_chars=200)
                submitted = st.form_submit_button(t('Войти'), type="primary", width="stretch")
            if submitted:
                token = store.authenticate(username, password, "hr" if role == "HR" else "employee")
                if token:
                    clear_private_session()
                    st.session_state.token = token
                    st.rerun()
                st.error(t('Неверный логин, пароль или роль. После пяти неудачных попыток подождите минуту.'))
            st.caption(t('Хакатон-демо · только синтетические профили'))
        with st.expander(t('Доступы для демонстрации')):
            st.text(t('Сотрудник: employee1, employee2 или employee3\nПароль: Quest2026!\n\nHR: hr\nПароль: HrQuest2026!'))
            st.caption(t('Это публичное демо. Для корпоративной среды требуется SSO и отключение демо-аккаунтов.'))


def do_action(store, token, activity_id, action):
    try:
        st.session_state.flash = store.activity_action(token, activity_id, action, locale=language())
        st.session_state.pop("recommendation", None)
        st.rerun()
    except ValueError as exc:
        st.error(t(str(exc)))


def profile_header(p):
    st.title(t(p['name']))
    st.text(t('{v0} · стаж {v1} мес.', v0=p['role'], v1=p['tenure_months']))
    with st.container(border=True):
        st.subheader(t('{v0} → {v1}', v0=p['grade'], v1=p['next_grade']), icon=":material/route:")
        st.progress(readiness(p) / 100, text=t('Готовность по навыкам: {v0}%', v0=readiness(p)))
        st.caption(t('Это оценка освоения навыков, а не автоматическое повышение в должности.'))
        with st.expander(t('Как рассчитана траектория')):
            st.markdown(t('Готовность = 100 × сумма **min(уровень / цель, 1) × вес** / сумма весов. Веса задаются требованиями следующего грейда. XP не влияет на этот показатель.'))
            st.caption(t('Выполнение — самоотчёт в демо. В рабочем продукте результат должен подтверждаться оценкой или наставником.'))


def skill_map(p):
    st.subheader(t('Карта навыков'))
    for skill, value in p["skills"].items():
        req = p["requirements"].get(skill)
        with st.container(border=True):
            st.text((t(skill) + (t(' · ключевой для перехода') if req and req['critical'] else '')))
            st.progress(value / 100, text=(t('{v0}/100', v0=value) + (t(' · цель {v0} · разрыв {v1} п.п. · вес {v2}', v0=req['target'], v1=max(0, req['target'] - value), v2=req['weight']) if req else t(' · вне требований грейда'))))


def history_table(activities, history):
    st.subheader(t('История участия'))
    names = {a["id"]: a["title"] for a in activities}
    if not history:
        st.info(t('История пока пуста. Первый шаг можно выбрать в рекомендациях.'))
        return
    frame = pd.DataFrame([{"Активность": names[h["activity_id"]], "Статус": STATUS[h["status"]],
        "Дата": h["date"], "Дедлайн": h["due_date"] or "—", "XP": h["xp"]} for h in history]).sort_values("Дата", ascending=False)
    st.dataframe(localized_frame(frame), hide_index=True)
    st.download_button(t('Скачать историю CSV'), localized_frame(frame).to_csv(index=False).encode("utf-8-sig"), "career-history.csv", "text/csv")


def progress_header(p, history):
    progress = rank_progress(history)
    earned = achievements(p, history)
    with st.container(horizontal=True):
        st.metric(t('Личный уровень'), t(progress['level']), border=True)
        st.metric(t('Опыт развития'), t('{v0} XP', v0=progress['xp']), border=True)
        st.metric(t('Завершено шагов'), t(earned['completed']), border=True)
        st.metric(t('Серия в срок'), t(earned['streak']), border=True)
    st.badge(t('{v0} {v1}', v0=progress['rank']['icon'], v1=progress['rank']['name']), color="green")
    st.progress((progress["xp"] % XP_PER_LEVEL) / XP_PER_LEVEL,
                text=t('До следующего уровня: {v0} XP', v0=progress['level_remaining']))
    if progress["next_rank"]:
        st.progress(progress["rank_fraction"], text=t('До ранга «{v0}»: {v1} XP', v0=progress['next_rank']['name'], v1=progress['rank_remaining']))
    else:
        st.success(t('Высший ранг «Лидер» достигнут. Уровни и опыт продолжают расти!'))


def rewards_view(store, token, p, history):
    progress = rank_progress(history)
    rewards = store.reward_history(token, p["id"])
    awarded = {r["rank_id"]: r for r in rewards}
    st.subheader(t('Ранги и награды'), icon=":material/workspace_premium:")
    st.metric(t('Накоплено Quest-баллов'), t(sum((r['points'] for r in rewards))))
    st.caption(t('Награды выдаются автоматически один раз за каждый достигнутый ранг. Quest-баллы — коллекционные баллы демо: они не увеличивают XP и пока не обмениваются на товары или деньги.'))
    rows = []
    for i, rank in enumerate(RANKS):
        reward = awarded.get(rank["id"])
        end = str(RANKS[i + 1]["level"] - 1) if i + 1 < len(RANKS) else "∞"
        rows.append({"Ранг": t("{icon} {name}", icon=rank["icon"], name=rank["name"]), "Уровни": f"{rank['level']}–{end}",
                     "От XP": (rank["level"] - 1) * XP_PER_LEVEL,
                     "Награда": t("{points} Quest-баллов · {badge}", points=rank["points"], badge=rank["badge"]),
                     "Статус": "Текущий" if rank["id"] == progress["rank"]["id"] else ("Достигнут" if reward else "Впереди"),
                     "Выдано": reward["awarded_at"] if reward else "—"})
    st.dataframe(localized_frame(pd.DataFrame(rows)), hide_index=True)
    st.caption(t('Ранг отражает участие в программе развития. Профессиональный грейд и должность определяются отдельно.'))
    earned = achievements(p, history)
    st.subheader(t('Личные достижения'))
    for badge in [r["badge"] for r in rewards] + earned["badges"]:
        st.badge(t(badge), icon=":material/verified:", color="green")
    st.caption(t('Лучшая серия: {v0} · выполнено в срок: {v1}. Серия считает последовательные завершения в срок. Пропуск или завершение без подтверждённого срока прерывает серию; отказ и пауза не уменьшают её.', v0=earned['best_streak'], v1=earned['on_time']))


def ai_setup_view():
    ready, notice = ai_status(language())
    st.caption(((t('🟢 ') if ready else t('⚪ ')) + t(notice)))
    with st.expander(t('Как подключить API-ключ')):
        st.markdown(t('1. Создайте ключ в [OpenAI Platform](https://platform.openai.com/api-keys).\n2. В папке проекта скопируйте `env.example` в `.env`, если файла ещё нет.\n3. Заполните настройки ниже.\n4. Перезапустите сервер: `python run.py`.\n5. Откройте AI-помощника, подтвердите отправку данных и задайте вопрос.'))
        st.code(t('OPENAI_API_KEY=ваш_новый_ключ\nALLOW_EXTERNAL_AI=true\nOPENAI_MODEL=gpt-4o-mini'), language="dotenv")
        st.caption(t('Ключ хранится только на сервере в .env. Не вставляйте его в чат или env.example. Переменные окружения сервера имеют приоритет над .env. Подробности: docs/API_SETUP.md.'))


def close_assistant():
    st.session_state.pop("assistant_profile", None)


@st.dialog(t('AI-помощник Career Quest'), width="large", on_dismiss=close_assistant)
def assistant_dialog(store, token, employee_id=None):
    try:
        p, _, _ = store.employee_data(token, employee_id)
        actor = store.identity(token)
        key = f"chat_{actor['login']}_{p['id']}"
        st.caption(t('Контекст: {v0}. Помощник объясняет навыки, маршрут, ранги и награды.', v0=p['name']))
        ready, notice = ai_status(language())
        st.info(t(notice))
        st.caption(t('В OpenAI будут отправлены навыки, грейды, прогресс и последние 12 сообщений диалога. Имя и логин автоматически не добавляются. Не вводите персональные данные, пароли и ключи. Переписка хранится только в текущей сессии и очищается при выходе.'))
        consent = st.checkbox(t('Разрешаю отправить контекст и сообщения в OpenAI'), key=key + "_consent", disabled=not ready)
        if st.button(t('Очистить диалог'), key=key + "_clear"):
            st.session_state[key] = []
        messages = st.session_state.setdefault(key, [])
        if not messages:
            st.markdown(t('Спросите, например: **Как получить следующий ранг?** · **Какие навыки развивать?** · **Какой следующий шаг?**'))
        transcript = st.container(height=330)
        question = st.chat_input(t('Задайте вопрос о развитии'), max_chars=2000, key=key + "_input")
        if question:
            try:
                with st.spinner(t('Готовлю ответ…')):
                    response = store.ask_assistant(token, question, messages, consent and ready, p["id"], locale=language())
                messages = [*messages, {"role": "user", "content": question},
                            {"role": "assistant", "content": response["text"], "source": response["source"], "notice": response["notice"]}][-24:]
                st.session_state[key] = messages
            except ValueError as exc:
                st.error(t(str(exc)))
        with transcript:
            for message in messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
                    if message.get("source"):
                        st.caption(t(message['source']))
                    if message.get("notice"):
                        st.caption(t(message['notice']))
    except PermissionError:
        clear_private_session()
        st.rerun()


def recommendation_cards(p, activities, history, store, token, readonly=False):
    st.subheader(t('Следующие шаги'), icon=":material/explore:")
    fingerprint = hashlib.sha256(json.dumps([language(), p, activities, history], sort_keys=True).encode()).hexdigest()
    response = recommend(p, activities, history, locale=language())
    cached = st.session_state.get("recommendation")
    if cached and cached[0] == fingerprint:
        response = cached[1]
    if not readonly and p["opted_in"] and response["items"]:
        with st.expander(t('Подобрать с AI')):
            st.caption(t('При запросе в OpenAI передаются синтетические навыки, грейды и сводка истории. Имя и логин не передаются. По умолчанию внешние запросы отключены.'))
            consent = st.checkbox(t('Разрешаю отправить эти синтетические данные в OpenAI'), key="ai_consent")
            if st.button(t('Получить AI-рекомендации'), disabled=not consent, key="ai_request"):
                with st.spinner(t('Сопоставляем цель, навыки и опыт…')):
                    response = recommend(p, activities, history, use_ai=True, locale=language())
                st.session_state.recommendation = (fingerprint, response)
    st.caption(t(response['source']))
    if response["notice"]:
        st.info(t(response['notice']))
    if not response["items"]:
        st.info(t(no_step_reason(p, activities, history, locale=language())))
    for i, r in enumerate(response["items"], 1):
        a = r["activity"]
        with st.container(border=True):
            st.caption(t('ШАГ {v0:02d} · {v1} · {v2} мин.', v0=i, v1=a['format'], v2=a['minutes']))
            st.subheader(t(a['title']))
            st.text(t('+{v0} XP · +20% XP в срок · {v1} дней после начала', v0=a['xp'], v1=a['due_days']))
            st.markdown(t('**Почему этот шаг подходит**'))
            for factor in r["factors"]:
                st.text(t(factor))
            with st.expander(t('Расчёт приоритета')):
                st.text(t(r['calculation']))
                st.caption(t('Доступные шаги по критичным разрывам идут первыми. Внутри группы учитываются прирост, формат и история. Это оценка активности, не рейтинг человека.'))
            if not readonly:
                with st.container(horizontal=True):
                    if st.button(t('Начать'), key=f"start_{a['id']}", type="primary"):
                        do_action(store, token, a["id"], "start")
                    if st.button(t('Не подходит'), key=f"decline_{a['id']}"):
                        do_action(store, token, a["id"], "decline")


def employee_view(store, token):
    p, activities, history = store.employee_data(token)
    profile_header(p)
    progress_header(p, history)
    if st.button(t('Открыть AI-помощника'), icon=":material/chat:", key="open_assistant"):
        st.session_state.assistant_profile = p["id"]
    if st.session_state.get("assistant_profile") == p["id"]:
        assistant_dialog(store, token)
    enabled = st.toggle(t('Участвовать в программе развития'), value=p["opted_in"], key="participation")
    if enabled != p["opted_in"]:
        store.set_participation(token, enabled)
        st.session_state.pop("recommendation", None)
        st.rerun()
    st.caption(t('Можно поставить участие на паузу или отказаться от шага. Прогресс и XP сохраняются. История видна только тебе и HR.'))
    route, skills, rewards, journal = st.tabs([t('Мой маршрут'), t('Навыки и цель'), t('Ранги и награды'), t('История')])
    with route:
        active = sorted([h for h in history if h["status"] == "started"], key=lambda h: h.get("due_date") or "9999-12-31")
        if active:
            st.subheader(t('В работе'))
        by_id = {a["id"]: a for a in activities}
        for h in active:
            a = by_id[h["activity_id"]]
            with st.container(border=True):
                st.subheader(t(a['title']))
                st.text(t('Срок: {v0}', v0=h['due_date'] or 'не задан'))
                st.caption(t(deadline_status(h, locale=language())))
                st.caption((t('Прирост при выполнении: ') + ', '.join((t('{v0} +{v1} п.п. (до 100)', v0=s, v1=v) for s, v in a['gains'].items()))))
                with st.container(horizontal=True):
                    if st.button(t('Отметить выполненной'), type="primary", key=f"complete_{a['id']}", disabled=not enabled):
                        do_action(store, token, a["id"], "complete")
                    if st.button(t('Отказаться'), key=f"cancel_{a['id']}", disabled=not enabled):
                        do_action(store, token, a["id"], "decline")
        recommendation_cards(p, activities, history, store, token)
    with skills:
        skill_map(p)
    with rewards:
        rewards_view(store, token, p, history)
    with journal:
        history_table(activities, history)


def import_view(store, token):
    st.subheader(t('Проверочные профили жюри'))
    st.caption(t('JSON до 2 МБ: профили, требования грейда, каталог активностей и история. Только синтетические данные. Импорт добавляет новые профили.'))
    with st.container(horizontal=True):
        st.download_button(t('Пример датасета'), (ROOT / "data/jury-example.json").read_bytes(), "jury-example.json", "application/json")
        st.download_button(t('JSON Schema'), json.dumps(Dataset.model_json_schema(), ensure_ascii=False, indent=2), "dataset.schema.json", "application/json")
    with st.form("import"):
        upload = st.file_uploader(t('Датасет JSON'), type=["json"], max_upload_size=2)
        synthetic = st.checkbox(t('Подтверждаю: все профили вымышлены и не содержат реальных персональных данных'))
        submitted = st.form_submit_button(t('Проверить и загрузить'), type="primary")
    if submitted:
        if not upload or not synthetic:
            st.error(t('Выберите JSON и подтвердите синтетическое происхождение данных.'))
        else:
            try:
                st.session_state.import_credentials = store.import_dataset(token, upload.getvalue())
                st.session_state.flash = "Датасет загружен. Профили доступны в HR-кабинете. Сохраните выданные доступы."
                st.rerun()
            except ValidationError as exc:
                st.error(t('Датасет не прошёл проверку. Изменения не сохранены.'))
                for error in exc.errors()[:8]:
                    reason = {"missing": "Обязательное поле отсутствует.",
                              "extra_forbidden": "Неизвестное поле.",
                              "literal_error": "Недопустимое значение поля."}.get(
                                  error["type"], "Проверьте тип, формат и допустимый диапазон значения.")
                    st.text(t("{field}: {reason}", field=".".join(map(str, error["loc"])), reason=reason))
            except (ValueError, UnicodeError) as exc:
                st.error((t('Импорт отменён: ') + t(str(exc))))
    if st.session_state.get("import_credentials"):
        st.success(t('Созданы личные учётные записи. Пароли показаны только в этой сессии HR.'))
        frame = pd.DataFrame(st.session_state.import_credentials)
        st.dataframe(localized_frame(frame), hide_index=True)
        st.download_button(t('Сохранить доступы'), localized_frame(frame).to_csv(index=False).encode("utf-8-sig"), "demo-accounts.csv", "text/csv")
        if st.button(t('Скрыть выданные пароли')):
            del st.session_state.import_credentials
            st.rerun()


def hr_view(store, token):
    data = store.hr_data(token)
    st.title(t('Пульс развития'))
    st.caption(t('HR-кабинет · поддержка сотрудников и планирование обучения'))
    gaps, no_steps, participation = hr_summary(data)
    with st.container(horizontal=True):
        st.metric(t('Профилей'), t(len(data['employees'])), border=True)
        st.metric(t('Без нового шага'), t(len(no_steps)), border=True)
        st.metric(t('Завершений'), t(sum((r['Выполнено'] for r in participation))), border=True)
    overview, profiles, ranks, datasets = st.tabs([t('Обзор команды'), t('Профили и траектории'), t('Ранги команды'), t('Загрузка датасета')])
    with overview:
        st.subheader(t('Где нужна поддержка'))
        st.caption(t('Число сотрудников с уровнем навыка ниже требований их следующего грейда.'))
        if gaps:
            st.bar_chart(localized_frame(pd.DataFrame([{"Навык": s, "Сотрудников": n} for s, n in gaps.items()]).set_index("Навык")), color="#087F58")
        else:
            st.success(t('Разрывов по целевым навыкам нет.'))
        st.subheader(t('Кому пока не предложен новый шаг'))
        if no_steps:
            st.dataframe(localized_frame(pd.DataFrame(no_steps)), hide_index=True)
        else:
            st.success(t('Для всех участников есть доступные шаги.'))
        st.subheader(t('Участие по активностям'))
        st.caption(t('Участников — уникальные сотрудники, начавшие или завершившие шаг; пропуски — число событий в истории.'))
        st.dataframe(localized_frame(pd.DataFrame(participation)), hide_index=True)
        st.subheader(t('Просроченные шаги'))
        people = {p["id"]: p["name"] for p in data["employees"]}
        activities = {a["id"]: a["title"] for a in data["activities"]}
        overdue = [{"Сотрудник": people[h["employee_id"]], "Активность": activities[h["activity_id"]],
                    "Дедлайн": h["due_date"]} for h in data["history"]
                   if h["status"] == "started" and h.get("due_date") and date.fromisoformat(h["due_date"]) < date.today()]
        if overdue:
            st.dataframe(localized_frame(pd.DataFrame(overdue).sort_values("Дедлайн")), hide_index=True)
        else:
            st.info(t('Просроченных шагов нет.'))
    with profiles:
        people = {p["id"]: p for p in data["employees"]}
        profile_labels = {identifier: t(profile["name"]) for identifier, profile in people.items()}
        selected = st.selectbox(t('Открыть профиль'), list(people), format_func=profile_labels.get, key="hr_profile")
        p, activities, history = store.employee_data(token, selected)
        profile_header(p)
        progress_header(p, history)
        if st.button(t('Обсудить профиль с AI'), icon=":material/chat:", key="hr_assistant"):
            st.session_state.assistant_profile = selected
        if st.session_state.get("assistant_profile") == selected:
            assistant_dialog(store, token, selected)
        elif st.session_state.get("assistant_profile"):
            close_assistant()
        rewards_view(store, token, p, history)
        skill_map(p)
        recommendation_cards(p, activities, history, store, token, readonly=True)
        history_table(activities, history)
    with ranks:
        st.subheader(t('Распределение по рангам'))
        st.caption(t('Сводка для поддержки развития; сотрудники видят только собственные достижения.'))
        rows = []
        counts = {r["name"]: 0 for r in RANKS}
        for p in data["employees"]:
            own = [h for h in data["history"] if h["employee_id"] == p["id"]]
            progress = rank_progress(own)
            counts[progress["rank"]["name"]] += 1
            rows.append({"Сотрудник": p["name"], "Ранг": progress["rank"]["name"],
                         "Уровень": progress["level"], "XP": progress["xp"],
                         "До следующего ранга, XP": progress["rank_remaining"],
                         "Quest-баллы": sum(r["points"] for r in store.reward_history(token, p["id"]))})
        st.bar_chart(localized_frame(pd.DataFrame({"Сотрудников": counts})), color="#087F58")
        frame = pd.DataFrame(rows)
        st.dataframe(localized_frame(frame), hide_index=True)
        st.download_button(t('Скачать сводку рангов'), localized_frame(frame).to_csv(index=False).encode("utf-8-sig"), "team-ranks.csv", "text/csv")
    with datasets:
        import_view(store, token)


def main():
    st.session_state.setdefault("ui_language", normalize_locale(st.query_params.get("lang", "ru")))
    with st.sidebar:
        st.segmented_control("Язык / Language / Тіл", list(LANGUAGES), key="ui_language",
                             format_func=LANGUAGES.get, on_change=save_language)
    store = get_store(os.getenv("CAREER_QUEST_DB", str(ROOT / "data/career_quest.sqlite3")))
    st.session_state.setdefault("token", None)
    if not st.session_state.token:
        login(store)
        return
    try:
        actor = store.identity(st.session_state.token)
        with st.sidebar:
            st.title(t('🌿 Career Quest'))
            st.caption(t('Твой рост начинается здесь'))
            st.divider()
            st.text((t('HR-кабинет') if actor['role'] == 'hr' else t('Личный кабинет')))
            st.caption(t(actor['login']))
            if st.button(t('Обновить данные'), icon=":material/refresh:"):
                st.rerun()
            if st.button(t('Выйти'), key="logout", icon=":material/logout:"):
                logout(store)
            st.divider()
            ai_setup_view()
            st.caption(t('Демо для хакатона. Все профили вымышлены.'))
        if st.session_state.get("flash"):
            st.success(t(st.session_state.pop('flash')))
        if actor["role"] == "hr":
            hr_view(store, st.session_state.token)
        else:
            employee_view(store, st.session_state.token)
    except PermissionError:
        clear_private_session()
        st.rerun()


if __name__ == "__main__":
    main()
