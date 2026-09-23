import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.dataset import parse_dataset
from services.recommendations import candidates, hr_summary, readiness, recommend
from services.store import ROOT, Store


class CareerQuestTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "test.sqlite3"
        self.store = Store(self.path)
        self.employee = self.store.authenticate("employee1", "Quest2026!", "employee")
        self.hr = self.store.authenticate("hr", "HrQuest2026!", "hr")

    def tearDown(self):
        self.directory.cleanup()

    def test_roles_and_sessions(self):
        self.assertIsNone(self.store.authenticate("employee1", "Quest2026!", "hr"))
        self.assertIsNone(self.store.authenticate("hr", "wrong", "hr"))
        for token in (None, "forged", self.employee):
            with self.assertRaises(PermissionError):
                self.store.hr_data(token)
        with self.assertRaises(PermissionError):
            self.store.employee_data(self.employee, "employee2")
        with self.assertRaises(PermissionError):
            self.store.import_dataset(self.employee, b"{}")
        with self.assertRaises(PermissionError):
            self.store.activity_action(self.hr, "design_mentor", "start")
        self.store.logout(self.employee)
        with self.assertRaises(PermissionError):
            self.store.employee_data(self.employee)

    def test_recommendation_not_minimum_skill(self):
        p, a, h = self.store.employee_data(self.employee)
        self.assertEqual(min(p["skills"], key=p["skills"].get), "Public Speaking")
        ranked = candidates(p, a, h)
        self.assertEqual(ranked[0]["activity"]["id"], "design_mentor")
        self.assertEqual(len(ranked[0]["factors"]), 4)
        self.assertNotIn("python", [r["activity"]["id"] for r in ranked])
        # Same profile/grade: changing history alone changes the chosen format.
        changed = h + [{"employee_id": p["id"], "activity_id": "design_mentor", "status": "missed"}] * 3
        self.assertEqual(candidates(p, a, changed)[0]["activity"]["id"], "design_workshop")

    def test_prerequisites_and_no_matching_step(self):
        p, a, h = self.store.employee_data(self.hr, "employee2")
        ids = [r["activity"]["id"] for r in candidates(p, a, h)]
        self.assertEqual(ids[0], "sql_basics")
        self.assertNotIn("advanced_sql", ids)
        self.assertNotIn("timesheets", ids)
        p, a, h = self.store.employee_data(self.hr, "employee3")
        self.assertEqual(candidates(p, a, h), [])
        _, missing, _ = hr_summary(self.store.hr_data(self.hr))
        self.assertEqual(len(missing), 1)

    def test_completion_persistence_and_no_double_xp(self):
        before, _, _ = self.store.employee_data(self.employee)
        today = date(2026, 9, 23)
        self.store.activity_action(self.employee, "design_mentor", "start", today)
        self.store.activity_action(self.employee, "design_mentor", "complete", today)
        reopened = Store(self.path)
        after, _, history = reopened.employee_data(self.employee)
        self.assertEqual(after["skills"]["System Design"], 65)
        self.assertGreater(readiness(after), readiness(before))
        self.assertEqual(sum(h["xp"] for h in history), 180)
        with self.assertRaises(ValueError):
            reopened.activity_action(self.employee, "design_mentor", "complete")
        self.assertEqual(sum(h["xp"] for h in reopened.employee_data(self.employee)[2]), 180)
        _, _, participation = hr_summary(reopened.hr_data(self.hr))
        row = next(r for r in participation if r["Активность"] == "Спроектируй сервис вместе с наставником")
        self.assertEqual(row["Выполнено"], 1)
        self.assertEqual(row["В работе"], 0)

    def test_pause_decline_and_late_completion(self):
        before = self.store.employee_data(self.employee)[0]
        self.store.activity_action(self.employee, "design_mentor", "decline")
        p, a, h = self.store.employee_data(self.employee)
        self.assertEqual(before["skills"], p["skills"])
        self.assertNotIn("design_mentor", [r["activity"]["id"] for r in candidates(p, a, h)])
        self.store.set_participation(self.employee, False)
        p, a, h = self.store.employee_data(self.employee)
        self.assertEqual(candidates(p, a, h), [])
        with self.assertRaises(ValueError):
            self.store.activity_action(self.employee, "design_workshop", "start")
        self.store.set_participation(self.employee, True)
        today = date.today()
        self.store.activity_action(self.employee, "design_workshop", "start", today)
        self.store.activity_action(self.employee, "design_workshop", "complete", today + timedelta(days=20))
        self.assertEqual(sum(h["xp"] for h in self.store.employee_data(self.employee)[2]), 120)

    def test_import_is_atomic_and_new_accounts_work(self):
        raw = (ROOT / "data/jury-example.json").read_bytes()
        invalid = json.loads(raw)
        invalid["history"][0]["employee_id"] = "unknown"
        with self.assertRaises(ValueError):
            self.store.import_dataset(self.hr, json.dumps(invalid).encode())
        self.assertEqual(len(self.store.hr_data(self.hr)["employees"]), 3)
        accounts = self.store.import_dataset(self.hr, raw)
        self.assertEqual(len(self.store.hr_data(self.hr)["employees"]), 6)
        account = accounts[0]
        token = self.store.authenticate(account["Логин"], account["Пароль"], "employee")
        self.assertEqual(self.store.employee_data(token)[0]["id"], "judge1")
        with self.assertRaises(ValueError):
            self.store.import_dataset(self.hr, raw)
        self.assertEqual(len(self.store.hr_data(self.hr)["employees"]), 6)
        for bad in (b'{"synthetic":false}', b"not json", b"x" * 2_000_001):
            with self.assertRaises(ValueError):
                parse_dataset(bad)

    def test_ai_constraints_and_safe_fallback(self):
        p, a, h = self.store.employee_data(self.employee)
        client = Mock()
        with patch.dict(os.environ, {"ALLOW_EXTERNAL_AI": "true", "OPENAI_API_KEY": "test-only"}):
            client.responses.create.return_value = SimpleNamespace(output_text='{"activity_ids":["design_mentor"]}')
            response = recommend(p, a, h, use_ai=True, client=client)
            self.assertIn("OpenAI", response["source"])
            self.assertFalse(client.responses.create.call_args.kwargs["store"])
            self.assertNotIn(p["name"], client.responses.create.call_args.kwargs["input"])
            for invalid in ('{"activity_ids":["unknown"]}', '{"activity_ids":["speaking"]}', '{"activity_ids":[]}'):
                client.responses.create.return_value = SimpleNamespace(output_text=invalid)
                response = recommend(p, a, h, use_ai=True, client=client)
                self.assertIn("без AI", response["source"])
                self.assertTrue(response["notice"])
            client.responses.create.side_effect = TimeoutError("secret details")
            self.assertNotIn("secret", recommend(p, a, h, True, client)["notice"])


class InterfaceTests(unittest.TestCase):
    def test_login_employee_hr_logout_and_progress(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"CAREER_QUEST_DB": str(Path(folder) / "ui.sqlite3")}):
            at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
            self.assertFalse(at.exception)
            at.text_input[0].set_value("employee1")
            at.text_input[1].set_value("Quest2026!")
            next(b for b in at.button if b.label == "Войти").click().run()
            self.assertFalse(at.exception)
            self.assertFalse(at.selectbox)
            at.button(key="start_design_mentor").click().run()
            self.assertFalse(at.exception)
            at.button(key="complete_design_mentor").click().run()
            self.assertFalse(at.exception)
            self.assertIn("180 XP", [m.value for m in at.metric])
            at.button(key="logout").click().run()
            self.assertFalse(at.exception)
            self.assertFalse(at.metric)
            at.session_state["login_role"] = "HR"
            at.run()
            at.text_input[0].set_value("hr")
            at.text_input[1].set_value("HrQuest2026!")
            next(b for b in at.button if b.label == "Войти").click().run()
            self.assertFalse(at.exception)
            self.assertTrue(at.selectbox)
            at.selectbox(key="hr_profile").select("employee3").run()
            self.assertFalse(at.exception)
            self.assertTrue(any("Нет подходящего шага" in i.value for i in at.info))
            self.assertFalse(any(b.key and b.key.startswith("start_") for b in at.button))


if __name__ == "__main__":
    unittest.main()
