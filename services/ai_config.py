"""Server-side AI configuration and safe user-facing diagnostics."""
import os
from functools import partial
from services.i18n import translate


def ai_status(locale="ru"):
    t = partial(translate, locale=locale)
    if os.getenv("ALLOW_EXTERNAL_AI", "false").strip().lower() != "true":
        return False, t('Внешний AI отключён. В .env задайте ALLOW_EXTERNAL_AI=true и перезапустите сервер.')
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return False, t('API-ключ не задан. Добавьте OPENAI_API_KEY в .env и перезапустите сервер.')
    return True, t('AI настроен. Соединение проверяется при отправке вопроса или запросе рекомендаций.')


def model_name():
    return os.getenv("OPENAI_MODEL", "").strip() or "gpt-4o-mini"


def error_notice(exc, locale="ru"):
    t = partial(translate, locale=locale)
    # Never include raw errors, request bodies or credentials in the interface.
    status = getattr(exc, "status_code", None)
    if status == 401:
        return t('OpenAI отклонил ключ. Проверьте OPENAI_API_KEY и перезапустите сервер.')
    if status in (403, 404):
        return t('Нет доступа к API или модели. Проверьте проект ключа и OPENAI_MODEL.')
    if status == 429:
        return t('Достигнут лимит OpenAI. Проверьте баланс и лимиты API или повторите позже.')
    return t('AI временно недоступен или вернул пустой ответ. Попробуйте позже.')
