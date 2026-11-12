"""Global-search paging, authorized component context, errors and lifecycle."""
import ast
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from nicegui import ui
from frontend.webui import app as host
from frontend.webui.api_client import ApiError
from frontend.webui.global_search_state import new_global_search_state
from frontend.webui.i18n_catalogue import render_message_plain as t

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio
NAMES=['global_search_payload','render_safe_snippet','copy_diagnostic_json','render_search_diagnostics','render_global_search_results','change_global_search_page','remember_global_result','set_global_result_expansion','open_global_record_from_result','open_global_aggregation_from_result','open_global_record','open_global_aggregation','run_global_search','clear_global_search_session']

def build(scope):
    from frontend.webui.global_search import build_global_search
    scope.update(global_search_state=scope['state'],
        get_principal=lambda:scope['auth_state'].get('principal'),
        get_resource=lambda:scope['state']['resource'],
        enter_global_search=lambda:scope['state'].update(resource='full-text-search'),
        discard_navigation_guard=lambda:scope['state'].pop('discard_navigation_guard',None),
        clear_advanced_workspace=lambda:scope['state'].pop('advanced_search_workspace',None),
        invalidate_advanced_session=lambda:scope['state'].__setitem__('advanced_search_session_revision',scope['state'].get('advanced_search_session_revision',0)+1),
        clear_collection_results=lambda:scope['collection_state'].update(entity_result_states={}))
    functions=build_global_search(**{key:scope[key] for key in inspect.signature(build_global_search).parameters})
    scope.update(zip(NAMES,functions))

def item(identifier=1,kind='aggregation'):
    return {'type':kind,kind:{'id':identifier,'title':f'Result {identifier}'},'matching_components':[{'id':7,'snippet':'Safe ⟦match⟧'}] if kind=='record' else []}

async def setup(user,items=None,privileges=None):
    state=new_global_search_state('Example')
    state['resource']='full-text-search'
    if items:
        state['global_search_streams']['all']=(items,None)
        state['global_search_totals']={
            'records':sum(row['type']=='record' for row in items),
            'aggregations':sum(row['type']=='aggregation' for row in items),
        }
    s=dict(vars(host),state=state,collection_state={},auth_state={'principal':{'global_privileges':privileges or []}},register_navigation=Mock(),show_authenticated_view=Mock(),restore_compact_result_anchor=Mock(),select_record_details=AsyncMock(),open_aggregation=AsyncMock(),error_message=lambda e:'Search unavailable',api=SimpleNamespace(full_text_search=AsyncMock(return_value={'items':[]}),resource_capabilities=AsyncMock(return_value={'list_components':True,'view_component':True}),component_page=AsyncMock(return_value={'items':[{'id':7,'mime_type':'image/png'}]})))
    s['rendered']=[]
    def compact(resource,row,**kwargs):s['rendered'].append((resource,row,kwargs));ui.label(row['title'])
    s['render_compact_resource_result']=compact
    @ui.page('/global-search-contract')
    def page():
        for name in ('title','subtitle'):s[name]=ui.label('')
        s['global_search_input']=ui.input()
        for name in ('search_bar','aggregation_mode_bar','add_button','add_record_button','table_container'):s[name]=ui.column()
        build(s);s['render_global_search_results']()
    await user.open('/global-search-contract');return s

async def test_cursor_paging_keeps_server_bound_and_stops_unchanged_cursor(user):
    s=await setup(user,[item(i) for i in range(10)])
    streams=s['state']['global_search_streams']
    streams['all']=(streams['all'][0],'next')
    s['api'].full_text_search.return_value={'items':[item(10)],'next_cursor':'next'}
    with user:await s['change_global_search_page'](2)
    assert s['state']['global_search_page']==2
    assert s['api'].full_text_search.await_args.args[0]['limit']==10
    assert s['api'].full_text_search.await_args.args[0]['cursor']=='next'
    assert s['api'].full_text_search.await_count==1
    assert streams['all'][1] is None
    await user.should_see('Result 10');await user.should_not_see('Result 0')

def click_tab(user, key, count):
    label=t(key,count=count)
    button=next(button for button in user.find(ui.button).elements if button.text == label)
    button.mark('search-tab')
    user.find(marker='search-tab').click()


@pytest.mark.parametrize('records', [3, 28])
async def test_totals_and_record_pages_do_not_depend_on_mixed_cursor(user,records):
    s=await setup(user)
    search=s['api'].full_text_search
    search.return_value={
        'items':[item(i) for i in range(10)], 'next_cursor':'mixed-next',
        'totals':{'records':records,'aggregations':97},
    }
    with user:await s['run_global_search']('Example',load_more=True)
    assert search.await_args.args[0]['include_totals'] is True
    await user.should_see(t('global_search.filter.all',count=records+97))
    await user.should_see(t('global_search.filter.aggregations',count=97))
    search.return_value={
        'items':[item(i,'record') for i in range(30,30+min(records,10))],
        'next_cursor':'record-next' if records>10 else None,
    }
    click_tab(user,'global_search.filter.records',records)
    await user.should_see('Result 30')
    first_page=search.await_args.args[0]
    assert first_page=={'result_types':['records'],'record_where':{'full_text':{'query':'Example'}},'limit':10}
    if records>10:
        search.return_value={'items':[item(i,'record') for i in range(40,50)],'next_cursor':'record-last'}
    with user:
        await asyncio.gather(s['change_global_search_page'](2), s['change_global_search_page'](2))
    if records>10:
        assert search.await_count==3
        assert search.await_args.args[0]=={**first_page,'cursor':'record-next'}
        await user.should_see('Result 40')
        await user.should_not_see('Result 30')
        with user:await s['change_global_search_page'](1)
        await user.should_see('Result 30')
        assert search.await_count==3
    else:
        next_button=next(button for button in user.find(ui.button).elements if button.props.get('icon')=='chevron_right')
        assert not next_button.enabled
        assert search.await_count==2
    await user.should_see(t('global_search.filter.records',count=records))
    await user.should_see(t('global_search.filter.aggregations',count=97))
    click_tab(user,'global_search.filter.all',records+97)
    await user.should_see('Result 0')
    assert search.await_count==(3 if records>10 else 2)


async def test_filters_expansions_and_return_anchors(user):
    s=await setup(user,[item(1),item(2,'record')])
    with user:s['set_global_result_expansion']('records',2,True)
    click_tab(user,'global_search.filter.records',1)
    await user.should_not_see('Result 1');await user.should_see('Result 2')
    assert s['rendered'][-1][2]['initially_expanded'] is True
    with user:await s['open_global_record_from_result']({'id':2})
    assert s['state']['global_search_return_anchor']=='compact-result-records-2';s['select_record_details'].assert_awaited_once_with(2)
    with user:await s['open_global_aggregation_from_result']({'id':1})
    s['open_aggregation'].assert_awaited_once_with({'id':1})
    with user:s['render_global_search_results']()
    s['restore_compact_result_anchor'].assert_called_with('compact-result-aggregations-1')
    assert 'global_search_return_anchor' not in s['state']

@pytest.mark.parametrize('boundary',['navigation','logout','newer'])
async def test_late_response_does_not_replace_current_results(user,boundary):
    s=await setup(user);started=asyncio.Event();release=asyncio.Event()
    async def delayed(payload):started.set();await release.wait();return {'items':[item(99)]}
    s['api'].full_text_search.side_effect=delayed
    with user:task=asyncio.create_task(s['run_global_search']('Example',load_more=True))
    await asyncio.wait_for(started.wait(),3)
    if boundary=='navigation':s['state']['resource']='dashboard'
    elif boundary=='logout':
        with user:s['clear_global_search_session']()
        s['auth_state']['principal']=None
    else:s['state']['global_search_revision']+=1
    release.set();await task
    assert s['state']['global_search_streams']=={}
    await user.should_not_see('Result 99')

async def test_authorized_components_and_failure_fallback_are_bounded(user):
    s=await setup(user);s['api'].full_text_search.return_value={'items':[item(1,'record')],'totals':{'records':2,'aggregations':0},'next_cursor':'next','index_freshness':{'has_pending_content':True}}
    with user:await s['run_global_search']('Example',load_more=True)
    s['api'].component_page.assert_not_awaited()
    s['api'].resource_capabilities.assert_awaited_once_with('records',1)
    assert s['state']['global_search_streams']['all'][0][0]['matching_components'][0]['id']==7
    assert s['state']['global_search_pending']
    s['api'].resource_capabilities.side_effect=ApiError(403,'Forbidden')
    with user:await s['run_global_search']('Example',load_more=True)
    assert s['state']['global_search_streams']['all'][0][-1]['record_capabilities']=={}

async def test_error_empty_and_diagnostics_do_not_disclose_without_privilege(user):
    s=await setup(user);assert not any(isinstance(e,ui.switch) for e in user.client.elements.values())
    s['api'].full_text_search.side_effect=ApiError(503,'Unavailable')
    with user:await s['run_global_search']('Example',load_more=True)
    await user.should_see('Search unavailable');assert not s['state']['global_search_loading']
    s['api'].full_text_search.side_effect=None;s['api'].full_text_search.return_value={'items':[],'totals':{'records':0,'aggregations':0}}
    with user:await s['run_global_search']('Example',load_more=True)
    await user.should_see(t('webui.render_global_search_results.label.no_results_found_ab1c85dc'))

async def test_diagnostics_explicit_opt_in_and_cleanup(user):
    s=await setup(user,privileges=['search.query.debug'])
    s['api'].full_text_search.return_value={'items':[],'totals':{'records':0,'aggregations':0}}
    toggle=next(e for e in user.client.elements.values() if isinstance(e,ui.switch))
    with user:toggle.value=True
    await asyncio.sleep(.1)
    s['api'].full_text_search.assert_not_awaited()
    with user:await s['run_global_search']('Example',load_more=True)
    assert s['api'].full_text_search.await_args.args[0]['debug'] is True
    assert s['state']['search_diagnostics_sent']['debug'] is True
    with user:s['clear_global_search_session']()
    assert s['state']['search_diagnostics_sent'] is None and not s['state']['search_diagnostics_enabled']

async def test_safe_snippet_renders_untrusted_text_as_labels(user):
    s=await setup(user)
    with user:s['render_safe_snippet']('<script>alert(1)</script> ⟦match⟧',compact=True)
    await user.should_see('<script>alert(1)</script> ')
    assert any('global-search-highlight' in e.classes and e.text=='match' for e in user.client.elements.values())
