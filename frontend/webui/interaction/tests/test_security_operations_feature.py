"""Security operations periods, permissions, paging and resource destinations."""
import ast
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

def source():return ast.parse((Path(__file__).parents[2]/'security_operations.py').read_text())
def callback(name,scope):
    if name=='select_security_operations':
        from frontend.webui.security_operations import build_security_operations
        scope.update(principal=lambda:scope['auth_state'].get('principal'),
                     get_resource=lambda:scope['state'].get('resource'),
                     enter_security_operations=lambda:(scope['state'].update(resource='security-operations'),scope['collection_state'].update(rows=[],searched=True)))
        return build_security_operations(**{key:scope[key] for key in inspect.signature(build_security_operations).parameters})
    node=next(n for n in ast.walk(source()) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<security-operations>','exec'),scope)
    return scope[name]

def summary(events=None):
    return dict(total_security_events=len(events or []),total_denials=0,event_counts=[],
                recent_events=(events or [])[:10],denial_groups=[],full_privilege_roles=[],
                window_start='2026-01-01T00:00:00Z',window_end='2026-01-02T00:00:00Z')

async def setup(user,privileges=(),events=None):
    async def event_page(*, start_at, end_at, limit, offset):
        return (events or [])[offset:offset + limit]
    api=SimpleNamespace(security_summary=AsyncMock(return_value=summary(events)),
                        security_events=AsyncMock(side_effect=event_page),
                        security_reconciliation=AsyncMock(return_value={'hierarchy_violation_count':0,'findings':[]}))
    scope=dict(vars(host),api=api,state={},collection_state={},auth_state={'principal':{'global_privileges':list(privileges)}},register_navigation=Mock(),show_authenticated_view=Mock())
    for name in ['open_aggregation','select_record_details','select_organization_unit_details','select_role_details','select_user_details','select_classification_workspace']:scope[name]=AsyncMock()
    @ui.page('/security-contract')
    async def page():
        scope['page_client']=ui.context.client
        for name in ('title','subtitle','guidance'):scope[name]=ui.label('')
        for name in ('search_bar','aggregation_mode_bar','add_button','add_record_button'):scope[name]=ui.column()
        scope['table_container']=ui.column()
        await callback('select_security_operations',scope)()
    await user.open('/security-contract')
    return scope

async def settle():await asyncio.sleep(.15)
def click(user,key):user.find(t(key)).click()

@pytest.mark.parametrize('admin',[False,True])
async def test_periods_custom_validation_and_permission_scoped_reconciliation(user,admin):
    h=await setup(user,['authorization.administer'] if admin else [])
    h['api'].security_summary.assert_awaited_once_with(
        hours=24,start_at=None,end_at=None,recent_event_limit=10,denial_group_limit=11,
    )
    assert h['api'].security_reconciliation.await_count==int(admin)
    control=next(iter(user.find(ui.select).elements))
    with user:control.value='week'
    await settle();assert h['api'].security_summary.call_args.kwargs['hours']==168
    with user:control.value='custom'
    calls=h['api'].security_summary.await_count
    click(user,'webui.select_security_operations.button.apply_range_53faab3c');await settle()
    assert h['api'].security_summary.await_count==calls
    fields={e.props.get('label'):e for e in user.find(ui.input).elements}
    with user:
        fields[t('webui.select_security_operations.input.from_a135a152')].value='2026-01-02'
        fields[t('webui.select_security_operations.input.through_b5ed408a')].value='2026-01-03'
    click(user,'webui.select_security_operations.button.apply_range_53faab3c');await settle()
    request=h['api'].security_summary.call_args.kwargs
    assert request['start_at'].startswith('2026-01-02T00:00:00')
    assert request['end_at'].startswith('2026-01-03T23:59:59.999999')
    assert h['api'].security_reconciliation.await_count==(3 if admin else 0)

@pytest.mark.parametrize('boundary',['navigation','new_period'])
async def test_abandoned_summary_does_not_render(user,boundary):
    h=await setup(user);started=asyncio.Event();release=asyncio.Event()
    async def delayed(**kwargs):started.set();await release.wait();return summary([dict(operation='AUTHENTICATION_FAILED',occurred_at='2026-01-01',entity_label='Late protected target',entity_type='record',entity_id=9)])
    h['api'].security_summary.side_effect=delayed
    click(user,'webui.select_security_operations.button.refresh_aa2c487e');await asyncio.wait_for(started.wait(),3)
    if boundary=='navigation':h['state']['resource']='records'
    else:
        with user:next(iter(user.find(ui.select).elements)).value='custom'
    release.set();await settle();await user.should_not_see('Late protected target')

async def test_recent_event_paging_redaction_and_target_navigation(user):
    events=[dict(operation='AUTHENTICATION_FAILED',occurred_at='2026-01-01',entity_label=f'Event target {i}',entity_type='record',entity_id=i,redacted=i==0) for i in range(11)]
    h=await setup(user,events=events)
    await user.should_see('Event target 0');await user.should_not_see('Event target 10')
    redacted=next(e for e in user.find(ui.label).elements if e.text=='Event target 0');assert not redacted._event_listeners
    user.find('Event target 1').click();await settle();h['select_record_details'].assert_awaited_once_with(1)
    click(user,'webui.load_security_operations.button.next_1b5d6dc7');await settle();await user.should_see('Event target 10');await user.should_not_see('Event target 0')
    h['api'].security_events.assert_awaited_once_with(
        start_at='2026-01-01T00:00:00Z', end_at='2026-01-02T00:00:00Z', limit=10, offset=10,
    )
    click(user,'webui.load_security_operations.button.previous_49e3a635');await settle();await user.should_see('Event target 0')
    assert h['api'].security_summary.await_count == 1


@pytest.mark.parametrize('boundary', ['navigation', 'refresh', 'identity'])
async def test_abandoned_event_page_does_not_replace_current_view(user, boundary):
    events = [dict(operation='AUTHENTICATION_FAILED', occurred_at='2026-01-01',
                   entity_label=f'Event target {i}', entity_type='record', entity_id=i)
              for i in range(11)]
    h = await setup(user, events=events)
    started = asyncio.Event()
    release = asyncio.Event()

    async def delayed(**kwargs):
        started.set()
        await release.wait()
        return events[10:]

    h['api'].security_events.side_effect = delayed
    click(user, 'webui.load_security_operations.button.next_1b5d6dc7')
    await asyncio.wait_for(started.wait(), 3)
    if boundary == 'navigation':
        h['state']['resource'] = 'records'
    elif boundary == 'identity':
        h['auth_state']['principal'] = {'global_privileges': []}
    else:
        h['api'].security_summary.return_value = summary([])
        click(user, 'webui.select_security_operations.button.refresh_aa2c487e')
        await user.should_see(t('webui.render_security_event_cards.label.no_recent_security_events_in_this_period_6d8fd436'))
    release.set()
    await settle()
    await user.should_not_see('Event target 10')

@pytest.mark.parametrize('kind,target,args,kwargs',[
 ('aggregation','open_aggregation',({'id':7,'classification_scheme_id':3},),{}),('record','select_record_details',(7,),{}),
 ('org_unit','select_organization_unit_details',(7,),{}),('role','select_role_details',(7,),{}),('user','select_user_details',(7,),{}),
 ('classification_scheme','select_classification_workspace',(),{'initial_scheme_id':7}),('classification','select_classification_workspace',(),{'initial_scheme_id':3,'initial_classification_id':7}),
])
async def test_security_event_destinations(kind,target,args,kwargs):
    h=dict(vars(host),api=SimpleNamespace(get=AsyncMock(return_value={'id':7,'classification_scheme_id':3})))
    for name in ['open_aggregation','select_record_details','select_organization_unit_details','select_role_details','select_user_details','select_classification_workspace']:h[name]=AsyncMock()
    await callback('open_security_event_target',h)({'entity_type':kind,'entity_id':7})
    h[target].assert_awaited_once_with(*args,**kwargs)

@pytest.mark.parametrize('status',[403,404])
async def test_target_failure_preserves_existing_error_handling(monkeypatch,status):
    notice=Mock();monkeypatch.setattr(ui,'notify',notice)
    h=dict(vars(host),api=SimpleNamespace(get=AsyncMock(side_effect=ApiError(status,'Denied'))),open_aggregation=AsyncMock(),show_api_error=Mock())
    await callback('open_security_event_target',h)({'entity_type':'aggregation','entity_id':7})
    assert notice.call_count==(status==404);assert h['show_api_error'].call_count==(status==403)
