"""Real root page + real API; launch only through run_webui_integration.py.

NiceGUI's User simulates the browser. JavaScript/layout/history require the
separate real-browser acceptance checks; these tests do not claim to cover them.
"""
import asyncio
import inspect
import json
import os
from pathlib import Path
import re
import shlex
import time

import pytest
from nicegui import app, ui
from nicegui.testing import User

from frontend.webui import app as webui
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message_plain, strip_diagnostic_metadata

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def disposable_only():
    # The owning runner supplies normalized libpq keyword conninfo. Avoid a
    # PostgreSQL driver dependency in the independently installed frontend.
    connection = dict(part.split('=', 1) for part in shlex.split(os.environ.get('DATABASE_URL', '')))
    name = connection.get('dbname', '')
    assert name.startswith('erms_webui_test_'), 'Use tools/run_webui_integration.py; never a persistent DB'
    assert os.environ['MESSAGING_LISTENER_DATABASE_URL'] == os.environ['DATABASE_URL']


async def eventually(predicate, *, timeout=10):
    async with asyncio.timeout(timeout):
        while True:
            try:
                if predicate():
                    return
            except AssertionError:
                # User.find asserts while a control is not yet rendered.
                pass
            await asyncio.sleep(.02)


def plain(element):
    return strip_diagnostic_metadata(str(getattr(element, 'text', getattr(element, 'label', ''))))


def click_one(user, elements):
    assert len(elements) == 1, [(type(e).__name__, plain(e)) for e in elements]
    element = elements[0]
    element.mark(f'assembled-target-{element.id}')
    user.find(marker=f'assembled-target-{element.id}').click()


def drawer_buttons(user):
    return [b for b in user.find(ui.button).elements if 'erms-nav-link' in b.classes and b.visible]


@pytest.fixture
async def assembled(user: User, monkeypatch, request):
    clients = []
    pages = []
    requests = []
    started = time.monotonic()
    user.api_clients = clients
    user.api_requests = requests
    user.api_failures = []
    user.pending_requests = 0
    original = webui.ErmsApiClient

    def record_client(*args, **kwargs):
        client = original(*args, **kwargs)
        request = client.request

        async def observed(method, path, **options):
            user.pending_requests += 1
            entry = {'method': method, 'path': path, 'outcome': 'ok'}
            sent = time.monotonic()
            try:
                return await request(method, path, **options)
            except ApiError as error:
                entry['outcome'] = error.status_code
                user.api_failures.append((method, path, error.status_code))
                raise
            except asyncio.CancelledError:
                entry['outcome'] = 'cancelled'
                raise
            finally:
                entry['milliseconds'] = round((time.monotonic() - sent) * 1000, 2)
                requests.append(entry)
                user.pending_requests -= 1

        client.request = observed
        clients.append(client)
        return client

    monkeypatch.setattr(webui, 'ErmsApiClient', record_client)
    # Explicitly acknowledge scripts in the simulator, without pretending they
    # executed. Real browser validation is an independent acceptance gate.
    user.javascript_rules[re.compile(r'.*localStorage.getItem.*', re.S)] = lambda _: None
    user.javascript_rules[re.compile(r'.*', re.S)] = lambda _: True

    def patch_simulated_javascript():
        # NiceGUI 2.24's simulator assumes every matching script was awaited.
        # The real shell also sends fire-and-forget scripts, with no request ID.
        client = user.client
        pages.append(client)
        original_emit = client.outbox._emit

        async def emit(message):
            await original_emit(message)
            _, kind, data = message
            if kind == 'run_javascript' and 'request_id' in data:
                for pattern, response in user.javascript_rules.items():
                    match = pattern.match(data['code'])
                    if match:
                        client.handle_javascript_response({'request_id': data['request_id'], 'result': response(match)})
                        break

        client.outbox._emit = emit

    monkeypatch.setattr(user, '_patch_outbox_emit_function', patch_simulated_javascript)
    ui.page('/')(webui.index)
    try:
        await user.open('/')
        # Controls exist before the startup timer decides whether to restore a
        # session. Wait for the login dialog to open, as a real user must.
        await eventually(lambda: any(d.value and any(isinstance(b, ui.button) and plain(b) == 'Continue to wathiq'
                                                     for b in d.descendants())
                                     for d in user.find(ui.dialog).elements))
        yield user
    finally:
        for page in reversed(pages):
            with page:
                for callback in page.disconnect_handlers:
                    outcome = callback()
                    if inspect.isawaitable(outcome):
                        await outcome
        for client in clients:
            client.cancel_pending_reads()
            await client.close()
        xml_path = request.config.getoption('xmlpath')
        if xml_path:
            evidence = {'test': request.node.nodeid,
                        'milliseconds': round((time.monotonic() - started) * 1000, 2),
                        'requests': requests}
            with Path(xml_path).with_suffix('.requests.jsonl').open('a') as log:
                log.write(json.dumps(evidence) + '\n')


async def login(user, email='admin@test.invalid'):
    inputs = {plain(i): i for i in user.find(ui.input).elements}
    with user:
        inputs['Email address'].value = email
        inputs['Password'].value = 'Temporary-Test-Password-123!'
    click_one(user, [b for b in user.find(ui.button).elements if plain(b) == 'Continue to wathiq'])
    await eventually(lambda: current_page(user) == 'dashboard')
    await user.should_see('Overview', retries=100)


async def test_login_and_settings_use_the_assembled_application(assembled):
    user = assembled
    await login(user)
    click_one(user, [b for b in drawer_buttons(user) if plain(b) == 'Settings'])
    await user.should_see('Shared application settings, grouped by purpose.', retries=100)
    await eventually(lambda: bool(user.find(ui.tabs).elements))
    assert next(iter(user.find(ui.tabs).elements)).value == 'general'
    with user:
        trail = app.storage.user['navigation_trail']
    assert trail[-1]['page'] == 'application-settings'
    assert trail[-1]['state']['settings_category'] == 'general'


DESTINATIONS = {
    'dashboard': 'navigation.item.dashboard',
    'advanced-search': 'navigation.item.advanced_search',
    'aggregations': 'navigation.item.aggregations',
    'records': 'navigation.item.records',
    'classification-workspace': 'navigation.item.classification_schemes',
    'relationship-types': 'relationships.ui.catalogue',
    'disposition-tasks': 'disposition.ui.my_tasks',
    'disposition-eligibility': 'disposition.ui.eligibility',
    'disposition-jobs': 'disposition.ui.jobs',
    'disposition-templates': 'disposition.ui.templates',
    'messages-inbox': 'messaging.navigation.inbox',
    'messages-outbox': 'messaging.navigation.outbox',
    'messages-drafts': 'messaging.navigation.drafts',
    'messages-monitor': 'messaging.monitor.title',
    'messages-notifications': 'messaging.admin.title',
    'organization-browser': 'navigation.item.organization_browser',
    'org-units': 'navigation.item.org_units',
    'roles': 'navigation.item.roles',
    'users': 'navigation.item.users',
    'text-indexers': 'navigation.item.text_indexers',
    'application-settings': 'navigation.item.application_settings',
    'audit-trail': 'navigation.item.audit_trail',
    'login-sessions': 'navigation.item.login_sessions',
    'security-operations': 'navigation.item.security_operations',
    'saved-search-administration': 'privilege.search.saved_search.administrator.name',
    'security-levels': 'navigation.item.security_levels',
    'profiles': 'navigation.item.profiles',
    'governance-custody': 'navigation.item.governance_custody',
    'holds': 'navigation.item.holds',
    'translations': 'navigation.item.translations',
}


def current_page(user):
    with user:
        trail = app.storage.user.get('navigation_trail', [])
        return trail[-1]['page'] if trail else None


@pytest.mark.parametrize('destination', DESTINATIONS)
async def test_main_destination_through_real_drawer(assembled, destination):
    user = assembled
    await login(user, 'officer@test.invalid' if destination == 'disposition-templates' else 'admin@test.invalid')
    label = render_message_plain(DESTINATIONS[destination])
    click_one(user, [b for b in drawer_buttons(user) if plain(b) == label])
    await eventually(lambda: current_page(user) == destination)
    # Check the actual screen heading, not merely the drawer entry or trail.
    await eventually(lambda: any(e.parent_slot and 'erms-page-title-row' in e.parent_slot.parent.classes
                                and bool(plain(e)) for e in user.find(ui.label).elements))
    await eventually(lambda: user.pending_requests == 0)
    assert not user.api_failures


async def test_settings_category_survives_navigation_and_breadcrumb_return(assembled):
    user = assembled
    await login(user)
    click_one(user, [b for b in drawer_buttons(user) if plain(b) == 'Settings'])
    await eventually(lambda: bool(user.find(ui.tabs).elements))
    with user:
        next(iter(user.find(ui.tabs).elements)).value = 'disposition'
    def category():
        with user:
            return app.storage.user['navigation_trail'][-1]['state'].get('settings_category')
    await eventually(lambda: category() == 'disposition')
    click_one(user, [b for b in drawer_buttons(user) if plain(b) == 'Dashboard'])
    await eventually(lambda: current_page(user) == 'dashboard')
    click_one(user, [b for b in user.find(ui.button).elements
                     if plain(b) == 'Settings' and 'max-w-52' in b.classes])
    await eventually(lambda: current_page(user) == 'application-settings')
    await eventually(lambda: bool(user.find(ui.tabs).elements))
    assert next(iter(user.find(ui.tabs).elements)).value == 'disposition'


def form_inputs(user, category='general'):
    # Existing tab panels are all constructed; scope to the displayed panel.
    panel = next(p for p in user.find(ui.tab_panel).elements if p.props['name'] == category)
    return {plain(e): e for e in panel.descendants() if isinstance(e, ui.input)}


async def open_settings(user):
    click_one(user, [b for b in drawer_buttons(user) if plain(b) == 'Settings'])
    await eventually(lambda: bool(user.find(ui.tabs).elements))


async def test_settings_real_save_validation_and_refresh(assembled):
    user = assembled
    await login(user)
    await open_settings(user)
    inputs = form_inputs(user)
    original = await user.api_clients[0].application_settings()
    old_value = next(i for i in original['items'] if i['key'] == 'REVIEW_WARNING_WINDOW_DAYS')['value']
    new_value = old_value + 1
    with user:
        inputs['Review warning window'].value = str(new_value)
    panel = next(p for p in user.find(ui.tab_panel).elements if p.props['name'] == 'general')
    click_one(user, [e for e in panel.descendants() if isinstance(e, ui.button) and plain(e) == 'Save'])
    await user.should_see(render_message_plain('settings.error.reason_required'))
    unchanged = await user.api_clients[0].application_settings()
    assert next(i for i in unchanged['items'] if i['key'] == 'REVIEW_WARNING_WINDOW_DAYS')['value'] == old_value
    with user:
        inputs['Reason for change (required)'].value = 'Disposable assembled regression'
    click_one(user, [e for e in panel.descendants() if isinstance(e, ui.button) and plain(e) == 'Save'])
    await user.should_see(render_message_plain('settings.page.saved'), retries=100)
    saved = await user.api_clients[0].application_settings()
    assert next(i for i in saved['items'] if i['key'] == 'REVIEW_WARNING_WINDOW_DAYS')['value'] == new_value
    click_one(user, [b for b in drawer_buttons(user) if plain(b) == 'Dashboard'])
    await eventually(lambda: current_page(user) == 'dashboard')
    await open_settings(user)
    assert str(form_inputs(user)['Review warning window'].value) == str(new_value)


async def test_settings_reload_restores_category_and_current_data(assembled):
    user = assembled
    await login(user)
    await open_settings(user)
    with user:
        next(iter(user.find(ui.tabs).elements)).value = 'disposition'
    await eventually(lambda: user.pending_requests == 0)
    await user.open('/')
    await eventually(lambda: current_page(user) == 'application-settings')
    await eventually(lambda: bool(user.find(ui.tabs).elements))
    assert next(iter(user.find(ui.tabs).elements)).value == 'disposition'
    assert any('erms-card' in c.classes and c.visible for c in user.find(ui.card).elements)


async def test_restricted_identity_cannot_reach_settings(assembled):
    user = assembled
    await login(user, 'viewer@test.invalid')
    assert not any(plain(b) == 'Settings' for b in drawer_buttons(user))
    with pytest.raises(ApiError) as error:
        await user.api_clients[0].application_settings()
    assert error.value.status_code == 403


async def test_settings_conflict_preserves_draft_and_other_edit(assembled):
    user = assembled
    await login(user)
    await open_settings(user)
    inputs = form_inputs(user)
    api = user.api_clients[0]
    item = next(i for i in (await api.application_settings())['items']
                if i['key'] == 'REVIEW_WARNING_WINDOW_DAYS')
    # Another committed edit makes the displayed version stale.
    await api.save_application_settings([{'key': item['key'], 'expected_version': item['version'],
                                          'value': item['value'] + 1}], 'Concurrent disposable edit')
    draft = str(item['value'] + 2)
    with user:
        inputs['Review warning window'].value = draft
        inputs['Reason for change (required)'].value = 'Preserve this unsaved draft'
    panel = next(p for p in user.find(ui.tab_panel).elements if p.props['name'] == 'general')
    click_one(user, [e for e in panel.descendants() if isinstance(e, ui.button) and plain(e) == 'Save'])
    await eventually(lambda: any(status == 409 for _, _, status in user.api_failures))
    await eventually(lambda: user.pending_requests == 0)
    assert inputs['Review warning window'].value == draft
    assert inputs['Reason for change (required)'].value == 'Preserve this unsaved draft'
    saved = next(i for i in (await api.application_settings())['items'] if i['key'] == item['key'])
    assert saved['value'] == item['value'] + 1
    assert any(isinstance(e, ui.label) and plain(e) for e in panel.descendants())


async def test_sign_out_then_restricted_sign_in_clears_settings_authority(assembled):
    user = assembled
    await login(user)
    await open_settings(user)
    click_one(user, [b for b in user.find(ui.button).elements if plain(b) == 'Sign out'])
    await eventually(lambda: any(d.value and any(isinstance(b, ui.button) and plain(b) == 'Continue to wathiq'
                                                for b in d.descendants())
                                for d in user.find(ui.dialog).elements))
    with user:
        assert not app.storage.user.get('session_token')
    await login(user, 'viewer@test.invalid')
    assert not any(plain(b) == 'Settings' for b in drawer_buttons(user))
    assert current_page(user) == 'dashboard'


async def test_custody_warning_opens_disposition_settings(assembled):
    user = assembled
    await login(user)
    click_one(user, [b for b in drawer_buttons(user) if plain(b) == render_message_plain('navigation.item.governance_custody')])
    label = render_message_plain('settings.custody.open')
    await eventually(lambda: any(plain(b) == label for b in user.find(ui.button).elements))
    click_one(user, [b for b in user.find(ui.button).elements if plain(b) == label])
    await eventually(lambda: current_page(user) == 'application-settings')
    await eventually(lambda: bool(user.find(ui.tabs).elements))
    assert next(iter(user.find(ui.tabs).elements)).value == 'disposition'


async def test_audit_event_opens_its_setting_in_the_assembled_app(assembled):
    user = assembled
    await login(user)
    api = user.api_clients[0]
    items = (await api.application_settings())['items']
    item = next(i for i in items if i['key'] == 'REVIEW_WARNING_WINDOW_DAYS')
    await api.save_application_settings([{'key': item['key'], 'expected_version': item['version'],
                                          'value': item['value'] + 1}], 'Disposable audit-link test')
    click_one(user, [b for b in drawer_buttons(user) if plain(b) == 'Audit trail'])
    label = render_message_plain('webui.render_event_timeline.tooltip.open_current_entity_208e2a65')
    def links():
        return sorted([b for b in user.find(ui.button).elements
                       if strip_diagnostic_metadata(str(b.props.get('aria-label', ''))) == label], key=lambda b: b.id)
    await eventually(lambda: bool(links()))
    click_one(user, links()[:1])
    await eventually(lambda: current_page(user) == 'application-settings')
    await eventually(lambda: bool(user.find(ui.tabs).elements))
    assert next(iter(user.find(ui.tabs).elements)).value == 'general'


async def test_aggregation_reload_shows_the_restored_content_panel(assembled):
    """Phase 1 B1: regression check for the separately approved visibility fix."""
    user = assembled
    await login(user)
    # Prepare an ordinary persisted visit, then enter through the real root.
    # No application callback is extracted or replaced.
    with user:
        app.storage.user['navigation_trail'] = [{'page': 'aggregation-details', 'entity_id': 1,
                                                'label': 'Test aggregation', 'state': {}}]
    await user.open('/')
    await user.should_see('Aggregation overview', retries=200)
    await eventually(lambda: user.pending_requests == 0)
    cards = [e for e in user.client.elements.values() if isinstance(e, ui.card) and 'erms-card' in e.classes]
    assert len(cards) == 1
    assert cards[0].visible, 'B1: restored aggregation content exists but its parent panel remains hidden'


@pytest.mark.parametrize('status', [403, 404])
async def test_unavailable_breadcrumb_restores_previous_visit_in_real_root(assembled, monkeypatch, status):
    """Controlled target failure through the assembled UI; other calls use real API."""
    user = assembled
    await login(user)
    with user:
        app.storage.user['navigation_trail'] = [
            {'page': 'dashboard', 'label': 'Dashboard', 'state': {}},
            {'page': 'aggregation-details', 'entity_id': 1, 'label': 'Unavailable aggregation', 'state': {}},
            {'page': 'application-settings', 'label': 'Settings', 'state': {'settings_category': 'general'}},
        ]
    await user.open('/')
    await user.should_see('Shared application settings, grouped by purpose.', retries=200)
    await eventually(lambda: user.pending_requests == 0)
    attempted = []
    for client in user.api_clients:
        original = client.get

        async def controlled(resource, identity, _original=original):
            if resource == 'aggregations' and identity == 1:
                attempted.append(status)
                raise ApiError(status, 'Controlled unavailable breadcrumb target')
            return await _original(resource, identity)

        monkeypatch.setattr(client, 'get', controlled)
    click_one(user, [b for b in user.find(ui.button).elements if plain(b) == 'Unavailable aggregation'])
    await user.should_see('Overview', retries=200)
    await eventually(lambda: current_page(user) == 'dashboard' and user.pending_requests == 0)
    assert attempted == [status]
    with user:
        assert [e['page'] for e in app.storage.user['navigation_trail']] == ['dashboard']
    assert not user.api_failures


async def test_temporary_password_recovery_and_abandonment_in_real_root(assembled):
    from uuid import uuid4
    user = assembled
    await login(user)
    api = user.api_clients[0]
    email = 'recovery-' + uuid4().hex + '@test.invalid'
    person = await api.request('POST', '/api/v1/users', json={
        'name': 'Disposable recovery person', 'email': email, 'account_type': 'person'})
    issued = await api.request('POST', f"/api/v1/auth/users/{person['id']}/temporary-password")
    temporary = issued['temporary_password']
    click_one(user, [b for b in user.find(ui.button).elements if plain(b) == 'Sign out'])
    await eventually(lambda: any(d.value and any(isinstance(b, ui.button) and plain(b) == 'Continue to wathiq'
                                               for b in d.descendants()) for d in user.find(ui.dialog).elements))

    async def sign_in_restricted():
        inputs = {plain(i): i for i in user.find(ui.input).elements}
        with user:
            inputs['Email address'].value = email
            inputs['Password'].value = temporary
        start = len(user.api_requests)
        click_one(user, [b for b in user.find(ui.button).elements if plain(b) == 'Continue to wathiq'])
        await user.should_see('Set a new password', retries=100)
        await eventually(lambda: user.pending_requests == 0)
        # NiceGUI's simulator lists child controls even inside a closed drawer.
        drawers = [e for e in user.client.elements.values() if 'erms-drawer' in e.classes]
        assert len(drawers) == 1 and not drawers[0].value
        assert not [r for r in user.api_requests[start:] if r['path'] in (
            '/api/v1/dashboard/summary', '/api/v1/application-settings', '/api/v1/favourites')]
        return next(d for d in user.find(ui.dialog).elements if d.value and
                    any(isinstance(e, ui.input) and plain(e) == 'Temporary password' for e in d.descendants()))

    dialog = await sign_in_restricted()
    click_one(user, [b for b in dialog.descendants() if isinstance(b, ui.button) and plain(b) == 'Back to sign in'])
    await eventually(lambda: not dialog.value)
    await eventually(lambda: user.pending_requests == 0)
    dialog = await sign_in_restricted()
    inputs = {plain(i): i for i in dialog.descendants() if isinstance(i, ui.input)}
    with user:
        inputs['Temporary password'].value = temporary
        inputs['New password'].value = 'Changed-Test-Password-456!'
        inputs['Confirm new password'].value = 'Changed-Test-Password-456!'
    click_one(user, [b for b in dialog.descendants() if isinstance(b, ui.button) and plain(b) == 'Set new password'])
    await user.should_see('Overview', retries=100)
    await eventually(lambda: current_page(user) == 'dashboard' and user.pending_requests == 0)
    assert not user.api_failures
