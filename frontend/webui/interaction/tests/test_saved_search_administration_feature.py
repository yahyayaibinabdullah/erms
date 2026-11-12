"""Saved-search administration permissions, bounded paging and late responses."""
import ast
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
from nicegui import ui
from frontend.webui import app as host
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message_plain as t
pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio

def build(scope):
    from frontend.webui.saved_search_administration import build_saved_search_administration
    scope.update(advanced_search_state=scope['state'],
        get_principal=lambda:scope['auth_state'].get('principal'),
        get_resource=lambda:scope['state'].get('resource'),
        enter_saved_administration=lambda page:scope['state'].update(resource=page))
    return build_saved_search_administration(**{key:scope[key] for key in inspect.signature(build_saved_search_administration).parameters})

def row(i):return {'id':i,'name':f'Saved {i:02}','resource_type':'record','owner':{'name':'Owner'},'version':1,'capabilities':{'delete':False}}
async def setup(user,allowed=True):
    async def page(**params):return {'items':[row(i) for i in range(params['offset'],min(26,params['offset']+params['limit']))],'total':26}
    h=dict(vars(host),state={},collection_state={},aggregation_state={},auth_state={'principal':{'global_privileges':['search.saved_search.administer'] if allowed else []}},api=SimpleNamespace(saved_search_administration=AsyncMock(side_effect=page)),register_navigation=Mock(),show_authenticated_view=Mock(),error_message=lambda error:'Query administration unavailable',format_timestamp=lambda value:'Fixed date',select_advanced_search=AsyncMock())
    @ui.page('/saved-admin-contract')
    async def screen():
        for name in ('title','subtitle','guidance'):h[name]=ui.label('')
        for name in ('search_bar','aggregation_mode_bar','add_button','add_record_button','table_container'):h[name]=ui.column()
        h['open']=build(h);await h['open']()
    await user.open('/saved-admin-contract');return h

async def test_admin_restricted_entry_never_fetches(user):
    h=await setup(user,False);h['api'].saved_search_administration.assert_not_awaited();assert h['state']=={}

async def test_admin_paging_and_edit_destination_keep_selected_identity(user):
    h=await setup(user);await user.should_see('Saved 00');await user.should_not_see('Saved 25')
    user.find(t('webui.open_saved_search_dialog.button.next_ba38d6aa')).click();await user.should_see('Saved 25');await user.should_not_see('Saved 00')
    h['api'].saved_search_administration.assert_awaited_with(limit=25,offset=25)
    button=next(e for e in user.client.elements.values() if isinstance(e,ui.button) and e.props.get('icon')=='edit');button.mark('edit-row');user.find(marker='edit-row').click();await asyncio.sleep(.1)
    assert h['state']['admin_saved_search_id']==25;h['select_advanced_search'].assert_awaited_once_with()

async def test_admin_paging_preserves_applied_name_and_owner(user):
    h = await setup(user)
    fetch = h['api'].saved_search_administration
    name = next(i for i in user.find(ui.input).elements
                if i.label == t('webui.open_saved_search_dialog.input.search_saved_searches_3352fa10'))
    owner = next(i for i in user.find(ui.input).elements if i.label == t('saved_search.administration.filter.owner'))
    apply = 'webui.open_saved_search_dialog.button.apply_filters_63a71659'
    with user:
        name.value = 'Saved'
        owner.value = 'Owner'
    user.find(t(apply)).click()
    await asyncio.sleep(.1)
    fetch.assert_awaited_with(q='Saved', owner_q='Owner', limit=25, offset=0)
    with user:
        name.value = 'Draft'
        owner.value = 'Another'
    user.find(t('webui.open_saved_search_dialog.button.next_ba38d6aa')).click()
    await user.should_see('Saved 25')
    fetch.assert_awaited_with(q='Saved', owner_q='Owner', limit=25, offset=25)
    assert (name.value, owner.value) == ('Draft', 'Another')
    user.find(t(apply)).click()
    await user.should_see('Saved 00')
    fetch.assert_awaited_with(q='Draft', owner_q='Another', limit=25, offset=0)

@pytest.mark.parametrize('outcome',['navigation','newer','error'])
async def test_admin_late_and_failed_filter_responses(user,outcome):
    h=await setup(user);started=asyncio.Event();release=asyncio.Event()
    async def delayed(**params):
        started.set();await release.wait()
        if outcome=='error':raise ApiError(503,'Unavailable')
        return {'items':[row(99)],'total':1}
    h['api'].saved_search_administration.side_effect=delayed
    user.find(t('webui.open_saved_search_dialog.button.apply_filters_63a71659')).click();await asyncio.wait_for(started.wait(),3)
    if outcome=='navigation':h['state']['resource']='records'
    elif outcome=='newer':
        h['api'].saved_search_administration.side_effect=None;h['api'].saved_search_administration.return_value={'items':[row(88)],'total':1}
        user.find(t('webui.open_saved_search_dialog.button.apply_filters_63a71659')).click();await user.should_see('Saved 88')
    release.set();await asyncio.sleep(.15)
    if outcome=='error':await user.should_see('Query administration unavailable')
    else:await user.should_not_see('Saved 99')
