"""Indexer administration contracts; only synthetic keys enter this mock UI."""
import ast
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


def build(scope):
    from frontend.webui.text_indexers import build_text_indexers
    from frontend.webui.text_indexer_details import build_text_indexer_details
    from frontend.webui.text_indexer_credentials import reveal_text_indexer_key
    v=scope['_injected']
    common={k:v[k] for k in ('register_navigation','show_authenticated_view','search_bar','aggregation_mode_bar','add_button','add_record_button','guidance','title','subtitle','table_container','api','show_api_error','format_timestamp')}
    common.update(error_message=host.error_message,localized_lifecycle_value=host.localized_lifecycle_value,direction=lambda:v['current_direction']['value'])
    list_view=build_text_indexers(**common,enter=lambda:v['state'].update(resource='text-indexers',rows=[],searched=True,aggregation_detail=None),select_text_indexer_details=lambda *a,**kw:detail(*a,**kw),select_record_details=v['select_record_details'],show_components=v['show_components'])
    detail=build_text_indexer_details(**common,enter=lambda:v['state'].update(resource='text-indexer-details',rows=[],searched=True,aggregation_detail=None),select_text_indexers=list_view,breadcrumb_back=v['breadcrumb_back'])
    return list_view,detail,reveal_text_indexer_key


async def setup(user,*,detail=False,status='active',direction='ltr',read_error=False,diagnostic=None):
    indexer=dict(id=7,name='Indexer fixture',external_id='fixture-indexer',version=3,status=status,date_created='2026-01-01',active_credential_count=1,credential_count=1,last_used_at=None)
    credential=dict(id=11,name='Synthetic credential',credential_identifier='0'*26,status='active',date_created='2026-01-01',expires_at='2099-01-01')
    cp=dict(items=[credential],total=6,offset=0,limit=5,retention_days=90)
    api=SimpleNamespace(text_indexers=AsyncMock(return_value=[indexer]),text_indexers_health=AsyncMock(return_value={'metrics':{},'ready_for_search':True,'failed_documents':1}),text_indexer_diagnostics=AsyncMock(return_value=diagnostic or {}),text_indexer=AsyncMock(return_value=indexer),text_indexer_credentials=AsyncMock(return_value=cp),create_text_indexer=AsyncMock(return_value={'text_indexer':indexer,'credential':{'api_key':'synthetic-test-only'}}),set_text_indexer_status=AsyncMock(),create_text_indexer_credential=AsyncMock(return_value={'api_key':'synthetic-test-only'}),rotate_text_indexer_credential=AsyncMock(return_value={'api_key':'synthetic-test-only'}),revoke_text_indexer_credential=AsyncMock(),queue_text_indexers_backfill=AsyncMock(return_value={'drifted':1,'queued':1}),retry_failed_text_indexer_documents=AsyncMock(return_value={'examined':1,'queued':1}),get=AsyncMock(return_value={'id':1}))
    if read_error:(api.text_indexer if detail else api.text_indexers).side_effect=ApiError(403,'Denied')
    s=dict(api=api,state={},current_direction={'value':direction},register_navigation=Mock(),show_authenticated_view=Mock(),show_api_error=Mock(),select_record_details=AsyncMock(),select_entity=AsyncMock(),show_components=AsyncMock(),breadcrumb_back=AsyncMock(),format_timestamp=lambda v:'Fixed date')
    @ui.page('/indexer-test')
    async def page():
        for name in ('title','subtitle','guidance'):s[name]=ui.label()
        for name in ('search_bar','aggregation_mode_bar','add_button','add_record_button','table_container'):s[name]=ui.column()
        scope={'_injected':s};s['list'],s['detail'],s['reveal']=build(scope)
        await (s['detail'](7) if detail else s['list']())
    await user.open('/indexer-test')
    return api,s


def button(user,key,root=None):
    candidates=root.descendants() if root else user.find(ui.button).elements
    if root is None:
        def outside_dialog(b):
            while b.parent_slot:
                b=b.parent_slot.parent
                if isinstance(b,ui.dialog):return False
            return True
        candidates=[b for b in candidates if outside_dialog(b)]
    return next(b for b in candidates if isinstance(b,ui.button) and host.strip_diagnostic_metadata(b.text)==t(key))
def click(user,b):b.mark(f'indexer-{b.id}');user.find(marker=f'indexer-{b.id}').click()
def dialog(user):return max((d for d in user.find(ui.dialog).elements if d.value),key=lambda d:d.id)
async def settle():await asyncio.sleep(.15)
def field(root,label):return next(i for i in root.descendants() if isinstance(i,ui.input) and host.strip_diagnostic_metadata(i.label)==t(label))


@pytest.mark.parametrize('direction',['ltr','rtl'])
async def test_list_filter_and_initial_requests(user,direction):
    api,s=await setup(user,direction=direction)
    api.text_indexers.assert_awaited_once_with();api.text_indexers_health.assert_awaited_once_with()
    api.text_indexer_diagnostics.assert_awaited_once_with(limit=10,offset=0)
    with user:next(i for i in user.find(ui.input).elements).value='absent'
    await settle();await user.should_see(t('webui.render.label.no_matching_text_indexers_064a7cfd'))
    api.text_indexers.assert_awaited_once()
    assert s['state']['resource']=='text-indexers'


@pytest.mark.parametrize('operation',['backfill','retry'])
@pytest.mark.parametrize('failure',[False,True])
async def test_operational_payload_cancel_error_and_refresh(user,operation,failure):
    api,s=await setup(user)
    icon='playlist_add' if operation=='backfill' else 'replay'
    action=next(b for b in user.find(ui.button).elements if b.props.get('icon')==icon)
    method=api.queue_text_indexers_backfill if operation=='backfill' else api.retry_failed_text_indexer_documents
    click(user,action);await settle();d=dialog(user)
    cancel=next(b for b in d.descendants() if isinstance(b,ui.button) and b.props.get('flat'))
    click(user,cancel);await settle();method.assert_not_awaited()
    click(user,action);await settle();d=dialog(user)
    with user:next(i for i in d.descendants() if isinstance(i,ui.number)).value=17
    if failure:method.side_effect=ApiError(403,'Denied')
    click(user,next(b for b in d.descendants() if isinstance(b,ui.button) and b.props.get('icon')==icon));await settle()
    method.assert_awaited_once_with(17)
    assert d.value==failure
    assert api.text_indexers.await_count==(1 if failure else 2)
    assert s['show_api_error'].call_count==int(failure)


@pytest.mark.parametrize('failure',[False,True])
async def test_create_payload_and_one_time_reveal(user,failure):
    api,s=await setup(user)
    click(user,button(user,'webui.select_text_indexers.button.add_text_indexer_fd6584b1'));await settle();d=dialog(user)
    values={'webui.add_text_indexer_dialog.input.deployment_or_pool_name_7539da84':' Fixture ','webui.add_text_indexer_dialog.input.immutable_external_id_0e9e9051':' external ','webui.add_text_indexer_dialog.input.initial_credential_name_33daef5e':' initial ','webui.add_text_indexer_dialog.input.credential_expiry_iso_8601_e10ffe03':'2099-01-01T00:00:00Z'}
    with user:
        for key,value in values.items():field(d,key).value=value
    if failure:api.create_text_indexer.side_effect=ApiError(403,'Denied')
    click(user,button(user,'webui.add_text_indexer_dialog.button.create_and_generate_key_a5f16e9e',d));await settle()
    api.create_text_indexer.assert_awaited_once_with(dict(name='Fixture',external_id='external',credential_name='initial',expires_at='2099-01-01T00:00:00Z'))
    assert d.value==failure
    if not failure:
        assert 'api_key' not in api.create_text_indexer.return_value['credential']
        reveal=dialog(user);assert reveal.props.get('persistent')
        click(user,button(user,'webui.reveal_text_indexer_key.button.i_have_stored_it_safely_e3a69b9d',reveal));await settle()
        api.text_indexer.assert_awaited_once_with(7)


@pytest.mark.parametrize('status,action',[('active','suspend'),('suspended','unsuspend')])
async def test_status_write_and_credential_permission(user,status,action):
    api,s=await setup(user,detail=True,status=status)
    generate=button(user,'webui.select_text_indexer_details.button.generate_api_key_35bdc780')
    assert generate.enabled==(status=='active')
    icon='pause_circle' if status=='active' else 'play_circle'
    click(user,next(b for b in user.find(ui.button).elements if b.props.get('icon')==icon));await settle()
    api.set_text_indexer_status.assert_awaited_once_with(7,3,action)
    assert api.text_indexer.await_count==2


async def test_credential_server_paging_filter_and_read_failure(user):
    api,s=await setup(user,detail=True)
    click(user,button(user,'webui.select_text_indexer_details.button.next_e284c9ef'));await settle()
    api.text_indexer_credentials.assert_awaited_with(7,history='all',limit=5,offset=5)
    with user:next(e for e in user.find(ui.select).elements).value='history'
    await settle();api.text_indexer_credentials.assert_awaited_with(7,history='history',limit=5,offset=0)
    api.text_indexer_credentials.side_effect=ApiError(403,'Denied')
    click(user,button(user,'webui.select_text_indexer_details.button.next_e284c9ef'));await settle()
    s['show_api_error'].assert_called_once()


@pytest.mark.parametrize('detail',[False,True])
async def test_read_failure_preserves_error_behavior(user,detail):
    api,s=await setup(user,detail=detail,read_error=True)
    assert not any(isinstance(e,ui.card) for e in s['table_container'].descendants())
    if not detail:button(user,'webui.select_text_indexers.button.try_again_f7ef4536')


@pytest.mark.parametrize('operation',['generate','rotate','revoke'])
@pytest.mark.parametrize('failure',[False,True])
async def test_credential_mutation_cancel_error_and_refresh(user,operation,failure):
    api,s=await setup(user,detail=True)
    open_key={'generate':'webui.select_text_indexer_details.button.generate_api_key_35bdc780','rotate':'webui.render_credentials.button.rotate_1496c92c','revoke':'webui.render_credentials.button.revoke_4fc0db3b'}[operation]
    method=getattr(api,{'generate':'create_text_indexer_credential','rotate':'rotate_text_indexer_credential','revoke':'revoke_text_indexer_credential'}[operation])
    click(user,button(user,open_key));await settle();d=dialog(user)
    click(user,next(b for b in d.descendants() if isinstance(b,ui.button) and b.props.get('flat')));await settle();method.assert_not_awaited()
    click(user,button(user,open_key));await settle();d=dialog(user)
    if operation!='revoke':
        with user:
            field(d,'webui.credential_dialog.input.credential_name_b670464d').value=' Name '
            field(d,'webui.credential_dialog.input.expiry_iso_8601_222d3b9f').value='2099-01-01T00:00:00Z'
            if operation=='rotate':field(d,'webui.credential_dialog.input.old_key_overlap_until_optional_maximum_7_d_eec9eb31').value='2098-12-31T00:00:00Z'
    if failure:method.side_effect=ApiError(403,'Denied')
    click(user,next(b for b in d.descendants() if isinstance(b,ui.button) and b.props.get('icon')==('block' if operation=='revoke' else 'key')));await settle()
    payload={'name':'Name','expires_at':'2099-01-01T00:00:00Z'}
    if operation=='rotate':payload['overlap_until']='2098-12-31T00:00:00Z'
    method.assert_awaited_once_with(*((7,11) if operation=='revoke' else (7,11,payload) if operation=='rotate' else (7,payload)))
    assert d.value==failure
    if failure:s['show_api_error'].assert_called_once()
    elif operation!='revoke':
        assert 'api_key' not in method.return_value
        click(user,button(user,'webui.reveal_text_indexer_key.button.i_have_stored_it_safely_e3a69b9d',dialog(user)));await settle()
    assert api.text_indexer.await_count==(1 if failure else 2)


@pytest.mark.parametrize('allowed',[False,True])
async def test_diagnostics_paging_permission_and_destination_links(user,allowed):
    failure=dict(digital_component_id=9,record_id=1,record_number='REC-FIXTURE',component_name='Fixture.txt',can_open=allowed)
    api,s=await setup(user,diagnostic={'failures':{'items':[failure],'total':11}})
    diagnostic_card=next(c for c in user.find(ui.card).elements if any(isinstance(e,ui.label) and host.strip_diagnostic_metadata(e.text)==t('webui.render_failure_diagnostics.label.failure_diagnostics_e8ffa8d8') for e in c.descendants()))
    click(user,button(user,'webui.render_failure_diagnostics.button.next_856cdffc',diagnostic_card));await settle()
    api.text_indexer_diagnostics.assert_awaited_with(limit=10,offset=10)
    if allowed:
        click(user,next(b for b in user.find(ui.button).elements if b.props.get('icon')=='description'));await settle()
        s['select_record_details'].assert_awaited_once_with(1)
        click(user,next(b for b in user.find(ui.button).elements if b.props.get('icon')=='attachment'));await settle()
        api.get.assert_awaited_once_with('records',1)
        s['show_components'].assert_awaited_once_with({'id':1},focused_component_id=9)
    else:
        assert not any(b.props.get('icon') in {'description','attachment'} for b in user.find(ui.button).elements)
    api.text_indexer_diagnostics.side_effect=ApiError(403,'Denied')
    click(user,button(user,'webui.render_failure_diagnostics.button.refresh_diagnostics_83e70efa'));await settle()
    s['show_api_error'].assert_called_once()
