import copy
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.assistant import answer_question
from services.progression import achievements, deadline_status, rank_progress
from services.store import ROOT, Store


class ProgressionTests(unittest.TestCase):
    def test_rank_boundaries_and_unbounded_levels(self):
        for xp, level, rank in [(0, 1, "novice"), (299, 1, "novice"), (300, 2, "novice"),
                                (599, 2, "novice"), (600, 3, "explorer"), (1199, 4, "explorer"),
                                (1200, 5, "practitioner"), (2099, 7, "practitioner"),
                                (2100, 8, "expert"), (3299, 11, "expert"), (3300, 12, "leader"),
                                (9000, 31, "leader")]:
            with self.subTest(xp=xp):
                progress = rank_progress([{"status": "completed", "xp": xp}, {"status": "missed", "xp": 360}])
                self.assertEqual((progress["level"], progress["rank"]["id"]), (level, rank))
                self.assertGreaterEqual(progress["rank_fraction"], 0)
                self.assertLessEqual(progress["rank_fraction"], 1)
                if rank == "leader":
                    self.assertIsNone(progress["next_rank"])
                    self.assertEqual(progress["rank_remaining"], 0)

    def test_streak_deadline_and_voluntary_decline(self):
        history = [{"status": "completed", "date": f"2026-09-{day:02}", "due_date": f"2026-09-{day:02}"} for day in (20, 21, 22)]
        history.append({"status": "declined", "date": "2026-09-23"})
        result = achievements({"skills": {"SQL": 100}}, history)
        self.assertEqual((result["streak"], result["best_streak"], result["on_time"]), (3, 3, 3))
        self.assertIn("Мастер навыка", result["badges"])
        history.append({"status": "completed", "date": "2026-09-24", "due_date": "2026-09-23"})
        result = achievements({"skills": {"SQL": 70}}, history)
        self.assertEqual((result["streak"], result["best_streak"]), (0, 3))
        self.assertIn("сегодня", deadline_status({"due_date": "2026-09-23"}, date(2026, 9, 23)))
        self.assertIn("Просрочено", deadline_status({"due_date": "2026-09-22"}, date(2026, 9, 23)))
        self.assertEqual(deadline_status({}), "Срок не задан")


class StoredFeaturesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "quest.sqlite3"
        self.store = Store(self.path)
        self.employee = self.store.authenticate("employee1", "Quest2026!", "employee")
        self.hr = self.store.authenticate("hr", "HrQuest2026!", "hr")

    def seed_xp(self):
        with self.store.connection() as db:
            data = self.store._read(db)
            next(h for h in data["history"] if h["status"] == "completed")["xp"] = 360
            self.store._save(db, data)

    def test_concurrent_completion_rewards_once_and_persistence(self):
        self.seed_xp()
        self.store.activity_action(self.employee, "design_mentor", "start")
        self.store.activity_action(self.employee, "design_mentor", "complete")
        self.store.activity_action(self.employee, "design_workshop", "start")

        def complete():
            try:
                return self.store.activity_action(self.employee, "design_workshop", "complete")
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: complete(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertIn("Исследователь", next(result for result in results if result))
        reopened = Store(self.path)
        rewards = reopened.reward_history(self.employee)
        self.assertEqual([r["rank_id"] for r in rewards], ["novice", "explorer"])
        self.assertEqual(sum(r["points"] for r in rewards), 100)
        self.assertEqual(rank_progress(reopened.employee_data(self.employee)[2])["xp"], 684)
        reopened.set_participation(self.employee, False)
        self.assertEqual(rewards, reopened.reward_history(self.employee))

    def test_completion_and_rewards_roll_back_together(self):
        self.store.activity_action(self.employee, "design_mentor", "start")
        before = self.store.employee_data(self.employee)
        with patch.object(Store, "_sync_rewards", side_effect=RuntimeError("storage error")):
            with self.assertRaises(RuntimeError):
                self.store.activity_action(self.employee, "design_mentor", "complete")
        self.assertEqual(before, self.store.employee_data(self.employee))

    def test_import_all_crossed_ranks_and_old_database_migration(self):
        data = json.loads((ROOT / "data/demo.json").read_text(encoding="utf-8"))
        person = copy.deepcopy(data["employees"][0])
        person["id"] = "veteran"
        data["employees"] = [person]
        base = data["activities"][0]
        data["activities"] = [dict(base, id=f"past_{i}", xp=300) for i in range(10)]
        data["history"] = [{"employee_id": "veteran", "activity_id": a["id"], "status": "completed",
                            "date": "2026-09-20", "xp": 330} for a in data["activities"]]
        raw = json.dumps(data).encode()
        credentials = self.store.import_dataset(self.hr, raw)
        token = self.store.authenticate(credentials[0]["Логин"], credentials[0]["Пароль"], "employee")
        rewards = self.store.reward_history(token)
        self.assertEqual(len(rewards), 5)
        self.assertEqual(sum(r["points"] for r in rewards), 1850)
        with self.assertRaises(ValueError):
            self.store.import_dataset(self.hr, raw)
        self.assertEqual(rewards, self.store.reward_history(token))
        with self.store.connection() as db:
            db.execute("DROP TABLE rank_rewards")
        migrated = Store(self.path)
        self.assertEqual(len(migrated.reward_history(token)), 5)
        self.assertEqual(rank_progress(migrated.employee_data(token)[2])["xp"], 3300)

    def test_assistant_and_rewards_enforce_roles_and_logout(self):
        with self.assertRaises(PermissionError):
            self.store.reward_history(self.employee, "employee2")
        with self.assertRaises(PermissionError):
            self.store.ask_assistant(self.employee, "Мой ранг?", employee_id="employee2")
        self.assertEqual(len(self.store.reward_history(self.hr, "employee2")), 1)
        reply = self.store.ask_assistant(self.hr, "Мой ранг?", employee_id="employee2")
        self.assertIn("Новичок", reply["text"])
        self.store.logout(self.employee)
        with self.assertRaises(PermissionError):
            self.store.ask_assistant(self.employee, "Мой ранг?")

    def test_offline_consent_validation_and_question_topics(self):
        p, activities, history = self.store.employee_data(self.employee)
        client = Mock()
        with patch.dict(os.environ, {"ALLOW_EXTERNAL_AI": "true", "OPENAI_API_KEY": "test-only"}):
            response = answer_question(p, activities, history, "Как получить ранг?", client=client)
            self.assertIn("600 XP", response["text"])
            client.responses.create.assert_not_called()
        with patch.dict(os.environ, {"ALLOW_EXTERNAL_AI": "false", "OPENAI_API_KEY": "test-only"}):
            for q in ("Мои навыки?", "Следующий шаг?", "Дедлайны?", "Привет"):
                self.assertIn("без AI", answer_question(p, activities, history, q, consent=True, client=client)["source"])
            client.responses.create.assert_not_called()
        for q in ("", "   ", "x" * 2001):
            with self.assertRaises(ValueError):
                answer_question(p, activities, history, q)

    def test_ai_context_history_and_safe_errors(self):
        p, activities, history = self.store.employee_data(self.employee)
        history.append({"employee_id": "employee2", "status": "completed", "xp": 99999})
        messages = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(20)]
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(output_text="Начните с архитектуры.")
        with patch.dict(os.environ, {"ALLOW_EXTERNAL_AI": "true", "OPENAI_API_KEY": "test-only"}):
            response = answer_question(p, activities, history, "Почему?", messages, True, client)
            self.assertIn("OpenAI", response["source"])
            args = client.responses.create.call_args.kwargs
            self.assertFalse(args["store"])
            self.assertEqual(len(args["input"]), 14)
            self.assertEqual(args["input"][-1]["content"], "Почему?")
            payload = json.dumps(args, ensure_ascii=False)
            for private in (p["name"], "employee1", "employee2", "99999", "test-only"):
                self.assertNotIn(private, payload)
            for status, expected in [(401, "отклонил ключ"), (429, "лимит"), (404, "Нет доступа"), (500, "недоступен")]:
                error = RuntimeError("secret request details")
                error.status_code = status
                client.responses.create.side_effect = error
                response = answer_question(p, activities, history, "Мой ранг?", consent=True, client=client)
                self.assertIn(expected, response["notice"])
                self.assertNotIn("secret", response["notice"])
                self.assertIn("без AI", response["source"])
            client.responses.create.side_effect = None
            client.responses.create.return_value = SimpleNamespace(output_text=" ")
            self.assertIn("без AI", answer_question(p, activities, history, "Мой ранг?", consent=True, client=client)["source"])


class NewInterfaceTests(unittest.TestCase):
    def test_rewards_and_offline_chat_dialog(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            "CAREER_QUEST_DB": str(Path(folder) / "ui.sqlite3"), "ALLOW_EXTERNAL_AI": "false", "OPENAI_API_KEY": ""}):
            at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
            at.text_input[0].set_value("employee1")
            at.text_input[1].set_value("Quest2026!")
            next(b for b in at.button if b.label == "Войти").click().run()
            self.assertFalse(at.exception)
            self.assertIn("Ранги и награды", [t.label for t in at.tabs])
            at.button(key="open_assistant").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.chat_input), 1)
            at.chat_input[0].set_value("Как получить следующий ранг?").run()
            self.assertFalse(at.exception)
            self.assertTrue(any("600 XP" in m.value for m in at.markdown),
                            f"Messages: {at.session_state['chat_employee1_employee1']}; chat inputs: {len(at.chat_input)}")
            at.button(key="chat_employee1_employee1_clear").click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state["chat_employee1_employee1"], [])


if __name__ == "__main__":
    unittest.main()
