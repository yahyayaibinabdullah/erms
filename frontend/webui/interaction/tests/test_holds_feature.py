"""Legal-hold dialogs preserve reasons, authority, versions and resource returns."""
import ast,asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
from nicegui import ui
from frontend.webui import app as host
from frontend.webui import hold_editor, hold_resources, holds_people
from frontend.webui.api_client import ApiError

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio
NAMES=('hold_reason_dialog','open_hold_editor','add_resource_to_hold_dialog','show_effective_holds_dialog')

def build(values):
    nodes={n.name:n for n in [n for module in (hold_editor,hold_resources) for n in ast.walk(ast.parse(Path(module.__file__).read_text()))] if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in NAMES}
    scope=dict(vars(host));scope.update(values)
    exec(compile(ast.Module(body=[nodes[n] for n in NAMES],type_ignores=[]),host.__file__,'exec'),scope)
    return scope

async def setup(user):
    api=SimpleNamespace(create_hold=AsyncMock(return_value={'id':7}),update_hold=AsyncMock(return_value={'id':7,'version':4}),replace_hold_contributors=AsyncMock(return_value={'id':7,'version':5}),holds_page=AsyncMock(return_value={'items':[{'id':7,'code':'FIX','name':'Fixture','capabilities':{'manage_held_items':True}},{'id':8,'code':'NO','name':'Denied','capabilities':{}}],'total':26}),add_resource_to_hold=AsyncMock(),remove_hold_held_item=AsyncMock(),get=AsyncMock(return_value={'id':9}))
    values=dict(api=api,bind_remote_people_select=Mock(side_effect=lambda *a,**k:AsyncMock()),select_hold_details=AsyncMock(),open_aggregation=AsyncMock())
    @ui.page('/hold-feature')
    def page():values.update(build(values))
    await user.open('/hold-feature');return api,values

def click(user,button):button.mark(f'hold-{button.id}');user.find(marker=f'hold-{button.id}').click()
def buttons(dialog,icon):return [b for b in dialog.descendants() if isinstance(b,ui.button) and b.props.get('icon')==icon]
def opened(user):return max((d for d in user.find(ui.dialog).elements if d.value),key=lambda d:d.id)
async def settle():await asyncio.sleep(.1)

@pytest.mark.parametrize('kind',['sync','async','error'])
async def test_reason_validation_async_or_sync_action_and_api_error(user,kind):
    api,v=await setup(user);action=Mock() if kind=='sync' else AsyncMock()
    if kind=='error':action.side_effect=ApiError(409,'Conflict')
    with user:await v['hold_reason_dialog']('Fixture','Confirm',action)
    d=opened(user);submit=buttons(d,'check')[0];click(user,submit);await settle();action.assert_not_called()
    with user:next(e for e in d.descendants() if isinstance(e,ui.textarea)).value='  Fixture reason  '
    click(user,submit);await settle();action.assert_called_once_with('Fixture reason');assert d.value==(kind=='error')

@pytest.mark.parametrize('editing',[False,True])
@pytest.mark.parametrize('failure',[False,True])
async def test_editor_validation_owner_exclusion_version_and_contributor_update(user,editing,failure):
    api,v=await setup(user)
    hold={'id':7,'version':3,'code':'FIX','name':'Fixture','owner_user_id':1,'owner':{'id':1,'name':'Owner','email':'owner@test.invalid'},'contributors':[{'id':2,'name':'Contributor','email':'contributor@test.invalid'}],'valid_from':'2026-01-01T00:00:00+00:00','valid_to':None,'description':'Original','preserve_resource_state':False} if editing else None
    with user:await v['open_hold_editor'](hold)
    d=opened(user);inputs=[e for e in d.descendants() if isinstance(e,ui.input) and not isinstance(e,ui.textarea)]
    save=buttons(d,'save')[0]
    if not editing:
        click(user,save);await settle();api.create_hold.assert_not_awaited()
    selectors=[e for e in d.descendants() if isinstance(e,ui.select)];owner,contributors=selectors
    with user:
        inputs[0].value='  FIX  ';inputs[1].value=' Updated ';inputs[2].value='2026-01-01T00:00';inputs[3].value=''
        owner.options={1:'Owner',2:'Contributor'};owner.value=1
        contributors.options={2:'Contributor',3:'New contributor'};contributors.value=[2,3]
        next(e for e in d.descendants() if isinstance(e,ui.checkbox)).value=True
    method=api.update_hold if editing else api.create_hold
    if failure:method.side_effect=ApiError(409,'Conflict')
    click(user,save);await settle()
    if editing:
        reason=opened(user);assert reason is not d
        with user:next(e for e in reason.descendants() if isinstance(e,ui.textarea)).value=' Fixture reason '
        click(user,buttons(reason,'check')[0]);await settle()
    assert method.await_count==1
    args=method.await_args.args;payload=args[2] if editing else args[0]
    assert payload['code']=='FIX' and payload['name']=='Updated' and payload['owner_user_id']==1 and payload['preserve_resource_state']
    assert payload['valid_from'].endswith('+00:00') and payload['valid_to'] is None
    if editing:
        assert args[:2]==(7,3) and args[3]=='Fixture reason'
        if not failure:api.replace_hold_contributors.assert_awaited_once_with(7,4,[2,3],'Fixture reason')
    else:assert payload['contributor_user_ids']==[2,3]
    assert d.value==failure
    assert v['select_hold_details'].await_count==int(not failure)

@pytest.mark.parametrize('failure',[False,True])
async def test_resource_attachment_bounded_selection_reason_gate_and_refresh(user,failure):
    api,v=await setup(user);refresh=AsyncMock()
    with user:await v['add_resource_to_hold_dialog']('record',11,refresh)
    await settle();d=opened(user);select=next(e for e in d.descendants() if isinstance(e,ui.select));assert select.options=={7:'FIX — Fixture'}
    api.holds_page.assert_awaited_once_with(q=None,limit=25,offset=0)
    submit=buttons(d,'add_link')[0];click(user,submit);await settle();api.add_resource_to_hold.assert_not_awaited()
    with user:select.value=7;next(e for e in d.descendants() if isinstance(e,ui.textarea)).value=' Fixture reason '
    if failure:api.add_resource_to_hold.side_effect=ApiError(409,'Conflict')
    click(user,submit);await settle();api.add_resource_to_hold.assert_awaited_once_with('record',11,7,'Fixture reason')
    assert refresh.await_count==int(not failure) and d.value==failure

@pytest.mark.parametrize('kind',['direct','inherited','restricted'])
async def test_effective_hold_authority_links_and_direct_removal(user,kind):
    api,v=await setup(user);refresh=AsyncMock()
    entry={'source':'inherited'} if kind=='restricted' else dict(hold_id=7,code='FIX',name='Fixture',source=kind,preserve_resource_state=True,is_direct=kind=='direct',can_manage_held_items=kind=='direct',direct_assignment_version=4,is_inherited=kind=='inherited',nearest_assigned_aggregation_id=9)
    with user:v['show_effective_holds_dialog']([entry],'record',11,refresh)
    d=opened(user)
    assert len(buttons(d,'link_off'))==int(kind=='direct')
    assert len(buttons(d,'account_tree'))==int(kind=='inherited')
    if kind=='restricted':assert not buttons(d,'open_in_new');return
    if kind=='inherited':
        click(user,buttons(d,'account_tree')[0]);await settle();api.get.assert_awaited_once_with('aggregations',9);v['open_aggregation'].assert_awaited_once_with({'id':9});return
    click(user,buttons(d,'link_off')[0]);await settle();reason=opened(user)
    with user:next(e for e in reason.descendants() if isinstance(e,ui.textarea)).value=' Remove reason '
    click(user,buttons(reason,'check')[0]);await settle()
    api.remove_hold_held_item.assert_awaited_once_with(7,'record',11,4,'Remove reason');refresh.assert_awaited_once();assert not d.value

def bind_people(values,control,**kwargs):
    node=next(n for n in ast.walk(ast.parse(Path(holds_people.__file__).read_text())) if isinstance(n,ast.FunctionDef) and n.name=='bind_remote_people_select')
    scope=dict(vars(host));scope.update(values)
    exec(compile(ast.Module(body=[node],type_ignores=[]),host.__file__,'exec'),scope)
    return scope['bind_remote_people_select'](control,**kwargs)

async def test_people_typeahead_retains_selection_excludes_owner_and_bounds_requests(user):
    api,v=await setup(user);api.active_people=AsyncMock(return_value={'items':[{'id':2,'name':'Owner','email':'owner@test.invalid'},{'id':3,'name':'Match','email':'match@test.invalid'}]})
    with user:
        select=ui.select({1:'Selected',9:'Unselected'},value=[1],multiple=True)
        load=bind_people(v,select,excluded_ids=lambda:{2})
        await load('x')
    assert select.options=={1:'Selected'};api.active_people.assert_not_awaited()
    with user:await load(' match ')
    api.active_people.assert_awaited_once_with('match',limit=25,offset=0)
    assert select.value==[1] and select.options=={1:'Selected',3:'Match — match@test.invalid'}

async def test_people_typeahead_discards_outdated_response(user):
    api,v=await setup(user);gate=asyncio.Event();started=asyncio.Event()
    async def lookup(query,**kwargs):
        if query=='old':started.set();await gate.wait()
        return {'items':[{'id':2 if query=='old' else 3,'name':query,'email':'fixture@test.invalid'}]}
    api.active_people=AsyncMock(side_effect=lookup)
    with user:
        select=ui.select({},value=None);load=bind_people(v,select)
        slow=asyncio.create_task(load('old'));await started.wait();await load('latest');gate.set();await slow
    assert select.options=={3:'latest — fixture@test.invalid'}
