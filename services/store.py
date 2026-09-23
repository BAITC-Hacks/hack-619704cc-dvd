"""Transactional local store with server-side role checks on every public operation."""
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from services.dataset import parse_dataset
from services.recommendations import candidates

ROOT = Path(__file__).resolve().parents[1]


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 260_000).hex()


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    login TEXT PRIMARY KEY, salt TEXT NOT NULL, digest TEXT NOT NULL,
                    role TEXT NOT NULL, employee_id TEXT, failures INTEGER DEFAULT 0,
                    locked_until REAL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, login TEXT, expires REAL);
                CREATE TABLE IF NOT EXISTS dataset (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
            """)
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM dataset").fetchone():
                data = parse_dataset((ROOT / "data/demo.json").read_bytes())
                self._save(db, data)
                self._add_user(db, "hr", "HrQuest2026!", "hr", None)
                for p in data["employees"]:
                    self._add_user(db, p["id"], "Quest2026!", "employee", p["id"])

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _add_user(db, login, password, role, employee_id):
        salt = secrets.token_hex(16)
        db.execute("INSERT INTO users(login,salt,digest,role,employee_id) VALUES(?,?,?,?,?)",
                   (login, salt, password_hash(password, salt), role, employee_id))

    @staticmethod
    def _read(db):
        return json.loads(db.execute("SELECT body FROM dataset WHERE id=1").fetchone()[0])

    @staticmethod
    def _save(db, data):
        db.execute("INSERT OR REPLACE INTO dataset VALUES(1,?)", (json.dumps(data, ensure_ascii=False),))

    @staticmethod
    def _actor(db, token, role=None):
        digest = hashlib.sha256((token or "").encode()).hexdigest()
        user = db.execute("SELECT u.login,u.role,u.employee_id FROM sessions s JOIN users u ON u.login=s.login WHERE s.digest=? AND s.expires>?",
                          (digest, time.time())).fetchone()
        if not user or (role and user["role"] != role):
            raise PermissionError("Нет доступа или сессия истекла. Войдите снова.")
        return dict(user)

    def authenticate(self, login, password, role):
        login = login.strip()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            user = db.execute("SELECT * FROM users WHERE login=?", (login,)).fetchone()
            if not user:
                password_hash(password, "00" * 16)
                return None
            if user["locked_until"] > time.time():
                return None
            valid = hmac.compare_digest(password_hash(password, user["salt"]), user["digest"])
            if not valid or role != user["role"]:
                failures = user["failures"] + 1
                db.execute("UPDATE users SET failures=?, locked_until=? WHERE login=?",
                           (failures, time.time() + 60 if failures >= 5 else 0, login))
                return None
            db.execute("UPDATE users SET failures=0,locked_until=0 WHERE login=?", (login,))
            db.execute("DELETE FROM sessions WHERE expires<=?", (time.time(),))
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), login, time.time() + 8 * 3600))
            return token

    def identity(self, token):
        with self.connection() as db:
            return self._actor(db, token)

    def logout(self, token):
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE digest=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def employee_data(self, token, employee_id=None):
        with self.connection() as db:
            actor = self._actor(db, token)
            target = employee_id or actor["employee_id"]
            if actor["role"] != "hr" and target != actor["employee_id"]:
                raise PermissionError("Доступен только собственный профиль")
            data = self._read(db)
            p = next((p for p in data["employees"] if p["id"] == target), None)
            if not p:
                raise ValueError("Профиль не найден")
            return p, data["activities"], [h for h in data["history"] if h["employee_id"] == target]

    def hr_data(self, token):
        with self.connection() as db:
            self._actor(db, token, "hr")
            return self._read(db)

    def set_participation(self, token, enabled):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            actor = self._actor(db, token, "employee")
            data = self._read(db)
            next(p for p in data["employees"] if p["id"] == actor["employee_id"])["opted_in"] = bool(enabled)
            self._save(db, data)

    def activity_action(self, token, activity_id, action, today=None):
        if action not in {"start", "complete", "decline"}:
            raise ValueError("Неизвестное действие")
        today = today or date.today()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            actor = self._actor(db, token, "employee")
            data = self._read(db)
            p = next(p for p in data["employees"] if p["id"] == actor["employee_id"])
            a = next((a for a in data["activities"] if a["id"] == activity_id), None)
            if not a or not a["voluntary"] or not p["opted_in"]:
                raise ValueError("Активность недоступна или участие приостановлено")
            own = [h for h in data["history"] if h["employee_id"] == p["id"] and h["activity_id"] == activity_id]
            if any(h["status"] == "completed" for h in own):
                raise ValueError("Активность уже выполнена — повторное начисление невозможно")
            started = next((h for h in own if h["status"] == "started"), None)
            if action == "complete":
                if not started:
                    raise ValueError("Сначала начните активность")
                on_time = bool(started["due_date"]) and today <= date.fromisoformat(started["due_date"])
                points = a["xp"] + (a["xp"] // 5 if on_time else 0)
                for skill, gain in a["gains"].items():
                    p["skills"][skill] = min(100, p["skills"].get(skill, 0) + gain)
                started.update(status="completed", date=today.isoformat(), xp=points)
                message = f"Готово! Навыки обновлены, +{points} XP" + (" (бонус 20% за выполнение в срок)." if on_time else ". Без штрафа за опоздание.")
            else:
                if started:
                    if action == "start":
                        raise ValueError("Активность уже в работе")
                    started.update(status="declined", date=today.isoformat(), xp=0)
                else:
                    allowed = {r["activity"]["id"] for r in candidates(p, data["activities"], data["history"])}
                    if activity_id not in allowed:
                        raise ValueError("Шаг больше не доступен. Обновите рекомендации.")
                    data["history"].append({"employee_id": p["id"], "activity_id": activity_id,
                        "status": "started" if action == "start" else "declined", "date": today.isoformat(),
                        "due_date": (today + timedelta(days=a["due_days"])).isoformat() if action == "start" else None, "xp": 0})
                message = "Активность в маршруте." if action == "start" else "Шаг отклонён. Баллы и навыки сохранены."
            self._save(db, data)
            return message

    def import_dataset(self, token, raw):
        # Authorization before parsing. No credentials or roles can be supplied in a dataset.
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._actor(db, token, "hr")
            incoming = parse_dataset(raw)
            data = self._read(db)
            existing_people = {p["id"] for p in data["employees"]}
            existing_activities = {a["id"]: a for a in data["activities"]}
            if existing_people & {p["id"] for p in incoming["employees"]}:
                raise ValueError("ID профиля уже существует. Импорт добавляет новые профили, не перезаписывает прогресс.")
            for a in incoming["activities"]:
                if a["id"] in existing_activities and a != existing_activities[a["id"]]:
                    raise ValueError("ID активности уже занят другим содержимым")
            if len(data["employees"]) + len(incoming["employees"]) > 200:
                raise ValueError("Лимит демо: 200 профилей")
            credentials = []
            for p in incoming["employees"]:
                login = "employee_" + p["id"]
                password = secrets.token_urlsafe(12)
                self._add_user(db, login, password, "employee", p["id"])
                credentials.append({"Профиль": p["name"], "Логин": login, "Пароль": password})
            data["employees"].extend(incoming["employees"])
            data["activities"].extend(a for a in incoming["activities"] if a["id"] not in existing_activities)
            data["history"].extend(incoming["history"])
            # Validate merged limits and references before committing anything.
            parse_dataset(json.dumps(data).encode())
            self._save(db, data)
            return credentials
