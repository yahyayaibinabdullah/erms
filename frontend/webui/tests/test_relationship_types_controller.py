"""Relationship administration contracts retained from the original host baseline."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontend.webui.capabilities import can_navigate


def host(monkeypatch):
    h = SimpleNamespace(principal={'global_privileges': ['relationships.administer']},
                        selected=False, calls=[], rendered=[], languages=[{'language_tag': 'ar'}])
    def render_control(name):
        return SimpleNamespace(set_visibility=lambda value: h.calls.append((name, value)))
    state = {'localization': {'supported_languages': h.languages}}
    aggregation_state = {'aggregation_detail': {'id': 99}}
    identity = {'principal': h.principal}
    h.state, h.identity = state, identity
    async def render(**kwargs):
        h.rendered.append(kwargs)
        if getattr(h, 'delay', None):
            h.delay[0].set()
            await h.delay[1].wait()
    def register(*args):
        assert state['resource'] == 'relationship-types'
        assert state['rows'] == [] and state['searched'] and aggregation_state['aggregation_detail'] is None
        h.calls.append('register')
    ns = dict(auth_state=identity, state=state, collection_state=state, aggregation_state=aggregation_state, can_navigate=can_navigate,
              register_navigation=register, localized_navigation={'relationship-types': 'Relationship types'},
              show_authenticated_view=lambda: h.calls.append('show'),
              title=SimpleNamespace(text='old'), subtitle=SimpleNamespace(text='old'), guidance=SimpleNamespace(text='old'),
              table_container=SimpleNamespace(clear=lambda: h.calls.append('clear')),
              api=object(), error_message=str, relationship_administration=render)
    for name in ('search_bar', 'aggregation_mode_bar', 'add_button', 'add_record_button'):
        ns[name] = render_control(name)
    tree = ast.parse((Path(__file__).parents[1] / 'app.py').read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'enter_relationship_types')
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<relationship shell adapter>', 'exec'), ns)
    from frontend.webui import relationship_types_controller as feature
    monkeypatch.setattr(feature, 'relationship_administration', render)
    controller = feature.RelationshipTypesController(
        api=ns['api'], container=ns['table_container'], principal=lambda: identity['principal'],
        selected=lambda: state.get('resource') == 'relationship-types', enter=ns['enter_relationship_types'],
        supported_languages=lambda: (state.get('localization') or {}).get('supported_languages', []),
        on_error=str,
    )
    h.open = controller.open
    h.ns = ns
    return h


@pytest.mark.parametrize('principal', [None, {}, {'global_privileges': []}, {'global_privileges': ['relationships.link']}])
async def test_denied_entry_does_not_change_current_view(monkeypatch, principal):
    h = host(monkeypatch); h.identity['principal'] = principal
    await h.open()
    assert not h.calls and not h.rendered
    assert 'resource' not in h.state


async def test_authorized_entry_preserves_shell_order_and_renderer_arguments(monkeypatch):
    h = host(monkeypatch)
    await h.open()
    assert h.calls == ['register', 'show', ('search_bar', False), ('aggregation_mode_bar', False),
                       ('add_button', False), ('add_record_button', False), 'clear']
    assert h.ns['title'].text == 'Relationship types'
    assert h.ns['subtitle'].text == h.ns['guidance'].text == ''
    view = h.rendered[0]
    assert view['api'] is h.ns['api'] and view['container'] is h.ns['table_container']
    assert view['supported_languages'] is h.languages and view['on_error'] is str
    assert view['active']()


@pytest.mark.parametrize('change', ['reopen', 'leave', 'identity', 'signout'])
async def test_previous_view_becomes_inactive(monkeypatch, change):
    h = host(monkeypatch); await h.open(); old = h.rendered[0]
    if change == 'reopen': await h.open()
    elif change == 'leave': h.state['resource'] = 'record-details'
    elif change == 'identity': h.identity['principal'] = dict(h.principal)
    else: h.identity['principal'] = None
    assert not old['active']()


async def test_language_metadata_is_read_on_each_entry(monkeypatch):
    h = host(monkeypatch); await h.open()
    newer = [{'language_tag': 'en'}]
    h.state['localization']['supported_languages'] = newer
    await h.open()
    assert h.rendered[0]['supported_languages'] is h.languages
    assert h.rendered[1]['supported_languages'] is newer


async def test_independent_clients_do_not_share_view_lifetime(monkeypatch):
    a = host(monkeypatch); await a.open()
    b = host(monkeypatch); await b.open()
    a.identity['principal'] = None
    assert not a.rendered[0]['active']() and b.rendered[0]['active']()


async def test_pending_renderer_retains_original_identity(monkeypatch):
    h = host(monkeypatch)
    h.delay = (asyncio.Event(), asyncio.Event())
    task = asyncio.create_task(h.open())
    await h.delay[0].wait()
    h.identity['principal'] = dict(h.principal)
    h.delay[1].set(); await task
    assert not h.rendered[0]['active']()
