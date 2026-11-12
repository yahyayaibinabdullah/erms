"""Security operations period requests and denial through the actual API."""
import pytest
from nicegui import ui
from frontend.webui.api_client import ApiError
from frontend.webui.assembled.tests.test_application import assembled,login,current_page,drawer_buttons,click_one,eventually
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

async def test_security_periods_and_custom_validation_use_real_api(assembled):
    user=assembled;await login(user)
    calls=[];original=user.api_clients[0].security_summary
    async def observed(**kwargs):
        calls.append(kwargs)
        return await original(**kwargs)
    user.api_clients[0].security_summary=observed
    click_one(user,[b for b in drawer_buttons(user) if plain(b)==t('navigation.item.security_operations')])
    label=t('webui.load_security_operations.label.administrative_access_and_security_level_c_6d5dbfc3')
    await eventually(lambda:current_page(user)=='security-operations' and any(plain(e)==label for e in user.find(ui.label).elements) and user.pending_requests==0)
    control=next(e for e in user.find(ui.select).elements if plain(e)==t('webui.select_security_operations.select.period_ed31c1a0'))
    with user:control.value='month'
    await eventually(lambda:any(r.get('hours')==720 for r in calls))
    await eventually(lambda:user.pending_requests==0)
    with user:control.value='custom'
    count=len(user.api_requests);notices=len(user.notify.messages)
    apply=t('webui.select_security_operations.button.apply_range_53faab3c')
    click_one(user,[b for b in user.find(ui.button).elements if plain(b)==apply])
    await eventually(lambda:len(user.notify.messages)>notices)
    assert not any(r['path'].endswith('/security-operations/summary') for r in user.api_requests[count:])
    fields={plain(e):e for e in user.find(ui.input).elements}
    with user:
        fields[t('webui.select_security_operations.input.from_a135a152')].value='2030-01-01'
        fields[t('webui.select_security_operations.input.through_b5ed408a')].value='2030-01-02'
    click_one(user,[b for b in user.find(ui.button).elements if plain(b)==apply])
    await eventually(lambda:any((r.get('start_at') or '').startswith('2030-01-01') for r in calls))
    await eventually(lambda:user.pending_requests==0)
    assert not user.api_failures

async def test_security_operations_is_hidden_and_api_denied_for_viewer(assembled):
    user=assembled;await login(user,'viewer@test.invalid')
    assert not any(plain(b)==t('navigation.item.security_operations') and b.visible for b in drawer_buttons(user))
    for method in ('security_summary','security_reconciliation'):
        with pytest.raises(ApiError) as error:await getattr(user.api_clients[0],method)()
        assert error.value.status_code==403
    with pytest.raises(ApiError) as error:
        await user.api_clients[0].security_events(
            start_at='2030-01-01T00:00:00Z', end_at='2030-01-02T00:00:00Z',
            limit=10, offset=100,
        )
    assert error.value.status_code == 403
    with pytest.raises(ApiError) as error:
        await user.api_clients[0].security_denial_groups(
            start_at='2030-01-01T00:00:00Z', end_at='2030-01-02T00:00:00Z',
            limit=11, offset=50,
        )
    assert error.value.status_code == 403
