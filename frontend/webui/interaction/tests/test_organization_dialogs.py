"""Organization assignments and deletion rules, before and after extraction."""
from frontend.webui.i18n_catalogue import strip_diagnostic_metadata as _owner_strip_diagnostic_metadata
import inspect
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from nicegui import ui
from frontend.webui import app as host
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

def load(name, scope):
    from frontend.webui.organization_memberships import build_organization_memberships
    from frontend.webui.organization_deletion import build_organization_deletion
    factory={'show_memberships':build_organization_memberships,'confirm_identity_deletion':build_organization_deletion}[name]
    return factory(**{key:scope[key] for key in inspect.signature(factory).parameters})

def click(user,label):
    b=next(b for b in user.find(ui.button).elements if _owner_strip_diagnostic_metadata(b.text)==label)
    b.mark(f'org-dialog-{b.id}');user.find(marker=f'org-dialog-{b.id}').click()

async def setup_memberships(user,for_user,status='active',fetch=None):
    api=SimpleNamespace(user_roles=AsyncMock(return_value={'items':[],'total':0}),role_users=AsyncMock(return_value={'items':[],'total':0}),create=AsyncMock(),delete_assignment=AsyncMock())
    if fetch is not None:
        (api.user_roles if for_user else api.role_users).side_effect = fetch
    picker=Mock();browse=AsyncMock()
    scope=dict(vars(host),api=api,bind_remote_relationship_select=picker,show_organization_structure=browse)
    @ui.page('/membership-regression')
    async def page():await load('show_memberships',scope)({'id':7,'name':'Fixture','status':status},for_user=for_user)
    await user.open('/membership-regression')
    return api,picker,browse

@pytest.mark.parametrize('for_user',[False,True])
async def test_assignment_validation_payload_refresh_and_bounded_picker(user,for_user):
    api,picker,browse=await setup_memberships(user,for_user)
    reader=api.user_roles if for_user else api.role_users
    reader.assert_awaited_once_with(7,limit=25,offset=0,sort="counterpart",descending=False)
    click(user,t('webui.show_memberships.button.assign_e003b2ce'));await asyncio.sleep(.05)
    api.create.assert_not_awaited()
    control=picker.call_args.args[0]
    with user:control.set_options({9:'Counterpart'},value=9)
    click(user,t('webui.show_memberships.button.assign_e003b2ce'));await asyncio.sleep(.05)
    api.create.assert_awaited_once_with('user-role-assignments',{'user_id':7 if for_user else 9,'role_id':9 if for_user else 7})
    assert reader.await_count==2 and control.value is None
    args=picker.call_args.kwargs
    assert args['resource']==('roles' if for_user else 'users')
    assert args['item_filter']({'id':9,'status':'active'})
    assert not args['item_filter']({'id':9,'status':'inactive'})
    click(user,t('webui.show_memberships.button.browse_aed12689'));await asyncio.sleep(.05)
    browse.assert_awaited_once_with(selection_mode='role' if for_user else 'user',target_control=control)

@pytest.mark.parametrize('for_user,status',[(True,'inactive'),(True,'suspended'),(False,'inactive')])
async def test_inactive_entity_disables_new_assignment(user,for_user,status):
    api,picker,_=await setup_memberships(user,for_user,status)
    assert not picker.call_args.args[0].enabled
    assert not next(b for b in user.find(ui.button).elements if _owner_strip_diagnostic_metadata(b.text)==t('webui.show_memberships.button.assign_e003b2ce')).enabled
    api.create.assert_not_awaited()

@pytest.mark.parametrize('for_user',[False,True])
async def test_assignment_failure_retains_selection_and_dialog(user,for_user):
    api,picker,_=await setup_memberships(user,for_user)
    api.create.side_effect=ApiError(403,'Denied')
    control=picker.call_args.args[0]
    with user:control.set_options({9:'Counterpart'},value=9)
    click(user,t('webui.show_memberships.button.assign_e003b2ce'));await asyncio.sleep(.05)
    assert control.value==9 and any(d.value for d in user.find(ui.dialog).elements)
    assert (api.user_roles if for_user else api.role_users).await_count==1

@pytest.mark.parametrize('blocked',[False,True])
async def test_permanent_deletion_preflight_reason_and_callback(user,blocked):
    api=SimpleNamespace(deletion_preflight=AsyncMock(return_value={'blockers':[{'message':'Owned content'}] if blocked else [],'entity_version':4,'cascades':{}}),delete=AsyncMock())
    deleted=AsyncMock();scope=dict(vars(host),api=api)
    @ui.page('/deletion-regression')
    async def page():await load('confirm_identity_deletion',scope)('org-units',{'id':7,'name':'Fixture'},label='organization unit',on_deleted=deleted)
    await user.open('/deletion-regression')
    api.deletion_preflight.assert_awaited_once_with('org-units',7)
    if blocked:
        await user.should_see('Owned content')
        assert not any(isinstance(e,ui.textarea) for e in user.client.elements.values())
        api.delete.assert_not_awaited();return
    click(user,t('webui.confirm_identity_deletion.button.delete_permanently_3b2f8fa1'));await asyncio.sleep(.05)
    api.delete.assert_not_awaited()
    with user:next(iter(user.find(ui.textarea).elements)).value='  Approved fixture cleanup  '
    click(user,t('webui.confirm_identity_deletion.button.delete_permanently_3b2f8fa1'));await asyncio.sleep(.05)
    api.delete.assert_awaited_once_with('org-units',7,4,reason='Approved fixture cleanup')
    deleted.assert_awaited_once()


@pytest.mark.parametrize('for_user', [True, False])
async def test_membership_filters_stay_mounted_and_reach_all_pages(user, for_user):
    counterpart_field = 'role_id' if for_user else 'user_id'

    async def fetch(entity_id, *, limit, offset, membership_q='', **filters):
        matching = [] if membership_q == 'missing' else list(range(30))
        return {'items': [
            {'id': index+1, 'version': 1, counterpart_field: index+1,
             'counterpart': {'id': index+1, 'code': f'A-{index}', 'name': f'Assignment {index}', 'status':'active'}}
            for index in matching[offset:offset+limit]
        ], 'total': len(matching)}

    api, picker, _ = await setup_memberships(user, for_user, fetch=fetch)
    reader = api.user_roles if for_user else api.role_users
    target = t('entity_metadata.field.role' if for_user else 'entity_metadata.field.user')
    field = 'code' if for_user else 'email'
    search_label = t(f'webui.show_memberships.input.search_counterpart_name_or_{field}', counterpart=target)
    search = next(c for c in user.find(ui.input).elements if _owner_strip_diagnostic_metadata(c.label)==search_label)
    table = next(iter(user.find(ui.table).elements))
    assert len(table.rows) == table.pagination['rowsPerPage'] == 25
    click(user,t('webui.load_held_itemships.button.filters_d7704feb'))
    status = next(c for c in user.find(ui.select).elements
                  if c.label == t('webui.load_held_itemships.select.status_f583ecf6'))
    dates = {c.label:c for c in user.find(ui.input).elements if c is not search}
    valid_from = dates[t('webui.load_held_itemships.input.valid_during_or_after_426a5d0b')]
    valid_until = dates[t('webui.load_held_itemships.input.valid_during_or_before_d4e95a3d')]

    with user:
        search.value = 'Assignment'
        status.value = 'active'
        valid_from.value = '2026-06-01'
        valid_until.value = '2026-06-30'
    await asyncio.sleep(.05)
    criteria = {'membership_q':'Assignment', ('role_status' if for_user else 'user_status'):'active',
                'valid_from':'2026-06-01', 'valid_until':'2026-06-30'}
    reader.assert_awaited_with(7, limit=25, offset=0, sort='counterpart', descending=False, **criteria)

    following = next(b for b in user.find(ui.button).elements if b.props.get('icon') == 'chevron_right')
    following.mark('membership-next')
    user.find(marker='membership-next').click()
    await asyncio.sleep(.05)
    reader.assert_awaited_with(7, limit=25, offset=25, sort='counterpart', descending=False, **criteria)
    assert len(table.rows) == 5
    assert table.rows[0]['id'] == 26 and table.pagination['page'] == 2
    assert (search.value, status.value, valid_from.value, valid_until.value) == (
        'Assignment','active','2026-06-01','2026-06-30',
    )

    request = next(event.handler for event in table._event_listeners.values() if event.type=='request')
    with user:
        await request(SimpleNamespace(args={'pagination': {'sortBy':'valid_until', 'descending':True}}))
    reader.assert_awaited_with(7, limit=25, offset=0, sort='valid_until', descending=True, **criteria)
    assert table.pagination['sortBy'] == 'valid_until'

    with user:
        search.value = 'missing'
    await user.should_see(t('webui.render_governance_cards.label.no_matching_items_38db9ba1'))
    assert search.visible and search.value == 'missing' and not following.enabled
    assert not picker.call_args.kwargs['item_filter']({'id': 1, 'status': 'active'})
    with user:
        search.value = 'Assignment'
    await asyncio.sleep(.05)
    assert table.visible and table.pagination['page'] == 1 and following.enabled
