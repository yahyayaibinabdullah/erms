"""Behavioural contracts for the Phase 6C shared owners and existing callers."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from frontend.webui.api_client import ApiError
from frontend.webui.entities import ENTITIES
from frontend.webui.tests.shared_controls_fixture import selector, personal, PersonalResourceState

@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    from nicegui import ui
    monkeypatch.setattr(ui, 'notify', Mock())

class Select:
    multiple=False
    _deleted=False
    def __init__(self):
        self.value=None;self.options={};self.events={};self._props={}
    def on(self,event,handler):self.events[event]=handler
    def update(self):pass

@pytest.mark.asyncio
async def test_selector_retains_selected_values_and_rejects_stale_reads():
    started,release=asyncio.Event(),asyncio.Event()
    async def page(resource,fields,query,**kwargs):
        assert kwargs['limit']==25
        if query=='older':started.set();await release.wait()
        return {'items':[{'id':2 if query=='older' else 3,'name':query}]}
    api=SimpleNamespace(relationship_page=page)
    control=Select();load=selector(api)(control,'users',('name',),('name',))
    control.value=1;control.options={1:'Selected person'}
    pending=asyncio.create_task(load('older'));await started.wait()
    await load('newer');release.set();await pending
    assert control.options=={1:'Selected person',3:'newer'}

@pytest.mark.asyncio
@pytest.mark.parametrize('deleted',[False,True])
async def test_selector_does_not_apply_abandoned_responses(deleted):
    started,release=asyncio.Event(),asyncio.Event();active=[True]
    async def page(*args,**kwargs):
        started.set();await release.wait();return {'items':[{'id':1,'name':'Late'}]}
    control=Select();load=selector(SimpleNamespace(relationship_page=page))(
        control,'users',('name',),('name',),active=lambda:active[0])
    pending=asyncio.create_task(load('late'));await started.wait()
    if deleted:control._deleted=True
    else:active[0]=False
    release.set();await pending
    assert control.options=={}

@pytest.mark.asyncio
async def test_selector_filters_exclusions_and_tracks_disabled_option_indices():
    api=SimpleNamespace(relationship_page=AsyncMock(return_value={'items':[
        {'id':1,'name':'Same'}, {'id':2,'name':'Same'}, {'id':3,'name':'Hidden'}]}))
    control=Select();load=selector(api)(control,'users',('name',),('name',),
        exclude_id=3,option_reason=lambda row:'Unavailable' if row['id']==2 else '')
    await load('Sa')
    assert control.options=={1:'Same',2:'Same · Unavailable'}
    assert control._props[':option-disable']=='opt => [1].includes(opt.value)'

@pytest.mark.asyncio
@pytest.mark.parametrize('resource',['profiles','security-levels'])
async def test_reference_selector_preserves_bounded_reference_endpoint(resource):
    api=SimpleNamespace(administration_reference_page=AsyncMock(return_value={'items':[]}))
    control=Select();await selector(api)(control,resource,('name',),('name',))('query')
    api.administration_reference_page.assert_awaited_once_with(resource,query='query',limit=25,
        sort='level_number' if resource=='security-levels' else 'name',filters=None)

@pytest.mark.asyncio
@pytest.mark.parametrize('change',['identity','resource'])
async def test_favourites_response_is_scoped_to_original_identity_and_destination(change):
    started,release=asyncio.Event(),asyncio.Event()
    response={'aggregations':[{'id':3}],'records':[{'id':4}],'application_configuration':{}}
    async def fetch():started.set();await release.wait();return response
    data=PersonalResourceState();data.resource='records';principal={'principal':object()}
    owner=personal(SimpleNamespace(favourites=fetch),data,principal,lambda:data.resource,AsyncMock())
    pending=asyncio.create_task(owner.reload_favourites());await started.wait()
    if change=='identity':principal['principal']=object()
    else:data.resource='dashboard'
    release.set();assert await pending is response
    assert data.favourite_ids=={'aggregations':set(),'records':set()}
    assert data.favourites=={'aggregations':[],'records':[]}

@pytest.mark.asyncio
@pytest.mark.parametrize('already_selected',[False,True])
async def test_favourite_write_failure_rolls_back_only_that_session(already_selected):
    api=SimpleNamespace(favourite=AsyncMock(side_effect=ApiError(503,'unavailable')),
                        unfavourite=AsyncMock(side_effect=ApiError(503,'unavailable')))
    data=PersonalResourceState();other=PersonalResourceState()
    if already_selected:data.favourite_ids['records'].add(7)
    owner=personal(api,data,{'principal':object()},lambda:'records',AsyncMock())
    button=Mock();tooltip=Mock()
    assert await owner.toggle_favourite('records',7,button=button,tooltip=tooltip)==already_selected
    assert owner.favourite_state('records',7)==already_selected
    assert other.favourite_ids['records']==set()
    button.disable.assert_called_once();button.enable.assert_called_once()

@pytest.mark.asyncio
async def test_accepted_favourite_write_invokes_async_refresh_and_updates_membership():
    api=SimpleNamespace(favourite=AsyncMock(),unfavourite=AsyncMock())
    data=PersonalResourceState();callback=AsyncMock()
    owner=personal(api,data,{'principal':object()},lambda:'records',AsyncMock())
    assert await owner.toggle_favourite('records',7,on_changed=callback)
    callback.assert_awaited_once_with(True)
    assert data.favourite_ids['records']=={7}
    assert not await owner.toggle_favourite('records',7)
    assert data.favourite_ids['records']==set()

@pytest.mark.asyncio
async def test_activity_snapshots_stay_separate_across_navigation():
    rows = {"aggregations": [{"id": 1}], "records": [{"id": 2}]}
    api = SimpleNamespace(recent_resource_activity=AsyncMock(side_effect=lambda key, **_: rows[key]))
    data = PersonalResourceState()
    owner = personal(api, data, {"principal": object()}, lambda: "records", AsyncMock())
    await owner.load_recent(ENTITIES["records"])
    data.leave_view()
    await owner.load_recent(ENTITIES["aggregations"])
    await owner.load_recent(ENTITIES["classifications"])
    assert data.recent_activity == rows
    assert all(call.kwargs == {"limit": 50} for call in api.recent_resource_activity.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["rapid_navigation", "language", "login"])
async def test_abandoned_activity_cannot_replace_current_snapshot(change):
    started, release = asyncio.Event(), asyncio.Event()

    async def read(*args, **kwargs):
        started.set()
        await release.wait()
        return [{"id": 1}]

    data = PersonalResourceState()
    identity = {"principal": object()}
    api = SimpleNamespace(recent_resource_activity=AsyncMock(side_effect=read))
    owner = personal(api, data, identity, lambda: "records", AsyncMock())
    older = asyncio.create_task(owner.load_recent(ENTITIES["records"]))
    await started.wait()
    if change == "language":
        identity["language"] = "ar"
    elif change == "login":
        identity["principal"] = object()
    else:
        data.leave_view()
        data.leave_view()  # Records -> Aggregations -> Records
    api.recent_resource_activity = AsyncMock(return_value=[{"id": 2}])
    await owner.load_recent(ENTITIES["records"])
    release.set()
    await older
    assert data.recent_activity == {"records": [{"id": 2}]}
