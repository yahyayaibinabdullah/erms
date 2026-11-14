"""Governance custody status and connected Settings/organization destinations."""
import pytest
from nicegui import ui
from frontend.webui.api_client import ApiError
from frontend.webui.assembled.tests.test_application import assembled,login,current_page,drawer_buttons,click_one,eventually
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

async def enter(user):
    click_one(user,[b for b in drawer_buttons(user) if plain(b)==t('navigation.item.governance_custody')])
    await eventually(lambda:current_page(user)=='governance-custody' and any('governance-metric-card' in e.classes for e in user.client.elements.values()) and user.pending_requests==0)

async def test_custody_status_settings_role_and_user_links(assembled):
    user=assembled;await login(user);await enter(user)
    report=await user.api_clients[0].governance_custody();assert report['highest_clearance_custodian_count']>=1
    click_one(user,[b for b in user.find(ui.button).elements if plain(b)==t('settings.custody.open')])
    await eventually(lambda:current_page(user)=='application-settings' and user.pending_requests==0)
    assert any('application-settings-page' in e.classes for e in user.client.elements.values())
    for icon,destination in [('badge','role-details'),('person','user-details')]:
        await enter(user)
        card=next(e for e in user.client.elements.values() if 'governance-custody-assignment-card' in e.classes)
        click_one(user,[b for b in card.descendants() if isinstance(b,ui.button) and b.props.get('icon')==icon])
        await eventually(lambda:current_page(user)==destination and user.pending_requests==0)
    assert not user.api_failures

async def test_custody_denied_and_hidden_for_viewer(assembled):
    user=assembled;await login(user,'viewer@test.invalid')
    assert not any(plain(b)==t('navigation.item.governance_custody') for b in drawer_buttons(user))
    with pytest.raises(ApiError) as error:await user.api_clients[0].governance_custody()
    assert error.value.status_code==403
