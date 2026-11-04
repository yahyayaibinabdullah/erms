import pytest

from frontend.webui.api_client import ApiError
from frontend.webui.app import error_message, login_error_message
from frontend.webui.i18n_catalogue import set_active_messages


@pytest.mark.parametrize('detail', ['unknown login', 'incorrect password'])
@pytest.mark.parametrize('language', ['en', 'ar'])
def test_rejected_login_uses_specific_neutral_feedback(detail, language):
    arabic = 'لم تُقبل بيانات تسجيل الدخول. تحقق من اسم الدخول وكلمة المرور ثم حاول مرة أخرى.'
    set_active_messages({'authentication.error.credentials_not_accepted': arabic} if language == 'ar' else {})
    try:
        message = login_error_message(ApiError(401, detail))
        assert message == (arabic if language == 'ar' else 'Your sign-in credentials weren’t accepted. Check your login name and password and try again.')
        assert error_message(ApiError(401, detail)) != message
        assert login_error_message(ApiError(503, 'unavailable')) == error_message(ApiError(503, 'unavailable'))
    finally:
        set_active_messages({})


@pytest.mark.parametrize('language', ['en', 'ar'])
def test_password_cooldown_renders_localized_duration(language):
    key = 'authentication.error.password_attempts_locked'
    arabic = 'محاولات كلمة المرور مقفلة مؤقتاً. حاول مرة أخرى بعد {seconds} ثانية.'
    set_active_messages({key: arabic} if language == 'ar' else {})
    try:
        message = error_message(ApiError(429, {
            'code': 'password_attempts_locked', 'message_key': key,
            'parameters': {'seconds': 120},
        }))
        expected = arabic if language == 'ar' else 'Password attempts are temporarily locked. Try again in {seconds} seconds.'
        assert message == expected.replace('{seconds}', '\u2068120\u2069')
    finally:
        set_active_messages({})
