"""Open canonical saved definitions through the actual workspace factory."""
import asyncio
import copy
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from nicegui import ui
from frontend.webui.advanced_search import build_advanced_search
from frontend.webui.advanced_search_model import compile_advanced_search_node
from frontend.webui.i18n_catalogue import set_active_messages

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio
TITLE={'field':'title','operator':'contains_ci','value':'budget'}
EXPRESSIONS=[TITLE, {'field':'is_vital','operator':'eq','value':False},
    {'field':'description','operator':'is_null'},
    {'full_text':{'query':'budget','sources':['metadata']}},
    {'and':[TITLE]}, {'or':[TITLE,{'field':'title','operator':'eq','value':'minutes'}]},
    {'not':TITLE}, {'and':[{'or':[{'not':{'and':[TITLE]}}]}]}]


@pytest.mark.parametrize('language',['en','ar'])
@pytest.mark.parametrize('resource',['records','aggregations'])
@pytest.mark.parametrize('expression',EXPRESSIONS,ids=['text','boolean','null','full-text','and','or','not','depth-five'])
async def test_reopen_canonical_definition_is_editable_clean_and_semantically_preserved(user,language,resource,expression):
    saved={'id':7,'version':3,'name':'Saved fixture','owner_user_id':1,
           'owner':{'name':'Fixture owner'},'date_updated':'2026-01-01',
           'audience_mode':'private','role_ids':[],'org_unit_ids':[],
           'capabilities':{'update':True,'execute':True,'delete':True},
           'definition':{'schema_version':1,'resource_type':resource[:-1], 'max_results':1000,
               'request':{'where':copy.deepcopy(expression),'sort':[{'field':'id','direction':'asc'}], 'limit':25,'offset':0}}}
    original=copy.deepcopy(saved)
    principal={'user':{'id':1},'global_privileges':['record.view','aggregation.view','search.saved_search.save']}
    state={'admin_saved_search_id':7}
    api=SimpleNamespace(saved_search=AsyncMock(return_value=saved),
        execute_saved_search=AsyncMock(return_value={'items':[],'total':0}),
        search_request=AsyncMock(return_value={'items':[],'total':0}),
        update_saved_search=AsyncMock())
    deps={name:Mock() for name in inspect.signature(build_advanced_search).parameters}
    deps.update(api=api,advanced_search_state=state,collection_state={},aggregation_state={},
        get_principal=lambda:principal,get_resource=lambda:'advanced-search',
        error_message=str,format_timestamp=lambda _:'Fixed date')
    @ui.page('/saved-reopen')
    async def screen():
        messages={r['message_key']:r['translated_text'] for r in json.loads(
            (Path(__file__).parents[2]/'i18n/messages.ar.generated.json').read_text())['items']} if language=='ar' else {}
        set_active_messages(messages)
        for name in ('title','subtitle','guidance'):deps[name]=ui.label('')
        for name in ('search_bar','aggregation_mode_bar','add_button','add_record_button','table_container'):deps[name]=ui.column()
        await build_advanced_search(**deps)()
    await user.open('/saved-reopen')
    await asyncio.sleep(.05)
    workspace=state['advanced_search_workspace']
    expected={'and':[expression]} if 'field' in expression or 'full_text' in expression else expression
    assert compile_advanced_search_node(workspace['root'],resource)==expected
    assert saved==original  # Opening must never rewrite the stored definition.
    assert workspace['saved']['id']==7 and workspace['resource']==resource
    assert workspace['loading'] is False and workspace['offset']==0
    assert json.loads(workspace['baseline'])['definition']['request']['where']==expected
    api.update_saved_search.assert_not_awaited()
    with user:
        assert await deps['set_navigation_guard'].call_args.args[0]('leave') is True
    assert not [d for d in user.client.elements.values() if isinstance(d,ui.dialog) and d.value]
    search=next(b for b in user.find(ui.button).elements if b.props.get('icon')=='search')
    assert search.enabled
    search.mark('execute-saved');user.find(marker='execute-saved').click()
    await asyncio.sleep(.1)
    api.execute_saved_search.assert_awaited_once_with(7,{'limit':25,'offset':0})
    api.search_request.assert_not_awaited()
    if expression==TITLE:
        field=next(e for e in user.find(ui.input).elements if e.value=='budget')
        with user:field.value='minutes'
        await asyncio.sleep(.05)
        updated=copy.deepcopy(saved)
        updated['version']=4
        updated['definition']['request']['where']={'and':[dict(TITLE,value='minutes')]}
        api.update_saved_search.return_value=updated
        save=next(b for b in user.find(ui.button).elements if b.props.get('icon')=='save')
        save.mark('update-saved');user.find(marker='update-saved').click()
        await asyncio.sleep(.15)
        api.update_saved_search.assert_awaited_once()
        identity,version,payload=api.update_saved_search.call_args.args
        assert (identity,version)==(7,3)
        assert payload['definition']['request']['where']==updated['definition']['request']['where']
        assert state['advanced_search_workspace']['saved']['version']==4
        with user:
            assert await deps['set_navigation_guard'].call_args.args[0]('leave') is True
