"""AFD-1–5: role choice, one upload batch, and activity without per-row calls."""
import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock

import pytest
from nicegui import ui

from frontend.webui.aggregation_file_drop import AggregationFileDrop
from frontend.webui.aggregation_recent_activity import AggregationRecentActivity
from frontend.webui.api_client import ApiError
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio


def api_stub(**kwargs):
    return SimpleNamespace(code_generation_bindings=AsyncMock(return_value={'items':[], 'total':0}), **kwargs)


@pytest.mark.parametrize('unknown',[False,True])
async def test_failed_drop_retains_original_bytes_and_retries_without_another_browser_upload(user,unknown):
    received=[]
    async def create(_,files,**kwargs):
        received.append((kwargs['submission_key'],kwargs['title'],[(n,c.read(),m) for n,c,m in files]))
        if len(received)==1:
            raise ApiError(503 if unknown else 422,'Lost response' if unknown else 'Invalid details',
                           creation_outcome=None if unknown else 'not-created')
        return 1
    api=api_stub(request=AsyncMock(return_value=[]),creation_role_options=AsyncMock(return_value=roles(1)),
                 create_records_from_file_drop=AsyncMock(side_effect=create))
    committed,state=AsyncMock(),{}
    @ui.page('/retained-drop')
    def page():
        with ui.column() as host:
            state['drop']=AggregationFileDrop(page=host,aggregation={'id':7,'owning_org_unit_id':1,'medium':'digital'},
                api=api,active=lambda:True,on_committed=committed,error_message=str)
            state['drop'].set_enabled(True)
    await user.open('/retained-drop')
    drop=state['drop'];drop.run_method=Mock()
    with user:
        await drop.choose_role(SimpleNamespace(args={'count':2,'separate':False,'filenames':['same.pdf','same.pdf']}))
    user.find(t('aggregation_file_drop.create_record')).click()
    await asyncio.sleep(.03)
    originals=[BytesIO(b'first'),BytesIO(b'second')]
    with user:
        drop.receive(SimpleNamespace(names=['same.pdf','same.pdf'],contents=originals,types=['application/pdf']*2))
    assert all(f.closed for f in originals)
    for _ in range(50):
        if drop.retry_dialog is not None:break
        await asyncio.sleep(.01)
    retained=[file for _,file,_ in drop.pending['files']]
    assert all(not f.closed for f in retained)
    await user.should_see(t('code_generation.status.files_retained'))
    if unknown:
        await user.should_not_see(t('code_generation.action.correct_details'))
        user.find(t('code_generation.action.retry_original')).click()
    else:
        user.find(t('code_generation.action.correct_details')).click()
        title=next(e for e in user.client.elements.values() if isinstance(e,ui.input))
        with user:title.set_value('Corrected title')
        user.find(t('aggregation_file_drop.create_record')).click()
    for _ in range(50):
        if committed.called:break
        await asyncio.sleep(.01)
    assert committed.await_count==1
    assert len(received)==2 and received[0][2]==received[1][2]==[
        ('same.pdf',b'first','application/pdf'),('same.pdf',b'second','application/pdf')]
    assert (received[0][0]==received[1][0]) is unknown
    assert received[1][1]==('same.pdf' if unknown else 'Corrected title')
    assert drop.run_method.call_args_list.count((('upload',),{}))==1
    assert all(f.closed for f in retained) and drop.pending is None



def move_file(user, original_index, direction):
    row=next(e for e in user.client.elements.values()
             if 'aggregation-drop-file' in e.classes and str(e.props['data-file-index'])==str(original_index))
    button=next(e for e in row.descendants() if isinstance(e,ui.button)
                and e.props.get('icon')==('arrow_upward' if direction<0 else 'arrow_downward'))
    button.mark(f'move-{button.id}')
    user.find(marker=f'move-{button.id}').click()


def roles(n):
    return [dict(role_id=i, org_unit_id=1 if i < 3 else 2, label=f'Role {i}') for i in range(1,n+1)]


@pytest.mark.parametrize('number_roles,separate', [(1, True),(1, False),(3, True),(3, False)])
async def test_drop_uses_one_atomic_request_and_only_eligible_role_choices(user, number_roles, separate):
    api = api_stub(request=AsyncMock(return_value=[]), creation_role_options=AsyncMock(return_value=roles(number_roles)),
                          create_records_from_file_drop=AsyncMock(return_value=2 if separate else 1))
    committed = AsyncMock()
    state = {}
    @ui.page('/drop')
    def page():
        with ui.column() as host:
            state['drop'] = AggregationFileDrop(page=host, aggregation={'id':7,'owning_org_unit_id':1,'medium':'digital'},
                                                api=api, active=lambda:True, on_committed=committed, error_message=str)
            state['drop'].set_enabled(True)
    await user.open('/drop')
    drop = state['drop']
    drop.run_method = Mock()
    with user:
        await drop.choose_role(SimpleNamespace(args={'count':2, 'separate':separate, 'filenames':['z-first.txt','a-second.txt']}))
    if number_roles > 1:
        selector = next(e for e in user.find(ui.select).elements if e.label==t('webui.open_record_draft_editor.select.create_for_857b2d59'))
        assert selector.options == {1:'Role 1', 2:'Role 2'}
        api.create_records_from_file_drop.assert_not_awaited()
        with user: selector.value = 2
        await asyncio.sleep(.05)
    if number_roles > 1 or not separate:
        inputs = [e for e in user.client.elements.values() if isinstance(e,ui.input)]
        assert len(inputs) == (0 if separate else 1)
        if not separate:
            assert inputs[0].value == 'z-first.txt'
        drop.run_method.assert_not_called()
        action = user.find(t('aggregation_file_drop.create_records' if separate else 'aggregation_file_drop.create_record'))
        action.click()
        # A queued second activation must not start another upload.
        action.click()
        await asyncio.sleep(.1)
    else:
        assert not any(isinstance(e,ui.dialog) for e in user.client.elements.values())
    assert drop.pending['role'] == (1 if number_roles == 1 else 2)
    drop.run_method.assert_called_once_with('upload')
    contents = [BytesIO(b'a'), BytesIO(b'b')]
    with user:
        await drop.save(SimpleNamespace(names=['z-first.txt','a-second.txt'],contents=contents,types=['text/plain']*2))
    api.create_records_from_file_drop.assert_awaited_once_with(7, list(zip(['z-first.txt','a-second.txt'],[ANY]*2,['text/plain']*2)),
                                                             separate_records=separate,creator_acl_role_id=1 if number_roles==1 else 2,
                                                             title=None if separate else 'z-first.txt',submission_key=ANY)
    committed.assert_awaited_once()
    assert all(content.closed for content in contents)
    assert drop.pending is None


@pytest.mark.parametrize('failure', ['physical','owner','upload','api','abandoned'])
async def test_drop_failures_do_not_refresh_or_save_partial_batches(user, failure):
    api = api_stub(request=AsyncMock(return_value=[]), creation_role_options=AsyncMock(return_value=[] if failure=='owner' else roles(1)),
                          create_records_from_file_drop=AsyncMock(side_effect=ApiError(422,'Rejected')))
    active = [True]
    committed = AsyncMock()
    state = {}
    @ui.page('/drop-failure')
    def page():
        with ui.column() as host:
            state['drop'] = AggregationFileDrop(page=host, aggregation={'id':7,'owning_org_unit_id':1,'medium':'physical' if failure=='physical' else 'digital'},
                                                api=api, active=lambda:active[0], on_committed=committed, error_message=str)
            state['drop'].set_enabled(True)
    await user.open('/drop-failure'); drop=state['drop']; drop.run_method=Mock()
    with user:
        await drop.choose_role(SimpleNamespace(args={'count':2,'separate':True}))
        if failure=='abandoned': active[0]=False
        await drop.save(SimpleNamespace(names=['a.txt'] if failure=='upload' else ['a.txt','b.txt'],
                                       contents=[BytesIO(b'a')] if failure=='upload' else [BytesIO(b'a'),BytesIO(b'b')],
                                       types=['text/plain'] if failure=='upload' else ['text/plain']*2))
    committed.assert_not_awaited()
    assert api.create_records_from_file_drop.await_count == (1 if failure=='api' else 0)


async def test_activity_preview_view_all_refresh_and_abandonment_use_batched_projection(user):
    items=[dict(id=i,title=f'Child {i}', record_number=f'R-{i}',_operation='CREATE',_activity_at='2026-11-17T12:00:00Z') for i in range(1,9)]
    api=api_stub(recent_resource_activity=AsyncMock(return_value=items), get=AsyncMock(return_value={'id':1,'title':'Child 1'}))
    opened=AsyncMock(); state={}; active=[True]
    @ui.page('/activity')
    async def page():
        state['panel']=AggregationRecentActivity(api=api,aggregation_id=7,active=lambda:active[0],
                          configuration={'DASHBOARD_RECENT_DAYS':30,'DASHBOARD_RECENT_ITEM_LIMIT':4},
                          format_timestamp=str,show_record_details=opened,error_message=str)
        await state['panel'].load()
    await user.open('/activity')
    api.recent_resource_activity.assert_awaited_once()
    assert api.recent_resource_activity.call_args.kwargs['aggregation_id']==7
    api.get.assert_not_awaited()
    assert len([e for e in user.client.elements.values() if 'dashboard-personal-item' in e.classes])==4
    with user: state['panel'].show_all()
    assert len([e for e in user.client.elements.values() if 'dashboard-personal-item' in e.classes])==12
    api.get.assert_not_awaited()
    with user: await state['panel'].open_record(items[0])
    api.get.assert_awaited_once_with('records',1); opened.assert_awaited_once()
    api.recent_resource_activity.return_value=[{**items[0],'title':'Newly created'}]
    with user: await state['panel'].load()
    assert state['panel'].items[0]['title']=='Newly created'
    active[0]=False; api.recent_resource_activity.return_value=[]
    with user: await state['panel'].load()
    assert state['panel'].items[0]['title']=='Newly created'
    assert api.recent_resource_activity.await_count==2
    with user: await state['panel'].open_record(items[0])
    api.get.assert_awaited_once_with('records',1)


@pytest.mark.parametrize('file_count,separate', [(1,True),(2,True),(2,False)])
async def test_one_eligible_choice_only_requires_combined_title_confirmation(user, file_count, separate):
    # The eligible role deliberately isn't first in the unfiltered options.
    effective_roles = [
        dict(role_id=10,org_unit_id=2,label='Other unit role'),
        dict(role_id=20,org_unit_id=1,label='Owning unit role'),
        dict(role_id=30,org_unit_id=3,label='Another unit role'),
    ]
    api = api_stub(request=AsyncMock(return_value=[]), creation_role_options=AsyncMock(return_value=effective_roles),
                          create_records_from_file_drop=AsyncMock(return_value=file_count if separate else 1))
    committed=AsyncMock();state={}
    @ui.page('/drop-one-eligible')
    def page():
        with ui.column() as host:
            state['drop']=AggregationFileDrop(page=host,aggregation={'id':7,'owning_org_unit_id':1,'medium':'digital'},
                                               api=api,active=lambda:True,on_committed=committed,error_message=str)
            state['drop'].set_enabled(True)
    await user.open('/drop-one-eligible')
    drop=state['drop'];drop.run_method=Mock()
    with user:await drop.choose_role(SimpleNamespace(args={'count':file_count,'separate':separate,'filenames':[f'file-{i}.txt' for i in range(file_count)]}))
    if not separate:
        assert not any(isinstance(e,ui.select) and e.label==t('webui.open_record_draft_editor.select.create_for_857b2d59') for e in user.client.elements.values())
        assert next(e for e in user.client.elements.values() if isinstance(e,ui.input)).value=='file-0.txt'
        drop.run_method.assert_not_called()
        user.find(t('aggregation_file_drop.create_record')).click()
        await asyncio.sleep(.1)
    else:
        assert not any(isinstance(e,ui.dialog) for e in user.client.elements.values())
    assert drop.pending['role']==20
    drop.run_method.assert_called_once_with('upload')
    names=[f'file-{i}.txt' for i in range(file_count)]
    contents=[BytesIO(b'content') for _ in names]
    with user:await drop.save(SimpleNamespace(names=names,contents=contents,types=['text/plain']*file_count))
    api.create_records_from_file_drop.assert_awaited_once_with(7,list(zip(names,[ANY]*file_count,['text/plain']*file_count)),
                                                              separate_records=separate,creator_acl_role_id=20,title=None if separate else 'file-0.txt',submission_key=ANY)
    committed.assert_awaited_once()
    assert all(content.closed for content in contents)


@pytest.mark.parametrize('number_roles', [1, 3])
@pytest.mark.parametrize('action', ['edit', 'reorder', 'cancel', 'dismiss', 'abandon'])
async def test_combined_title_requires_confirmation_and_preserves_files(user, number_roles, action):
    api = api_stub(request=AsyncMock(return_value=[]), creation_role_options=AsyncMock(return_value=roles(number_roles)),
                          create_records_from_file_drop=AsyncMock(return_value=1))
    committed = AsyncMock(); state = {}; active = [True]
    @ui.page('/confirm-title')
    def page():
        with ui.column() as host:
            state['drop'] = AggregationFileDrop(page=host,
                aggregation={'id':7,'owning_org_unit_id':1,'medium':'digital'},
                api=api,active=lambda:active[0],on_committed=committed,error_message=str)
            state['drop'].set_enabled(True)
    await user.open('/confirm-title')
    drop=state['drop']; drop.run_method=Mock()
    names=['z-first.pdf','a-second.pdf']
    with user:
        await drop.choose_role(SimpleNamespace(args={'count':2,'separate':False,'filenames':names}))
    title=next(iter(user.find(ui.input).elements))
    assert title.value==names[0]
    move_file(user,1,-1)
    assert title.value==names[1]
    move_file(user,1,1)
    assert title.value==names[0]
    move_file(user,1,-1)
    assert title.value==names[1]
    assert drop.pending['order']==[1,0]
    if number_roles > 1:
        selector=next(e for e in user.find(ui.select).elements if e.label==t('webui.open_record_draft_editor.select.create_for_857b2d59'))
        with user: selector.value=2
    # Even an upload delivered before confirmation cannot create records.
    premature=[BytesIO(b'first'),BytesIO(b'second')]
    with user: await drop.save(SimpleNamespace(names=names,contents=premature,types=['application/pdf']*2))
    assert all(content.closed for content in premature)
    api.create_records_from_file_drop.assert_not_awaited()
    drop.run_method.assert_not_called()
    button=next(e for e in user.find(ui.button).elements if e.text==t('aggregation_file_drop.create_record'))
    if action in ('edit','reorder'):
        with user: title.value='   '
        await asyncio.sleep(.05)
        assert not button.enabled
        if action=='edit':
            with user: title.value='  Confirmed report  '
            move_file(user,1,1)
            assert title.value=='  Confirmed report  '
            move_file(user,1,-1)
            assert title.value=='  Confirmed report  '
        else:
            with user: title.value=names[1]
            move_file(user,1,1)
            assert title.value==names[0]
            move_file(user,1,-1)
            assert title.value==names[1]
        await asyncio.sleep(.05)
        assert button.enabled
        user.find(t('aggregation_file_drop.create_record')).click()
        await asyncio.sleep(.1)
        drop.run_method.assert_called_once_with('upload')
        contents=[BytesIO(b'first'),BytesIO(b'second')]
        with user: await drop.save(SimpleNamespace(names=names,contents=contents,types=['application/pdf']*2))
        api.create_records_from_file_drop.assert_awaited_once_with(
            7,[(names[i],ANY,'application/pdf') for i in [1,0]],separate_records=False,
            creator_acl_role_id=1 if number_roles==1 else 2,title='Confirmed report' if action=='edit' else names[1],submission_key=ANY)
        committed.assert_awaited_once()
    else:
        if action=='cancel':
            user.find(t('common.action.cancel')).click()
        elif action=='dismiss':
            dialog=next(iter(user.find(ui.dialog).elements))
            with user: dialog.close()
        else:
            active[0]=False
            user.find(t('aggregation_file_drop.create_record')).click()
        await asyncio.sleep(.1)
        api.create_records_from_file_drop.assert_not_awaited()
        committed.assert_not_awaited()
        assert not any(call.args==('upload',) for call in drop.run_method.call_args_list)
        if action!='abandon': assert drop.pending is None


async def test_reorder_many_files_preserves_duplicate_names_and_distinct_content(user):
    seen={}
    async def create(_, files, **kwargs):
        seen['files']=[(name,content.read(),mime) for name,content,mime in files]
        seen['title']=kwargs['title']
        return 1
    api=api_stub(request=AsyncMock(return_value=[]), creation_role_options=AsyncMock(return_value=roles(1)),
                        create_records_from_file_drop=AsyncMock(side_effect=create))
    state={}
    @ui.page('/many-files')
    def page():
        with ui.column() as host:
            state['drop']=AggregationFileDrop(page=host,aggregation={'id':7,'owning_org_unit_id':1,'medium':'digital'},
                api=api,active=lambda:True,on_committed=AsyncMock(),error_message=str)
            state['drop'].set_enabled(True)
    await user.open('/many-files')
    drop=state['drop'];drop.run_method=Mock()
    names=['same.pdf','one.pdf','two.pdf','three.pdf','four.pdf','same.pdf']
    with user: await drop.choose_role(SimpleNamespace(args={'count':6,'separate':False,'filenames':names}))
    for _ in range(5):move_file(user,5,-1)
    order=[5,0,1,2,3,4]
    assert drop.pending['order']==order
    rows=[e for e in user.client.elements.values() if 'aggregation-drop-file' in e.classes]
    ordered=list(rows[0].parent_slot.children)
    assert [int(e.props['data-file-index']) for e in ordered]==order
    for rank,row in enumerate(ordered,1):
        assert next(e for e in row.descendants() if isinstance(e,ui.badge)).text==str(rank)
    first_up=next(e for e in ordered[0].descendants() if isinstance(e,ui.button) and e.props.get('icon')=='arrow_upward')
    last_down=next(e for e in ordered[-1].descendants() if isinstance(e,ui.button) and e.props.get('icon')=='arrow_downward')
    assert not first_up.enabled and not last_down.enabled
    api.create_records_from_file_drop.assert_not_awaited()
    user.find(t('aggregation_file_drop.create_record')).click()
    await asyncio.sleep(.1)
    contents=[BytesIO(f'bytes-{i}'.encode()) for i in range(6)]
    with user:await drop.save(SimpleNamespace(names=names,contents=contents,types=['application/pdf']*6))
    assert seen['files']==[(names[i],f'bytes-{i}'.encode(),'application/pdf') for i in order]
    assert seen['title']=='same.pdf'
    assert all(content.closed for content in contents)


@pytest.mark.parametrize("count,separate", [(1, True), (2, True), (2, False)])
async def test_one_role_and_usable_type_always_review_before_upload(user, count, separate):
    api = api_stub(request=AsyncMock(return_value=[{"id": 41, "name": "Invoice"}]),
                          creation_role_options=AsyncMock(return_value=roles(1)))
    @ui.page("/typed-drop")
    def page():
        with ui.column() as host:
            target = AggregationFileDrop(page=host, aggregation={"id": 7, "owning_org_unit_id": 1},
                                        api=api, active=lambda: True, on_committed=AsyncMock(), error_message=str)
            target.set_enabled(True)
    await user.open("/typed-drop")
    target = next(e for e in user.client.elements.values() if isinstance(e, AggregationFileDrop))
    target.run_method = Mock()
    with user:
        await target.choose_role(SimpleNamespace(args={"count": count, "separate": separate,
                                                       "filenames": ["a.pdf", "b.pdf"][:count]}))
    target.run_method.assert_not_called()
    await user.should_see(t("resource_types.ui.type") + " · " + t("resource_types.ui.unset"))
    user.find(t("common.action.cancel")).click()
    await asyncio.sleep(.05)
    assert target.pending is None
