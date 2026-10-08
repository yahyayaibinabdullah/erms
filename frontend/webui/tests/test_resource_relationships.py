"""Phase 2 UI invariants, using synthetic rows and bounded async responses."""
import asyncio
from types import SimpleNamespace
import pytest
from nicegui import ui
from frontend.webui.api_client import ApiError
from frontend.webui.capabilities import can_navigate
from frontend.webui.resource_relationships import PageTable, link_row, hydrate_target, relationship_administration
from frontend.webui.locale_services import set_locale_context



@pytest.fixture
def host():
    column = ui.column()
    with column:
        set_locale_context("en", "Asia/Dubai")
    return column


def test_catalogue_requires_its_own_privilege():
    assert can_navigate('relationship-types', ['relationships.administer'])
    assert not can_navigate('relationship-types', ['relationships.link'])
    assert not can_navigate('relationship-types', ['authorization.administer'])


def test_redacted_row_has_no_actions_or_protected_target_label():
    item = {'related':{'redacted':True,'id':None,'number':None,'title':None},'is_active':False}
    row = link_row(item, True)
    assert not row['can_open'] and not row['can_remove']
    assert row['target_label'] == 'Restricted resource'
    visible = link_row({'related':{'redacted':False,'id':4,'number':'R-4','title':'Other'},'is_active':True},False)
    assert visible['can_open'] and not visible['can_remove']


@pytest.mark.asyncio
async def test_selected_target_hydrates_one_id_and_handles_revoked_access():
    calls=[]
    async def request(method,path,params):
        calls.append(params)
        return {'items':[{'id':7}]} if len(calls)==1 else {'items':[]}
    api=SimpleNamespace(request=request)
    assert (await hydrate_target(api,'/links',7))['id']==7
    assert calls==[{'selected_id':7,'limit':1}]
    with pytest.raises(ApiError):
        await hydrate_target(api,'/links',7)


@pytest.mark.asyncio
async def test_slow_old_page_cannot_overwrite_latest_page_or_abandoned_view(host):
    futures=[]
    async def fetch(page):
        future=asyncio.get_running_loop().create_future()
        futures.append(future)
        return await future
    active=[True]
    with host:
        page=PageTable(columns=[],fetch=fetch,active=lambda:active[0],on_error=lambda e:'Failed',empty='empty')
        first=asyncio.create_task(page.load())
        await asyncio.sleep(0)
        second=asyncio.create_task(page.load())
        await asyncio.sleep(0)
        futures[1].set_result({'items':[{'id':2}],'total':1})
        await second
        futures[0].set_result({'items':[{'id':1}],'total':1})
        await first
        assert page.table.rows==[{'id':2}]
        third=asyncio.create_task(page.load());await asyncio.sleep(0)
        active[0]=False
        futures[2].set_result({'items':[{'id':3}],'total':1});await third
        assert page.table.rows==[{'id':2}]


@pytest.mark.asyncio
async def test_last_page_removal_reloads_valid_server_page_and_error_clears_old_rows(host):
    calls=[]
    async def fetch(page):
        calls.append((page.page,page.size))
        return {'items':[],'total':25} if page.page==2 else {'items':[{'id':1}],'total':25}
    with host:
        page=PageTable(columns=[],fetch=fetch,active=lambda:True,on_error=lambda e:'Permission changed',empty='empty')
        page.page=2
        await page.load()
        assert calls==[(2,25),(1,25)]
        assert page.table.pagination['rowsNumber']==25
        async def denied(_):
            raise ApiError(403,'Denied')
        page.fetch=denied
        await page.load()
        assert page.table.rows==[] and page.status.text=='Permission changed'


@pytest.mark.asyncio
async def test_pager_sends_only_bounded_server_requests(host):
    calls=[]
    async def fetch(page):
        calls.append((page.page,page.size,page.sort,page.descending))
        return {'items':[{'id':page.page}],'total':29}
    with host:
        page=PageTable(columns=[],fetch=fetch,active=lambda:True,on_error=str,empty='empty')
        await page.load()
        assert page.previous._props['disable'] and not page.next._props.get('disable')
        await page.move(1)
        assert page.table.rows==[{'id':2}] and page.next._props['disable']
        await page.resize(SimpleNamespace(value=10))
        assert page.page==1 and page.size==10
        await page.request(SimpleNamespace(args={'pagination':{'page':1,'rowsPerPage':10,'sortBy':'label','descending':True}}))
        assert calls==[(1,25,'',False),(2,25,'',False),(1,10,'',False),(1,10,'label',True)]


@pytest.mark.asyncio
async def test_catalogue_actions_are_connected_to_handlers(host):
    async def request(*args, **kwargs):
        return {'items':[], 'total':0}
    with host:
        page = await relationship_administration(api=SimpleNamespace(request=request),container=host,active=lambda:True,on_error=str)
        assert page.no_data.text == 'No matching relationship types.'
        events = {listener.type for listener in page.table._event_listeners.values()}
        assert {'editType','deleteType','request'} <= events


@pytest.mark.asyncio
async def test_read_only_panel_omits_add_and_remove_controls(host):
    from nicegui.elements.button import Button
    from frontend.webui.resource_relationships import relationship_panel
    async def request(*args, **kwargs):
        return {'items':[{'id':7,'relationship_type_id':1,'label':'related to','is_active':True,
            'related':{'id':2,'number':'REC-002','title':'Other','redacted':False}}],'total':1}
    with host:
        page=await relationship_panel(api=SimpleNamespace(request=request),kind='record',identity=1,
            source_label='Source',can_link=False,active=lambda:True,open_target=None,bind_remote=None,on_error=str)
        button_labels=[element.text for element in host.descendants() if isinstance(element,Button)]
        assert 'Refresh' in button_labels and 'Add relationship' not in button_labels
        assert page.table.rows[0]['can_open'] and not page.table.rows[0]['can_remove']


@pytest.mark.asyncio
async def test_type_editor_uses_enabled_languages_and_stages_each_language(host, monkeypatch):
    from nicegui import core
    monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
    from nicegui.elements.button import Button
    from nicegui.elements.input import Input
    from nicegui.elements.select import Select
    from nicegui.elements.dialog import Dialog
    calls=[]
    async def request(method,path,**kwargs):
        calls.append((method,kwargs))
        return {'items':[], 'total':0}
    languages=[{'language_tag':'en','native_name':'English','english_name':'English','direction':'ltr'},
               {'language_tag':'ar','native_name':'العربية','english_name':'Arabic','direction':'rtl'},
               {'language_tag':'fr','native_name':'Français','english_name':'French','direction':'ltr'},
               {'language_tag':'de','native_name':'Deutsch','english_name':'German','is_enabled':False}]
    with host:
        await relationship_administration(api=SimpleNamespace(request=request),container=host,
            active=lambda:True,on_error=str,supported_languages=languages)
        add=next(e for e in host.descendants() if isinstance(e,Button) and e.text=='Add relationship type')
        next(iter(add._event_listeners.values())).handler(None)
        await asyncio.sleep(0)
        dialog=max((e for e in host.client.elements.values() if isinstance(e,Dialog) and e.value), key=lambda e:e.id)
        controls={e._props.get('label'):e for e in dialog.descendants() if isinstance(e,Input)}
        assert set(controls)=={'Stable code','Forward name (English)','Reverse name (English)','Forward name','Reverse name'}
        selector=next(e for e in dialog.descendants() if isinstance(e,Select))
        assert set(selector.options)=={'en','ar','fr'}
        selector.value='ar'
        controls['Forward name'].value='يشير إلى'
        controls['Reverse name'].value='أشار إليه'
        assert 'direction: rtl' in controls['Forward name']._props['input-style']
        selector.value='fr'
        controls['Forward name'].value='référence'
        controls['Reverse name'].value='référencé par'
        selector.value='en'
        controls['Forward name'].value='American term'
        controls['Reverse name'].value='American reverse term'
        selector.value='ar'
        assert controls['Forward name'].value=='يشير إلى'
        controls['Stable code'].value='test'
        controls['Forward name (English)'].value='references'
        controls['Reverse name (English)'].value='referenced by'
        save=next(e for e in dialog.descendants() if isinstance(e,Button) and e.text=='Save')
        next(iter(save._event_listeners.values())).handler(None)
        await asyncio.sleep(0)
        payload=next(kwargs['json'] for method,kwargs in calls if method=='POST')
        assert payload['translations']=={'ar':{'forward_name':'يشير إلى','reverse_name':'أشار إليه'},
                                          'fr':{'forward_name':'référence','reverse_name':'référencé par'},
                                          'en':{'forward_name':'American term','reverse_name':'American reverse term'}}
        assert 'arabic_forward_name' not in payload


@pytest.mark.asyncio
async def test_link_dialog_does_not_preload_targets_and_reuses_tree_browser(host, monkeypatch):
    from nicegui import core
    from nicegui.elements.button import Button
    from nicegui.elements.dialog import Dialog
    import frontend.webui.resource_relationships as module
    monkeypatch.setattr(core, 'loop', asyncio.get_running_loop())
    loaded=[];bindings={};picker_calls=[]
    async def request(*args,**kwargs):
        return {'items':[], 'total':0}
    def bind(control,resource,*args,**kwargs):
        bindings[resource]=kwargs
        async def load():
            loaded.append(resource)
        return load
    async def picker(control, **kwargs):
        picker_calls.append(kwargs)
    with host:
        await module.relationship_panel(api=SimpleNamespace(request=request,full_text_search=request),kind='record',identity=1,
            source_label='Source',can_link=True,active=lambda:True,open_target=None,bind_remote=bind,on_error=str,browse_resource=picker)
        add=next(e for e in host.descendants() if isinstance(e,Button) and e.text=='Add relationship')
        next(iter(add._event_listeners.values())).handler(None)
        await asyncio.sleep(0)
        assert loaded==['relationship-types']
        assert bindings['record']['min_query_length']==2
        dialog=max((e for e in host.client.elements.values() if isinstance(e,Dialog) and e.value), key=lambda e:e.id)
        browse=next(e for e in dialog.descendants() if isinstance(e,Button) and e.text=='Browse')
        next(iter(browse._event_listeners.values())).handler(None)
        await asyncio.sleep(0)
        assert picker_calls[0]['resource_kind']=='record'
        assert picker_calls[0]['exclude_id']==1
        assert callable(picker_calls[0]['on_select'])


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['record','aggregation'])
async def test_shared_tree_browser_drills_down_and_selects_only_requested_kind(host, monkeypatch, kind):
    import ast
    from pathlib import Path
    from typing import Any
    from nicegui import core
    from nicegui.elements.button import Button
    from nicegui.elements.label import Label
    from nicegui.elements.dialog import Dialog
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    calls=[];chosen=[]
    async def schemes():
        return [{'id':1,'code':'TEST','title':'Test Scheme'}]
    async def page(path,**params):
        calls.append((path,params))
        items={'classification-schemes/1/roots':[{'id':1,'title':'Classification','code':'C1','is_terminal':True}],
               'classifications/1/aggregations':[{'id':10,'title':'Case','aggregation_number':'A10'}],
               'aggregations/10/children':[],
               'aggregations/10/records':[{'id':42,'title':'Source','record_number':'R42'},{'id':43,'title':'Target','record_number':'R43'}]}[path]
        return {'items':items,'next_cursor':None}
    async def selected(item,active):
        assert active()
        chosen.append(item['id'])
    tree=ast.parse(Path('frontend/webui/app.py').read_text())
    function=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='browse_advanced_aggregation')
    namespace={'Any':Any,'ui':ui,'asyncio':asyncio,'api':SimpleNamespace(browse_page=page,browse_schemes=schemes),
               'render_message':lambda key:key,'error_message':str,'tree_expander_icon':lambda opened:'expand_more' if opened else 'chevron_right',
               'bind_remote_scheme_select':lambda control:None}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'shared-tree-browser','exec'),namespace)
    with host:
        await namespace['browse_advanced_aggregation'](ui.select({}),resource_kind=kind,exclude_id=42,on_select=selected)
        dialog=max((e for e in host.client.elements.values() if isinstance(e,Dialog) and e.value), key=lambda e:e.id)
        def row_for(title):
            return next(e for e in dialog.descendants() if 'advanced-relationship-tree-row' in e._classes
                        and any(isinstance(c,Label) and c.text==title for c in e.descendants()))
        def click(button):
            next(iter(button._event_listeners.values())).handler(None)
        click(next(e for e in row_for('Classification').descendants() if isinstance(e,Button)))
        await asyncio.sleep(.01)
        case=row_for('Case')
        if kind=='record':
            assert not any(isinstance(e,Button) and e._props.get('icon')=='check' for e in case.descendants())
            click(next(e for e in case.descendants() if isinstance(e,Button)))
            await asyncio.sleep(.01)
            assert not any(isinstance(e,Button) and e._props.get('icon')=='check' for e in row_for('Source').descendants())
            target=row_for('Target')
        else:
            target=case
        click(next(e for e in target.descendants() if isinstance(e,Button) and e._props.get('icon')=='check'))
        await asyncio.sleep(.01)
        assert chosen==[43 if kind=='record' else 10]
        assert all(params['limit']==50 for _,params in calls)
        assert not dialog.value
