"""Explicit, session-independent translation catalogs; Russian is the source locale."""
import json
from functools import lru_cache
from pathlib import Path

LANGUAGES = {"ru": "Русский", "en": "English", "kk": "Қазақша"}
LANGUAGE_NAMES = {"ru": "Russian", "en": "English", "kk": "Kazakh"}
CATALOG_DIR = Path(__file__).resolve().parents[1] / "locales"


def normalize_locale(locale):
    return locale if isinstance(locale, str) and locale in LANGUAGES else "ru"


@lru_cache(maxsize=3)
def catalog(locale):
    if locale == "ru":
        return {}
    return json.loads((CATALOG_DIR / f"{locale}.json").read_text(encoding="utf-8"))


def translate(message, locale="ru", **values):
    """Translate a known message template, leaving unknown/user-provided text intact."""
    if not isinstance(message, str):
        return message
    locale = normalize_locale(locale)
    translated = catalog(locale).get(message, message)
    if values:
        # Only known labels (ranks, built-in skills) are localized in placeholders.
        values = {key: catalog(locale).get(value, value) if isinstance(value, str) else value
                  for key, value in values.items()}
        return translated.format(**values)
    return translated
