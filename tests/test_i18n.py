import ast
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from string import Formatter
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.assistant import answer_question, local_answer
from services.i18n import LANGUAGES, LANGUAGE_NAMES, catalog, normalize_locale, translate
from services.recommendations import candidates
from services.store import ROOT, Store


class TranslationTests(unittest.TestCase):
    def test_catalog_coverage_and_placeholders(self):
        english, kazakh = catalog("en"), catalog("kk")
        self.assertEqual(set(english), set(kazakh))
        for locale in ("en", "kk"):
            for source, target in catalog(locale).items():
                with self.subTest(locale=locale, source=source):
                    self.assertTrue(target.strip())
                    fields = lambda text: {(name, spec, conversion) for _, name, spec, conversion in Formatter().parse(text) if name is not None}
                    self.assertEqual(fields(source), fields(target))
        for path in [ROOT / "app.py", *ROOT.glob("services/*.py")]:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t" and node.args and isinstance(node.args[0], ast.Constant):
                    message = node.args[0].value
                    if isinstance(message, str) and re.search("[А-Яа-яЁё]", message):
                        self.assertIn(message, english, f"Missing translation in {path.name}")

    def test_unknown_text_and_locale_are_safe(self):
        self.assertEqual(normalize_locale("../../secret"), "ru")
        self.assertEqual(translate("Войти", "unknown"), "Войти")
        for locale in LANGUAGES:
            self.assertEqual(translate("Custom name {not_a_placeholder}", locale), "Custom name {not_a_placeholder}")
            self.assertEqual(translate(42, locale), 42)
        self.assertEqual(translate("До ранга «{v0}»: {v1} XP", "en", v0="Исследователь", v1=600), "600 XP to reach Explorer")

    def test_recommendations_and_assistant_use_selected_language(self):
        data = json.loads((ROOT / "data/demo.json").read_text(encoding="utf-8"))
        profile, activities, history = data["employees"][0], data["activities"], data["history"]
        originals = json.dumps(data, ensure_ascii=False, sort_keys=True)
        questions = {"ru": "Как получить ранг?", "en": "How do I reach the next rank?", "kk": "Келесі дәрежеге қалай жетемін?"}
        for locale in LANGUAGES:
            with self.subTest(locale=locale):
                ranked = candidates(profile, activities, history, locale)
                self.assertEqual(ranked[0]["activity"]["id"], "design_mentor")
                reply = local_answer(questions[locale], profile, activities, history, locale)
                self.assertIn(translate("Новичок", locale), reply)
                self.assertIn("600 XP", reply)
                if locale == "en":
                    self.assertFalse(re.search("[А-Яа-яЁё]", reply + json.dumps(ranked[0]["factors"], ensure_ascii=False)))
                client = Mock()
                client.responses.create.return_value = SimpleNamespace(output_text="test reply")
                with patch.dict(os.environ, {"ALLOW_EXTERNAL_AI": "true", "OPENAI_API_KEY": "test-only"}):
                    response = answer_question(profile, activities, history, questions[locale], consent=True, client=client, locale=locale)
                self.assertEqual(response["text"], "test reply")
                self.assertIn(f"Reply in {LANGUAGE_NAMES[locale]}", client.responses.create.call_args.kwargs["instructions"])
        self.assertEqual(json.dumps(data, ensure_ascii=False, sort_keys=True), originals)


class LanguageInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.env = patch.dict(os.environ, {"CAREER_QUEST_DB": str(Path(self.folder.name) / "ui.sqlite3"),
                                           "ALLOW_EXTERNAL_AI": "false", "OPENAI_API_KEY": ""})
        self.env.start()
        self.addCleanup(self.env.stop)

    def app(self, locale="ru"):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        at.query_params["lang"] = locale
        return at.run()

    def login(self, at, user, password, locale):
        at.text_input[0].set_value(user)
        at.text_input[1].set_value(password)
        next(b for b in at.button if b.label == translate("Войти", locale)).click().run()
        self.assertFalse(at.exception)

    def test_employee_switch_preserves_progress_and_logout_preference(self):
        at = self.app()
        at.segmented_control(key="ui_language").set_value("en").run()
        self.assertFalse(at.exception)
        self.assertEqual(at.query_params["lang"], ["en"])
        self.assertEqual(at.text_input[0].label, "Login")
        self.login(at, "employee1", "Quest2026!", "en")
        token = at.session_state["token"]
        self.assertIn("My path", [tab.label for tab in at.tabs])
        at.button(key="start_design_mentor").click().run()
        at.button(key="complete_design_mentor").click().run()
        self.assertFalse(at.exception)
        self.assertIn("180 XP", [m.value for m in at.metric])
        self.assertTrue(any("Skills updated" in item.value for item in at.success))
        at.segmented_control(key="ui_language").set_value("kk").run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["token"], token)
        self.assertIn("180 XP", [m.value for m in at.metric])
        self.assertIn("Менің бағытым", [tab.label for tab in at.tabs])
        at.button(key="open_assistant").click().run()
        at.chat_input[0].set_value("Келесі дәрежеге қалай жетемін?").run()
        self.assertFalse(at.exception)
        self.assertTrue(any("Ағымдағы дәреже" in item.value for item in at.markdown))
        at.button(key="logout").click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state["ui_language"], "kk")
        self.assertEqual(at.text_input[1].label, "Құпиясөз")
        self.assertFalse(at.metric)
        with self.assertRaises(KeyError):
            at.session_state["chat_employee1_employee1"]

    def test_hr_translated_tables_and_session_isolation(self):
        at = self.app("en")
        at.segmented_control(key="login_role").set_value("HR").run()
        self.login(at, "hr", "HrQuest2026!", "en")
        self.assertIn("Team ranks", [tab.label for tab in at.tabs])
        self.assertTrue(any("Rank" in frame.value.columns for frame in at.dataframe))
        at.selectbox(key="hr_profile").select("employee3").run()
        self.assertTrue(any("No suitable step" in item.value for item in at.info))
        at.segmented_control(key="ui_language").set_value("kk").run()
        self.assertFalse(at.exception)
        self.assertTrue(any("Дәреже" in frame.value.columns for frame in at.dataframe))
        self.assertEqual(at.selectbox(key="hr_profile").value, "employee3")
        other = self.app("ru")
        self.assertEqual(other.text_input[0].label, "Логин")
        self.assertEqual(at.session_state["ui_language"], "kk")

    def test_query_locale_survives_new_browser_session(self):
        at = self.app("kk")
        self.assertFalse(at.exception)
        self.assertEqual(at.text_input[1].label, "Құпиясөз")
        fresh = self.app("kk")
        self.assertEqual(fresh.text_input[1].label, "Құпиясөз")
        fallback = self.app("invalid")
        self.assertFalse(fallback.exception)
        self.assertEqual(fallback.text_input[1].label, "Пароль")


if __name__ == "__main__":
    unittest.main()
