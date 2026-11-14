"""Session revocation through the assembled root and a disposable real API."""
import pytest
from nicegui import app, ui
from frontend.webui.assembled.tests.test_application import (
    assembled, disposable_only, login, current_page, drawer_buttons, click_one, eventually, plain,
)
from frontend.webui.assembled.tests.test_security_feature import click, opened
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('current', [False, True])
async def test_session_revocation_refreshes_or_clears_current_identity(assembled, current):
    user = assembled
    await login(user)
    api = user.api_clients[0]
    if not current:
        await api.login('viewer@test.invalid', 'Temporary-Test-Password-123!', user_agent='Phase6F disposable viewer')
    click_one(user, [b for b in drawer_buttons(user) if plain(b) == 'Login sessions'])
    await eventually(lambda: current_page(user) == 'login-sessions' and user.pending_requests == 0)
    if not current:
        with user:
            next(i for i in user.find(ui.input).elements if plain(i) == t('webui.select_login_sessions.input.user_or_client_e41c0521')).value = 'Phase6F disposable viewer'
        click(user, t('webui.select_login_sessions.button.apply_filters_fc2322aa'))
        await eventually(lambda: len([c for c in user.find(ui.card).elements if 'login-session-card' in c.classes]) == 1 and user.pending_requests == 0)
    cards = [c for c in user.find(ui.card).elements if 'login-session-card' in c.classes]
    card = next(c for c in cards if any(isinstance(e, ui.badge) and plain(e) == t('webui.render_session_card.badge.current_session_01ba47c6') for e in c.descendants())) if current else cards[0]
    click_one(user, [b for b in card.descendants() if isinstance(b, ui.button) and b.props.get('icon') == 'logout'])
    dialog = await opened(user)
    click(user, t('webui.confirm_revoke.button.force_sign_out_e02eacd0'), dialog)
    await eventually(lambda: any(r['method'] == 'DELETE' and '/auth/sessions/' in r['path'] for r in user.api_requests) and user.pending_requests == 0)
    if current:
        with user:
            assert app.storage.user.get('session_token') is None
        assert api._session_token is None
        await user.should_see('Continue to wathiq', retries=100)
    else:
        page = await api.login_sessions_page(query='Phase6F disposable viewer')
        assert page['total'] == 1 and page['items'][0]['status'] == 'revoked'
        assert api._session_token
        await eventually(lambda: not any(b.props.get('icon') == 'logout' for c in user.find(ui.card).elements if 'login-session-card' in c.classes for b in c.descendants() if isinstance(b, ui.button)))
    assert not user.api_failures
