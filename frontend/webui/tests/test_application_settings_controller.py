"""Feature-boundary contracts: authorization, callers and abandoned views."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from frontend.webui import application_settings_controller as feature


def controller(monkeypatch, *, privileges=('app.settings.manage',)):
    host = SimpleNamespace(principal={'global_privileges':list(privileges)}, selected=False,
                           allowed=True, visits=0, persisted=[], rendered=[])

    def enter():
        host.selected = True
        host.visits += 1

    async def guard(callback):
        if host.allowed:
            await callback()

    async def render(**kwargs):
        host.rendered.append(kwargs)

    monkeypatch.setattr(feature, 'settings_page', render)
    page = feature.ApplicationSettingsController(
        api=SimpleNamespace(), container=SimpleNamespace(),
        principal=lambda:host.principal, selected=lambda:host.selected, enter=enter,
        persist_category=lambda:host.persisted.append(page.category), guard=guard,
        bind_relationship=Mock(), direction=lambda:'rtl', on_error=str,
    )
    return page, host


@pytest.mark.parametrize('principal', [None, {}, {'global_privileges':[]}])
async def test_unauthorized_entry_has_no_shell_or_render_side_effects(monkeypatch, principal):
    page, host = controller(monkeypatch)
    host.principal = principal
    await page.open('email')
    assert not page.can_open()
    assert host.visits == 0 and not host.rendered
    assert page.category == 'general'


@pytest.mark.parametrize('entry', ['open_from_drawer', 'open_from_custody', 'open_from_event'])
async def test_cancelled_navigation_does_not_replace_the_current_view(monkeypatch, entry):
    page, host = controller(monkeypatch)
    await page.open('authentication')
    old = host.rendered[-1]
    host.allowed = False
    arguments = [{'metadata':{'setting_key':'SMTP_HOST'}}] if entry=='open_from_event' else []
    await getattr(page, entry)(*arguments)
    assert host.visits == 1 and page.category == 'authentication'
    assert old['active']()


async def test_all_callers_preserve_initial_category_and_setting_key(monkeypatch):
    page, host = controller(monkeypatch)
    await page.open_from_drawer()
    assert host.rendered[-1]['initial_category']=='general'
    await page.open_from_custody()
    assert host.rendered[-1]['initial_category']=='disposition'
    await page.restore({'settings_category':'email'})
    assert host.rendered[-1]['initial_category']=='email'
    await page.restore({})
    assert host.rendered[-1]['initial_category']=='general'
    await page.open_from_event({'metadata':{'setting_key':'SMTP_HOST'}})
    assert host.rendered[-1]['initial_setting_key']=='SMTP_HOST'
    assert host.rendered[-1]['initial_category']=='general'
    assert host.rendered[-1]['direction']()=='rtl'


async def test_audit_dialog_closes_before_the_existing_guard_even_if_cancelled(monkeypatch):
    page, host = controller(monkeypatch)
    origin = Mock()
    host.allowed = False
    await page.open_from_event({'_origin_dialog':origin})
    origin.close.assert_called_once()
    assert not host.rendered
    host.principal = None
    origin.reset_mock()
    await page.open_from_event({'_origin_dialog':origin})
    origin.close.assert_not_called()


@pytest.mark.parametrize('abandon', ['replace_view', 'leave_feature', 'replace_identity'])
async def test_old_view_cannot_remember_category_or_remain_active(monkeypatch, abandon):
    page, host = controller(monkeypatch)
    await page.open('general')
    old = host.rendered[-1]
    old['on_category']('email')
    assert page.category=='email' and host.persisted==['email']
    if abandon=='replace_view':
        await page.open('disposition')
    elif abandon=='leave_feature':
        host.selected = False
    else:
        host.principal = dict(host.principal)  # Same values, different identity.
    expected = page.category
    assert not old['active']()
    old['on_category']('search')
    assert page.category==expected and host.persisted==['email']


async def test_two_client_instances_do_not_share_view_tokens_or_categories(monkeypatch):
    first, a = controller(monkeypatch)
    # Both controllers call the same patched renderer, so retain each call's
    # callbacks explicitly rather than relying on separate renderer globals.
    await first.open('email')
    first_view = a.rendered[-1]
    second, b = controller(monkeypatch)
    await second.open('disposition')
    second_view = b.rendered[-1]
    first_view['on_category']('search')
    assert first.category=='search' and second.category=='disposition'
    assert first_view['active']() and second_view['active']()


async def test_pending_render_keeps_its_original_view_identity(monkeypatch):
    page, host = controller(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    observed = []

    async def delayed(**kwargs):
        entered.set()
        await release.wait()
        observed.append(kwargs['active']())
        kwargs['on_category']('email')

    monkeypatch.setattr(feature, 'settings_page', delayed)
    pending = asyncio.create_task(page.open())
    await entered.wait()
    host.selected = False
    release.set()
    await pending
    assert observed==[False] and not host.persisted
