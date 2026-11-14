"""Legal-hold mutations and effective propagation using the disposable API."""
import pytest
from nicegui import ui
from frontend.webui.assembled.tests.test_application import assembled,login,current_page,drawer_buttons,click_one,eventually
from frontend.webui.assembled.tests.test_shared_entity_controls import plain
from frontend.webui.assembled.tests.test_security_feature import click,opened,saved
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

async def ready_details(user,old=None):
    await eventually(lambda:current_page(user)=='hold-details' and user.pending_requests==0 and any(plain(b)==t('webui.select_hold_details.button.edit_hold_d034b7c2') and b.id!=old for b in user.find(ui.button).elements))
    return next(b.id for b in user.find(ui.button).elements if plain(b)==t('webui.select_hold_details.button.edit_hold_d034b7c2'))

async def reason_confirm(user):
    await eventually(lambda:any(d.value and any(isinstance(b,ui.button) and b.props.get('icon')=='check' for b in d.descendants()) for d in user.find(ui.dialog).elements))
    d=max((d for d in user.find(ui.dialog).elements if d.value and any(isinstance(b,ui.button) and b.props.get('icon')=='check' for b in d.descendants())),key=lambda d:d.id)
    with user:next(e for e in d.descendants() if isinstance(e,ui.textarea)).value='Disposable hold verification'
    click_one(user,[b for b in d.descendants() if isinstance(b,ui.button) and b.props.get('icon')=='check'])
    await saved(user,d)

async def test_hold_edit_contributors_bulk_assignment_removal_and_deletion(assembled):
    user=assembled;await login(user);api=user.api_clients[0];owner=(await api.me())['user']['id']
    people=(await api.active_people('viewer',limit=25,offset=0))['items'];other=next(p['id'] for p in people if p['id']!=owner)
    hold=await api.create_hold(dict(code='PHASE6K',name='Hold fixture',valid_from='2020-01-01T00:00:00Z',valid_to=None,owner_user_id=owner,contributor_user_ids=[other],preserve_resource_state=False))
    identity=hold['id']
    click_one(user,[b for b in drawer_buttons(user) if plain(b)==t('navigation.item.holds')])
    await eventually(lambda:current_page(user)=='holds' and user.pending_requests==0)
    await eventually(lambda:any(b.props.get('icon')=='open_in_new' for b in user.find(ui.button).elements))
    click_one(user,[b for b in user.find(ui.button).elements if b.props.get('icon')=='open_in_new']);old=await ready_details(user)
    click(user,t('webui.select_hold_details.button.edit_hold_d034b7c2'));d=await opened(user)
    with user:next(e for e in d.descendants() if isinstance(e,ui.input) and plain(e)==t('webui.open_hold_editor.input.name_fc2e95e9')).value='Updated hold fixture'
    click(user,t('webui.open_hold_editor.button.save_hold_c7de035c'),d);await reason_confirm(user);old=await ready_details(user,old)
    assert (await api.hold(identity))['name']=='Updated hold fixture'
    click(user,t('webui.select_hold_details.button.manage_contributors_866ef148'));d=await opened(user)
    with user:
        next(e for e in d.descendants() if isinstance(e,ui.select)).value=[]
        next(e for e in d.descendants() if isinstance(e,ui.textarea)).value='Remove fixture contributor'
    click(user,t('webui.manage_contributors.button.save_contributors_9b6b56e2'),d);await saved(user,d);old=await ready_details(user,old)
    assert (await api.hold(identity))['contributors']==[]
    click(user,t('webui.select_hold_details.button.add_held_items_4cfdf56b'));d=await opened(user)
    with user:next(e for e in d.descendants() if isinstance(e,ui.input)).value='TEST-AGG'
    await eventually(lambda:user.pending_requests==0 and len([e for e in d.descendants() if isinstance(e,ui.checkbox)])==1)
    with user:
        next(e for e in d.descendants() if isinstance(e,ui.checkbox)).value=True
        next(e for e in d.descendants() if isinstance(e,ui.textarea)).value='Preserve fixture aggregation'
    click(user,t('webui.show_add_held_item.button.add_held_items_be6b0111'),d);await saved(user,d);old=await ready_details(user,old)
    assert not next(b for b in user.find(ui.button).elements if plain(b)==t('webui.select_hold_details.button.delete_hold_61877bfd')).enabled
    items=(await api.hold_held_items_page(identity,limit=25))['items'];assert len(items)==1
    effective=await api.effective_holds('aggregation',items[0]['resource_id']);assert any(h.get('hold_id')==identity for h in effective)
    await eventually(lambda:any(isinstance(e,ui.checkbox) for e in user.find(ui.checkbox).elements))
    with user:next(e for e in user.find(ui.checkbox).elements if e.visible).value=True
    click(user,t('webui.select_hold_details.button.remove_selected_16cdfb8a'));await reason_confirm(user);old=await ready_details(user,old)
    assert (await api.hold_held_items_page(identity,limit=25))['total']==0
    click(user,t('webui.select_hold_details.button.delete_hold_61877bfd'));await reason_confirm(user)
    await eventually(lambda:current_page(user)=='holds' and user.pending_requests==0 and any(plain(b)==t('webui.select_holds.button.create_hold_c7bae8dd') for b in user.find(ui.button).elements))
    assert (await api.holds_page(q='PHASE6K',limit=25))['total']==0
    assert not user.api_failures
