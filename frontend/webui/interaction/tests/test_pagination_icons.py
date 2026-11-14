"""Real pager widgets: valid icon props and unchanged paging callbacks."""
import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from nicegui import ui
from frontend.webui.administration_cards import build_administration_cards
from frontend.webui.entities import ENTITIES
from frontend.webui.i18n_catalogue import set_active_messages
from test_login_sessions_feature import setup as session_setup, button as session_button, click, settle
from test_text_indexers_feature import setup as indexer_setup, button as indexer_button

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


def messages(language):
    return {r['message_key']: r['translated_text'] for r in json.loads(
        (Path(__file__).parents[2] / 'i18n/messages.ar.generated.json').read_text())['items']} if language == 'ar' else {}


def valid_icon(button, expected):
    assert button.props.get('icon') == expected
    assert 'icon-right' not in button.props or isinstance(button.props['icon-right'], str)


@pytest.mark.parametrize('language', ['en', 'ar'])
@pytest.mark.parametrize('resource', ['profiles', 'security-levels', 'users', 'roles', 'org-units'])
async def test_administration_pager_icons_offsets_and_boundaries(user, language, resource):
    page = dict(offset=0, limit=25, total=51, query='', status='all', account_type='all',
                sort='level_number' if resource == 'security-levels' else 'name')
    calls = []
    async def load(**kwargs):
        calls.append(page['offset'])
        kwargs['on_loaded']()
    values = {name: Mock() for name in inspect.signature(build_administration_cards).parameters}
    values.update(pages={resource: page}, load_rows=AsyncMock(side_effect=load),
                  format_timestamp=lambda _: 'Fixed date', localized_account_type=lambda v: v,
                  localized_lifecycle_value=lambda v: v,
                  get_rows=lambda: [dict(id=i, name=f'Item {i}', code=f'I-{i}', account_type='person')
                      for i in range(page['offset'], min(page['offset']+25, page['total']))])
    rendered = {}
    @ui.page('/pager-icons')
    def screen():
        set_active_messages(messages(language))
        rendered['refresh'] = build_administration_cards(**values)(ENTITIES[resource])
    await user.open('/pager-icons')
    controls = {b.props['icon']: b for b in user.find(ui.button).elements
                if b.props.get('icon') in {'first_page', 'chevron_left', 'chevron_right', 'last_page'}}
    for icon, b in controls.items():
        valid_icon(b, icon)
    assert len(controls) == 4 and not controls['first_page'].enabled
    for icon, offset in [('chevron_right',25), ('last_page',50), ('chevron_left',25), ('first_page',0)]:
        b = controls[icon]
        assert b.enabled
        callback = next(v.handler for v in b._event_listeners.values() if v.type == 'click')
        with b.parent_slot:
            await callback()
        assert page['offset'] == offset and calls[-1] == offset
        assert controls['last_page'].enabled == (offset < 50)
    page['total'] = 0
    with user:
        rendered['refresh']()
    assert all(not b.enabled for b in controls.values())


@pytest.mark.parametrize('language', ['en', 'ar'])
async def test_session_pager_icons_and_request_offsets(user, monkeypatch, language):
    import test_login_sessions_feature as fixture
    original = fixture.build
    def localized(scope):
        set_active_messages(messages(language))
        return original(scope)
    monkeypatch.setattr(fixture, 'build', localized)
    api, _ = await session_setup(user)
    for key, icon, offset in [
        ('next_b09718d5','chevron_right',20), ('last_5cfe5c95','last_page',40),
        ('previous_6631329f','chevron_left',20), ('first_3e9443bf','first_page',0)]:
        with user:
            b = session_button(user, 'webui.select_login_sessions.button.'+key)
        valid_icon(b, icon)
        click(user, b); await settle()
        assert api.login_sessions_page.await_args.kwargs['offset'] == offset
        assert api.login_sessions_page.await_args.kwargs['limit'] == 20


@pytest.mark.parametrize('language', ['en', 'ar'])
async def test_credential_pager_icons_direction_and_offsets(user, monkeypatch, language):
    import test_text_indexers_feature as fixture
    original = fixture.build
    def localized(scope):
        set_active_messages(messages(language))
        return original(scope)
    monkeypatch.setattr(fixture, 'build', localized)
    api, _ = await indexer_setup(user, detail=True, direction='rtl' if language=='ar' else 'ltr')
    response = api.text_indexer_credentials.return_value
    api.text_indexer_credentials.side_effect = lambda *args, **kwargs: dict(response, offset=kwargs['offset'])
    for key, icon, offset in [('next_e284c9ef','chevron_left' if language=='ar' else 'chevron_right',5),
                              ('previous_86972be8','chevron_right' if language=='ar' else 'chevron_left',0)]:
        with user:
            b = indexer_button(user, 'webui.select_text_indexer_details.button.'+key)
        valid_icon(b, icon)
        click(user, b); await settle()
        assert api.text_indexer_credentials.await_args.kwargs['offset'] == offset
        assert api.text_indexer_credentials.await_args.kwargs['limit'] == 5
