"""Connected organization workflows through the real root and disposable API."""
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import (
    assembled, disposable_only, login, current_page, drawer_buttons, click_one, eventually, plain,
)
from frontend.webui.assembled.tests.test_security_feature import click, opened
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio


async def open_detail(user,resource,label,query):
    click_one(user,[b for b in drawer_buttons(user) if plain(b)==label])
    await eventually(lambda:current_page(user)==resource and user.pending_requests==0)
    field=next(i for i in user.find(ui.input).elements if 'Filter ' in plain(i))
    with user:field.value=query
    await eventually(lambda:len([c for c in user.find(ui.card).elements if 'governance-list-card' in c.classes])==1 and user.pending_requests==0)
    card=next(c for c in user.find(ui.card).elements if 'governance-list-card' in c.classes)
    click_one(user,[b for b in card.descendants() if isinstance(b,ui.button) and b.props.get('icon')=='open_in_new'])
    await eventually(lambda:current_page(user).endswith('-details') and user.pending_requests==0)


async def test_membership_write_and_removal_refresh_through_user_details(assembled):
    user=assembled;await login(user);api=user.api_clients[0]
    role_page=await api.search_request('roles',{'where':{'field':'code','operator':'eq','value':'officer'},'limit':1})
    role=role_page['items'][0]
    await open_detail(user,'users','Users','viewer@test.invalid')
    click(user,t('webui.select_user_details.button.role_assignments_adaadc55'));d=await opened(user)
    selector=next(e for e in d.descendants() if isinstance(e,ui.select))
    with user:selector.set_options({role['id']:role['name']},value=role['id'])
    click(user,t('webui.show_memberships.button.assign_e003b2ce'),d)
    await eventually(lambda:any(isinstance(e,ui.table) and e.rows for e in d.descendants()) and user.pending_requests==0)
    table=next(e for e in d.descendants() if isinstance(e,ui.table));row=table.rows[0]
    stored=await api.user_roles(row['user_id'],limit=25,offset=0)
    assert len(stored['items'])==1 and stored['items'][0]['role_id']==role['id']
    # NiceGUI's simulator dispatches the same custom event as the rendered slot.
    with user:table._handle_event({'listener_id':next(l.id for l in table._event_listeners.values() if l.type=='remove'),'args':row})
    await eventually(lambda:any(r['method']=='DELETE' and '/user-role-assignments/' in r['path'] for r in user.api_requests) and user.pending_requests==0)
    assert (await api.user_roles(row['user_id'],limit=25,offset=0))['total']==0
    assert not user.api_failures


async def test_unit_lifecycle_is_inherited_and_refreshes_after_reactivation(assembled):
    user=assembled;await login(user);api=user.api_clients[0]
    parent=await api.create('org-units',{'code':'PHASE6G-P','name':'Phase6G parent'})
    child=await api.create('org-units',{'code':'PHASE6G-C','name':'Phase6G child','parent_org_unit_id':parent['id']})
    await open_detail(user,'org-units','Organization units','PHASE6G-P')
    click(user,t('webui.select_organization_unit_details.button.deactivate_5e1ac197'))
    await eventually(lambda:any(r['method'] in {'PATCH','POST'} and str(parent['id']) in r['path'] for r in user.api_requests) and user.pending_requests==0)
    await user.should_see(t('webui.select_organization_unit_details.button.activate_e8099903'),retries=100)
    assert (await api.organization_summary('org-units',child['id']))['effective_status']=='inactive'
    click(user,t('webui.select_organization_unit_details.button.activate_e8099903'))
    await user.should_see(t('webui.select_organization_unit_details.button.deactivate_5e1ac197'),retries=100)
    assert (await api.organization_summary('org-units',child['id']))['effective_status']=='active'
    assert not user.api_failures


async def test_empty_unit_deletion_requires_reason_and_returns_to_list(assembled):
    user=assembled;await login(user);api=user.api_clients[0]
    unit=await api.create('org-units',{'code':'PHASE6G-DELETE','name':'Phase6G deletion fixture'})
    await open_detail(user,'org-units','Organization units','PHASE6G-DELETE')
    click(user,t('webui.select_organization_unit_details.button.permanently_delete_257a572f'))
    d=await opened(user)
    with user:next(e for e in d.descendants() if isinstance(e,ui.textarea)).value='Disposable regression fixture'
    click(user,t('webui.confirm_identity_deletion.button.delete_permanently_3b2f8fa1'),d)
    await eventually(lambda:current_page(user)=='org-units' and user.pending_requests==0)
    result=await api.search_request('org-units',{'where':{'field':'id','operator':'eq','value':unit['id']},'limit':1})
    assert result['total']==0 and not user.api_failures


async def test_unit_editor_hydrates_and_preserves_existing_designated_roles(assembled):
    user=assembled;await login(user);api=user.api_clients[0]
    roles=await api.search_request('roles',{'where':{'field':'code','operator':'eq','value':'admin'},'limit':1})
    role=roles['items'][0];unit=await api.get('org-units',role['org_unit_id'])
    await api.update('org-units',unit['id'],unit['version'],{'managing_role_id':role['id'],'file_administrator_role_id':role['id']})
    await open_detail(user,'org-units','Organization units','WEBUI-TEST')
    click(user,t('webui.select_organization_unit_details.button.edit_cfc8d565'));d=await opened(user)
    controls={plain(e).removesuffix(' *'):e for e in d.descendants() if isinstance(e,(ui.input,ui.select))}
    assert controls['Managing role'].value==role['id']
    assert controls['File Administrator role'].value==role['id']
    with user:next(e for e in d.descendants() if isinstance(e,ui.input) and plain(e)=='Name *').value='Renamed fixture unit'
    click(user,t('webui.open_editor.button.save_46081ed6'),d)
    await eventually(lambda:not d.value and user.pending_requests==0)
    saved=await api.get('org-units',unit['id'])
    assert saved['name']=='Renamed fixture unit'
    assert saved['managing_role_id']==saved['file_administrator_role_id']==role['id']
    assert not user.api_failures
