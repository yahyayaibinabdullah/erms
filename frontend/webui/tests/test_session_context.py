"""Lifecycle ordering established against the original page before extraction."""
import ast
import asyncio
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from frontend.webui.api_client import ApiError
from frontend.webui.personal_resources import PersonalResourceState
from frontend.webui.tests.account_sources import account_sources


def host():
    tree = ast.parse((Path(__file__).parents[1] / 'app.py').read_text() + '\n' + account_sources())
    names = {'submit_login', 'reset_private_views', 'reset_navigation_session'}
    nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    calls = Mock()
    principal = {'user': {'id': 1}, 'must_change_password': False}
    storage = {'session_token': 'old', 'navigation_trail': [{'page': 'old'}], 'organization_browser_state': {'private': True}}
    api = SimpleNamespace(login=AsyncMock(return_value=(principal, 'new')), logout=AsyncMock(), set_session_token=calls.token)
    h = dict(ApiError=ApiError, api=api, app=SimpleNamespace(storage=SimpleNamespace(user=storage)),
             personal=PersonalResourceState(recent_scope=(1, 'old', 'en'),
                                            recent_activity={'records': [{'entity_id': 8}]}),
             context=SimpleNamespace(client=SimpleNamespace(request=SimpleNamespace(headers={'user-agent': 'fixture-browser'}))),
             login_email=SimpleNamespace(value='person@test.invalid'), login_password=SimpleNamespace(value='test-secret'),
             login_error=SimpleNamespace(text='old'), login_error_message=str,
             clear_global_search_session=calls.search, clear_dashboard_session=calls.dashboard,
             clear_translation_inspector_session=AsyncMock(), navigation_controller=SimpleNamespace(trail=[{'page': 'old'}]),
             login_dialog=SimpleNamespace(close=calls.close_login, open=calls.open_login),
             auth_state={'principal': None}, drawer=SimpleNamespace(hide=calls.hide_drawer), table_container=nullcontext(),
             show_change_password=AsyncMock(), prepare_authenticated_workspace=AsyncMock(return_value=True),
             select_dashboard=AsyncMock(), user_menu=SimpleNamespace(close=calls.close_menu),
             clear_signed_in_identity=calls.clear_identity, set_connection_status=calls.connection,
             calls=calls, storage=storage, principal=principal)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<existing lifecycle>', 'exec'), h)
    from frontend.webui.session_context import SessionContext
    h['session'] = SessionContext(
        api=api, storage=lambda: h['app'].storage.user, locale=lambda: {},
        reset_private_views=h['reset_private_views'], reset_navigation=h['reset_navigation_session'],
        clear_identity=h['clear_signed_in_identity'], close_menu=h['user_menu'].close,
        open_login=h['login_dialog'].open, set_connection_status=h['set_connection_status'],
    )
    h['set_principal'] = h['session'].set_principal
    h['sign_out'] = h['session'].sign_out
    h['handle_unauthorized'] = h['session'].handle_unauthorized
    return h


@pytest.mark.parametrize('forced', [False, True])
async def test_login_clears_private_state_and_stores_token_before_workspace(forced):
    h = host(); h['principal']['must_change_password'] = forced
    async def prepared(principal):
        assert h['storage']['session_token'] == 'new'
        assert 'navigation_trail' not in h['storage']
        assert h['navigation_controller'].trail == []
        assert h['login_password'].value == ''
        h['clear_translation_inspector_session'].assert_awaited_once()
        return True
    h['prepare_authenticated_workspace'].side_effect = prepared
    await h['submit_login']()
    h['api'].login.assert_awaited_once_with('person@test.invalid', 'test-secret', user_agent='fixture-browser')
    assert h['login_error'].text == ''
    assert h['storage']['session_token'] == 'new'
    h['calls'].token.assert_called_once_with('new')
    h['calls'].search.assert_called_once(); h['calls'].dashboard.assert_called_once()
    assert h['personal'].recent_scope is None and not h['personal'].recent_activity
    if forced:
        assert h['session'].principal is h['principal']
        h['show_change_password'].assert_awaited_once()
        h['prepare_authenticated_workspace'].assert_not_awaited()
        h['select_dashboard'].assert_not_awaited()
    else:
        h['prepare_authenticated_workspace'].assert_awaited_once_with(h['principal'])
        h['select_dashboard'].assert_awaited_once()
        h['show_change_password'].assert_not_awaited()


async def test_failed_login_retains_existing_state_and_reports_error():
    h = host(); h['api'].login.side_effect = ApiError(401, 'bad credentials')
    await h['submit_login']()
    assert h['login_error'].text
    assert h['storage']['session_token'] == 'old'
    h['calls'].search.assert_not_called(); h['calls'].token.assert_not_called()
    h['calls'].close_login.assert_not_called()


async def test_language_rebuild_does_not_start_an_extra_dashboard():
    h = host(); h['prepare_authenticated_workspace'].return_value = False
    await h['submit_login']()
    h['select_dashboard'].assert_not_awaited()


@pytest.mark.parametrize('failure', [None, ApiError(503, 'offline')])
async def test_logout_cleans_before_waiting_and_clears_storage_even_on_api_error(failure):
    h = host(); started, release = asyncio.Event(), asyncio.Event()
    async def logout():
        started.set(); await release.wait()
        if failure: raise failure
    h['api'].logout.side_effect = logout
    pending = asyncio.create_task(h['sign_out']())
    await started.wait()
    assert [c[0] for c in h['calls'].mock_calls] == ['close_menu', 'clear_identity']
    assert h['storage']['session_token'] == 'old'
    release.set(); await pending
    assert 'session_token' not in h['storage'] and 'organization_browser_state' not in h['storage']
    h['calls'].token.assert_called_once_with(None); h['calls'].open_login.assert_called_once()


@pytest.mark.parametrize('missing_context', [False, True])
def test_unauthorized_cleans_identity_even_without_storage_request_context(missing_context):
    h = host()
    if missing_context:
        class Storage:
            @property
            def user(self): raise RuntimeError('no request context')
        h['app'].storage = Storage()
    h['handle_unauthorized']()
    assert [c[0] for c in h['calls'].mock_calls] == ['token', 'clear_identity', 'connection', 'open_login']
    h['calls'].token.assert_called_once_with(None)
    h['calls'].connection.assert_called_once_with(True)
    if not missing_context: assert 'session_token' not in h['storage']


def test_context_identity_is_per_client_and_locale_follows_its_existing_owner():
    first, second = host(), host()
    first['session'].set_principal(first['principal'])
    assert first['session'].principal is first['principal']
    assert second['session'].principal is None
    assert first['session'].api is first['api']
    assert second['session'].api is not first['session'].api
    locale = {'effective_language': 'en'}
    first['session']._locale = lambda: locale
    assert first['session'].locale is locale
    locale['effective_language'] = 'ar'
    assert first['session'].locale['effective_language'] == 'ar'
