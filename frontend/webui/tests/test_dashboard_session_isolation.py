"""Exercise dashboard cache ownership and late-response guards without a database."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from frontend.webui.api_client import ApiError

SOURCE = ast.parse((Path(__file__).parents[1] / 'app.py').read_text())


def load(name, scope):
    node = next(n for n in ast.walk(SOURCE)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<dashboard-callback>', 'exec'), scope)
    return scope[name]


def test_dashboard_clear_invalidates_snapshot_and_session_even_for_same_account():
    state = dict(dashboard_summary_cache={'private':'A'}, dashboard_summary_cache_key=('A','en'),
                 dashboard_view_token=object())
    clear = load('clear_dashboard_session', dict(state=state))
    clear()
    assert not {'dashboard_summary_cache','dashboard_summary_cache_key','dashboard_view_token'} & state.keys()
    assert state['dashboard_session_revision'] == 1
    clear()
    assert state['dashboard_session_revision'] == 2


@pytest.mark.parametrize('field,value', [('user',2), ('effective_language','ar'),
                                        ('working_timezone','Asia/Dubai'), ('revision',1),
                                        ('privileges',['record.view']), ('roles',[{'id':12}])])
def test_dashboard_key_is_identity_language_timezone_and_session_scoped(field,value):
    state = {'localization':{'effective_language':'en','working_timezone':'UTC'}}
    auth = {'principal':{'user':{'id':1}}}
    key = load('dashboard_session_key', dict(state=state,auth_state=auth,Any=Any))
    before = key()
    if field == 'user': auth['principal']['user']['id'] = value
    elif field == 'revision': state['dashboard_session_revision'] = value
    elif field == 'privileges': auth['principal']['global_privileges'] = value
    elif field == 'roles': auth['principal']['roles'] = value
    else: state['localization'][field] = value
    assert key() != before
    auth['principal'] = None
    assert key() is None


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['success','error'])
@pytest.mark.parametrize('boundary', ['identity','same_user_login','language','timezone',
                                      'navigation','new_view','client_deleted','disconnected','host_deleted'])
async def test_old_dashboard_response_cannot_repopulate_cache_or_update_another_view(boundary,outcome):
    started, release = asyncio.Event(), asyncio.Event()
    principal = {'user':{'id':1}, 'global_privileges':[]}
    auth = {'principal':principal}
    state = {'resource':'dashboard', 'localization':{'effective_language':'en','working_timezone':'UTC'}}
    token = object()
    state['dashboard_view_token'] = token
    host, client, button = Mock(is_deleted=False), SimpleNamespace(_deleted=False,has_socket_connection=True), Mock()
    async def summary(**kwargs):
        started.set()
        await release.wait()
        if outcome == 'error': raise ApiError(503,'old request failed')
        return {'private':'user A'}
    scope = dict(state=state,auth_state=auth,Any=Any,ApiError=ApiError,
                 dashboard_principal=principal,dashboard_view_token=token,
                 dashboard_content=host,page_client=client,
                 dashboard_load_state={'running':False},dashboard_refresh_controls={'button':button},
                 api=SimpleNamespace(dashboard_summary=summary),
                 accept_application_configuration=Mock(),set_connection_status=Mock())
    key = load('dashboard_session_key',scope)
    scope['dashboard_key'] = key()
    load('dashboard_session_is_current',scope)
    load('dashboard_view_is_current',scope)
    task = asyncio.create_task(load('load_dashboard',scope)(refresh_only=True))
    await started.wait()
    if boundary == 'identity': auth['principal'] = {'user':{'id':2}}
    elif boundary == 'same_user_login': load('clear_dashboard_session',scope)()
    elif boundary == 'language': state['localization']['effective_language'] = 'ar'
    elif boundary == 'timezone': state['localization']['working_timezone'] = 'Asia/Dubai'
    elif boundary == 'navigation': state['resource'] = 'records'
    elif boundary == 'new_view': state['dashboard_view_token'] = object()
    elif boundary == 'client_deleted': client._deleted = True
    elif boundary == 'disconnected': client.has_socket_connection = False
    else: host.is_deleted = True
    state['dashboard_summary_cache'] = {'private':'user B'}
    state['dashboard_summary_cache_key'] = key()
    release.set()
    await task
    assert state['dashboard_summary_cache'] == {'private':'user B'}
    host.clear.assert_not_called()
    scope['accept_application_configuration'].assert_not_called()
    scope['set_connection_status'].assert_not_called()
    assert scope['dashboard_load_state']['running'] is False


@pytest.mark.asyncio
async def test_sign_out_clears_protected_dashboard_before_waiting_for_remote_logout():
    started, release = asyncio.Event(), asyncio.Event()
    clear = Mock()
    async def logout():
        started.set()
        await release.wait()
    api = SimpleNamespace(logout=logout,set_session_token=Mock())
    scope = dict(user_menu=Mock(),clear_signed_in_identity=clear,ApiError=ApiError,
                 api=api,app=SimpleNamespace(storage=SimpleNamespace(user={})),login_dialog=Mock())
    from frontend.webui.session_context import SessionContext
    session = SessionContext(
        api=api, storage=lambda: scope['app'].storage.user, locale=lambda: {},
        reset_private_views=AsyncMock(), reset_navigation=Mock(), clear_identity=clear,
        close_menu=scope['user_menu'].close, open_login=scope['login_dialog'].open,
        set_connection_status=Mock(),
    )
    task = asyncio.create_task(session.sign_out())
    await started.wait()
    clear.assert_called_once()
    release.set()
    await task
    scope['login_dialog'].open.assert_called_once()
