"""One source of truth for levels, rank thresholds and personal achievements."""
from datetime import date
from functools import partial
from services.i18n import translate

XP_PER_LEVEL = 300
RANKS = (
    {"id": "novice", "name": "Новичок", "level": 1, "icon": "🌱", "points": 0, "badge": "Начало пути"},
    {"id": "explorer", "name": "Исследователь", "level": 3, "icon": "🧭", "points": 100, "badge": "Открываю новое"},
    {"id": "practitioner", "name": "Практик", "level": 5, "icon": "🛠️", "points": 250, "badge": "От знаний к делу"},
    {"id": "expert", "name": "Эксперт", "level": 8, "icon": "💎", "points": 500, "badge": "Глубина мастерства"},
    {"id": "leader", "name": "Лидер", "level": 12, "icon": "🏆", "points": 1000, "badge": "Вдохновляю рост"},
)


def rank_progress(history):
    xp = sum(h.get("xp", 0) for h in history if h["status"] == "completed")
    level = 1 + xp // XP_PER_LEVEL
    rank = next(r for r in reversed(RANKS) if level >= r["level"])
    next_rank = next((r for r in RANKS if r["level"] > level), None)
    start = (rank["level"] - 1) * XP_PER_LEVEL
    target = (next_rank["level"] - 1) * XP_PER_LEVEL if next_rank else xp
    return {"xp": xp, "level": level, "rank": dict(rank),
            "next_rank": dict(next_rank) if next_rank else None,
            "level_remaining": XP_PER_LEVEL - xp % XP_PER_LEVEL,
            "rank_remaining": target - xp, "rank_fraction": (xp - start) / (target - start) if next_rank else 1.0}


def achievements(profile, history):
    completed = [h for h in history if h["status"] == "completed"]
    current = best = on_time = 0
    # Same-day events follow their stable journal order.
    for h in sorted(history, key=lambda h: h["date"]):
        if h["status"] == "completed":
            if h.get("due_date") and date.fromisoformat(h["date"]) <= date.fromisoformat(h["due_date"]):
                current += 1
                on_time += 1
                best = max(best, current)
            else:
                current = 0
        elif h["status"] == "missed":
            current = 0
    badges = []
    if completed:
        badges.append("Первый шаг")
    if len(completed) >= 3:
        badges.append("В ритме · 3 шага")
    if best >= 3:
        badges.append("Точно в срок · серия 3")
    if any(value == 100 for value in profile["skills"].values()):
        badges.append("Мастер навыка")
    return {"completed": len(completed), "streak": current, "best_streak": best,
            "on_time": on_time, "badges": badges}


def deadline_status(record, today=None, locale="ru"):
    t = partial(translate, locale=locale)
    if not record.get("due_date"):
        return t('Срок не задан')
    days = (date.fromisoformat(record["due_date"]) - (today or date.today())).days
    if days < 0:
        return t('Просрочено на {v0} дн. · базовые XP сохраняются', v0=abs(days))
    if days == 0:
        return t('Срок сегодня · ещё доступен бонус 20%')
    return t('До дедлайна: {v0} дн.', v0=days)
