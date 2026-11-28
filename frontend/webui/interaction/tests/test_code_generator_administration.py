"""Settings interactions, exact inputs, server paging and late-response safety."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from nicegui import ui

from frontend.webui.api_client import ApiError
from frontend.webui.code_generator_administration import (
    BASE, code_generation_page, counter_dialog, edit_generator)
from frontend.webui.entity_selectors import build_relationship_selector
from frontend.webui.i18n_catalogue import set_active_messages
from frontend.webui.code_generator_messages import t
from frontend.webui.locale_services import set_locale_context

pytest_plugins=['nicegui.testing.user_plugin']
pytestmark=pytest.mark.asyncio
ROOT=Path(__file__).parents[4]
AR={v['message_key']:v['translated_text'] for v in json.loads(
    (ROOT/'frontend/webui/i18n/messages.ar.generated.json').read_text())['items']}


def definition(identity=1, **changes):
    row=dict(id=identity,version=1,name=f'Name{identity:03}',kind='record',
        primary_field='record_number',type_id=None,field_id=None,pattern='R{SERIAL}',
        start='10',increment='10',scope='generator',reset_frequency='never',
        padding_width=None,max_code_length=128,enabled=False,
        target_snapshot={'type_name':None,'field_name':None})
    row.update(changes)
    row.setdefault('applies_to','type' if row['type_id'] is not None else 'all')
    return row


def samples(prefix='R'):
    return {'items':[dict(value=f'{prefix}{n}',serial=str(n),date='2026-12-31',
        scope_kind='generator',scope_id=0,period_bucket='0001-01-01',reset=False)
        for n in (10,20,30,40,50)],'warnings':[],'working_timezone':'Asia/Dubai'}


class Api:
    def __init__(self):
        self.calls=[]
        self.rows=[definition(i) for i in range(1,131)]
        self.preview=samples()
        self.preview_handler=None
        self.save_error=None
        self.history=AsyncMock(return_value=[])
        self.counter_version=0
        self.counter_error=None
        self.field_handler=None
        self.save_handler=None

    async def request(self, method, path, **kwargs):
        self.calls.append((method,path,deepcopy(kwargs)))
        params=kwargs.get('params',{})
        if path==BASE+'/targets/primary':
            return {'items':[{'key':params['kind']+'_number','max_length':None},
                             {'key':'title','max_length':None},{'key':'description','max_length':None}]}
        if path in (BASE+'/targets/types',BASE+'/targets/fields'):
            if path.endswith('/fields') and self.field_handler and params.get('selected'):
                result=await self.field_handler(params['selected'])
                if result is not None:return result
            prefix='Field' if path.endswith('/fields') else 'Type'
            rows=[{'id':i,'name':f'{prefix}{i:03}','max_length':128} for i in range(1,131)]
            selected=params.get('selected')
            rows=[v for v in rows if not params.get('q') or params['q'] in v['name'] or v['id']==selected]
            rows.sort(key=lambda v:(v['id']!=selected,v['name']))
            return {'items':rows[params.get('offset',0):params.get('offset',0)+params.get('limit',25)],'total':len(rows)}
        if path==BASE+'/preview':
            return await self.preview_handler(kwargs['json']) if self.preview_handler else deepcopy(self.preview)
        if path.endswith('/counter/advance'):
            if self.counter_error:raise self.counter_error
            self.counter_version+=1
            return {**kwargs['json'],'version':self.counter_version}
        if path.endswith('/counters'):
            return {'items':[],'total':0}
        if path.endswith('/counter'):
            return {**params,'version':self.counter_version,'next_number':'10','last_serial':None,'forward_next':None}
        if path==BASE and method=='GET':
            rows=[v for v in self.rows if params.get('q','').casefold() in v['name'].casefold()
                  and (params.get('kind') is None or v['kind']==params['kind'])
                  and (params.get('enabled') is None or v['enabled']==params['enabled'])]
            rows.sort(key=lambda v:(v['name'],v['id']),reverse=params.get('descending',False))
            return {'items':deepcopy(rows[params['offset']:params['offset']+params['limit']]),'total':len(rows)}
        if method in ('POST','PUT'):
            if self.save_error:raise self.save_error
            if self.save_handler:await self.save_handler(kwargs['json'])
            result={**definition(201),**kwargs['json']}
            if method=='POST':self.rows.append(result)
            return result
        if method=='GET' and path.startswith(BASE+'/'):
            return deepcopy(next(row for row in self.rows if row['id']==int(path.split('/')[-1])))
        raise AssertionError((method,path,kwargs))


def mark(user, element):
    element.mark(f'control-{element.id}')
    return user.find(marker=f'control-{element.id}')


async def open_dialog(user, *, row=None, language='en', api=None, audit=False, render_history=None):
    api=api or Api()
    holder={};live={'value':True};saved=AsyncMock()
    @ui.page('/generator-dialog')
    async def page():
        set_locale_context(language,'Asia/Dubai')
        set_active_messages(AR if language=='ar' else {})
        holder['form']=await edit_generator(api=api,row=row,active=lambda:live['value'],on_error=str,
            bind_relationship=build_relationship_selector(api,error_message=str),
            direction=lambda:'rtl' if language=='ar' else 'ltr',on_saved=saved,
            render_history=render_history,can_audit=lambda:audit)
    await user.open('/generator-dialog')
    return api,holder['form'],live,saved


@pytest.mark.parametrize('language',['en','ar'])
async def test_create_requires_name_but_not_reason_and_keeps_exact_big_serial(user,language):
    api,form,_,saved=await open_dialog(user,language=language)
    mark(user,form['save_button']).click()
    await asyncio.sleep(.02)
    assert not any(m=='POST' and p==BASE for m,p,_ in api.calls)
    form['controls']['name'].value='Contract series'
    form['controls']['max_code_length'].value='6000'
    form['controls']['start'].value='9'*5000
    form['controls']['increment'].value='10'
    form['controls']['padding_width'].value='0'
    mark(user,form['save_button']).click()
    await asyncio.sleep(.03)
    payload=next(v for m,p,v in api.calls if m=='POST' and p==BASE)
    assert payload['json']['name']=='Contract series'
    assert payload['json']['start']=='9'*5000 and isinstance(payload['json']['start'],str)
    assert payload['json']['increment']=='10' and payload['json']['padding_width']==0
    assert 'X-Change-Reason' not in payload['headers']
    assert saved.await_count==1 and not form['dialog'].value


@pytest.mark.parametrize('language',['en','ar'])
async def test_edit_requires_reason_and_stale_version_retains_inputs(user,language):
    api,form,_,saved=await open_dialog(user,row=definition(),language=language)
    form['controls']['name'].value='Updated name'
    mark(user,form['save_button']).click();await asyncio.sleep(.02)
    assert not any(m=='PUT' for m,_,_ in api.calls)
    form['controls']['reason'].value='Clarify purpose'
    api.save_error=ApiError(412,{'code':'code_generator_stale_version'})
    mark(user,form['save_button']).click();await asyncio.sleep(.03)
    request=next(v for m,_,v in api.calls if m=='PUT')
    assert request['headers']=={'If-Match':'1','X-Change-Reason':'Clarify purpose'}
    assert form['dialog'].value and form['controls']['name'].value=='Updated name'
    assert form['controls']['reason'].value=='Clarify purpose'
    assert form['state']['stale'] and not form['save_button'].enabled
    assert saved.await_count==0


async def test_preview_is_one_five_value_request_and_changes_refresh_without_writes(user):
    api,form,_,_=await open_dialog(user)
    form['controls']['name'].value='Preview series'
    form['controls']['max_code_length'].value='128'
    form['tabs'].value='preview'
    with form['dialog']:
        await form['preview']()
    assert len(form['table'].rows)==5
    assert [r['value'] for r in form['table'].rows]==['R10','R20','R30','R40','R50']
    assert sum(p==BASE+'/preview' for _,p,_ in api.calls)==1
    assert not any(m in ('POST','PUT') and p!=BASE+'/preview' for m,p,_ in api.calls)
    form['controls']['start'].value='20'
    await asyncio.sleep(.45)
    requests=[v for _,p,v in api.calls if p==BASE+'/preview']
    assert len(requests)==2 and requests[-1]['json']['configuration']['start']=='20'
    form['controls']['name'].value=''
    assert form['table'].rows==[]
    await asyncio.sleep(.45)
    assert len([v for _,p,v in api.calls if p==BASE+'/preview'])==2


async def test_independent_pattern_warning_is_visible_and_edit_preview_identifies_itself(user):
    api=Api()
    api.preview['warnings']=['independent_number_pattern']
    _,form,_,_=await open_dialog(user,row=definition(enabled=True),api=api)
    form['tabs'].value='preview'
    with form['dialog']:
        await form['preview']()
    assert api.calls[-1][2]['json']['generator_id']==1
    await user.should_see(t('independent_pattern'))
    form['controls']['pattern'].value='OTHER{SERIAL}'
    await user.should_not_see(t('independent_pattern'))


@pytest.mark.parametrize('abandon',['change','close','navigate'])
async def test_late_preview_never_replaces_new_results_or_revives_abandoned_dialog(user,abandon):
    api=Api();started=asyncio.Event();release=asyncio.Event()
    async def preview(body):
        if body['configuration']['pattern']=='R{SERIAL}':
            started.set();await release.wait();return samples('OLD')
        return samples('NEW')
    api.preview_handler=preview
    _,form,live,_=await open_dialog(user,api=api)
    form['controls']['name'].value='Late preview';form['controls']['max_code_length'].value='128'
    form['controls']['pattern'].value='R{SERIAL}'
    with form['dialog']:
        pending=asyncio.create_task(form['preview']())
    await asyncio.wait_for(started.wait(),2)
    if abandon=='change':
        form['controls']['pattern'].value='N{SERIAL}'
        await asyncio.sleep(.45)
        assert form['table'].rows[0]['value']=='NEW10'
    elif abandon=='close':form['dialog'].close()
    else:live['value']=False
    release.set();await pending
    assert not any(row['value'].startswith('OLD') for row in form['table'].rows)


async def test_listing_pages_beyond_100_and_keeps_draft_filters_unsubmitted(user):
    api=Api();holder={}
    @ui.page('/generators')
    async def page():
        set_locale_context('en','UTC');set_active_messages({})
        holder['view']=await code_generation_page(api=api,container=ui.column(),
            bind_relationship=build_relationship_selector(api,error_message=str),active=lambda:True,on_error=str)
    await user.open('/generators')
    view=holder['view']
    await view['page'].move(4)
    assert view['page'].table.rows[0]['id']==101
    view['query'].value='Name129'
    await view['page'].move(1)
    assert [r['id'] for r in view['page'].table.rows]==[126,127,128,129,130]
    assert api.calls[-1][2]['params']['q']==''
    await view['search']()
    assert view['page'].page==1
    assert [r['id'] for r in view['page'].table.rows]==[129]
    assert all(call[2]['params']['limit']<=50 for call in api.calls if call[1]==BASE)
    assert 'erms-page-table' in view['page'].table._classes


@pytest.mark.parametrize('allowed',[False,True])
async def test_history_is_lazy_and_requires_separate_audit_permission(user,allowed):
    # The production timeline callback is synchronous.
    rendered=[]
    def timeline(rows,host):rendered.extend(rows)
    api,form,_,_=await open_dialog(user,row=definition(),audit=allowed,render_history=timeline)
    assert api.history.await_count==0
    form['tabs'].value='history';await asyncio.sleep(.03)
    assert api.history.await_count==int(allowed)
    if allowed:api.history.assert_awaited_with('code-generators',1,limit=26,offset=0)


async def test_typed_target_retains_selected_ids_and_reads_capacity_once(user):
    row=definition(primary_field=None,type_id=1,field_id=2,
        target_snapshot={'type_name':'Type001','field_name':'Field002'})
    api,form,_,_=await open_dialog(user,row=row)
    await asyncio.sleep(.03)
    assert form['target']['type']['id']==1 and form['target']['field']['id']==2
    assert form['target']['field']['max_length']==128
    field_reads=[v for _,p,v in api.calls if p==BASE+'/targets/fields']
    assert len(field_reads)==1 and field_reads[0]['params']['selected']==2
    assert field_reads[0]['params']['limit']==1


async def test_older_field_lookup_cannot_replace_a_later_selection(user):
    api=Api();started=asyncio.Event();release=asyncio.Event()
    async def field(identity):
        if identity==3:
            started.set();await release.wait()
            return {'items':[{'id':3,'name':'Field003','max_length':60}],'total':1}
    api.field_handler=field
    row=definition(primary_field=None,type_id=1,field_id=2,
        target_snapshot={'type_name':'Type001','field_name':'Field002'})
    _,form,_,_=await open_dialog(user,row=row,api=api)
    field=next(control for control in user.find(ui.select).elements if control.label=='Text field')
    field.set_options({2:'Field002',3:'Field003',4:'Field004'})
    field.value=3
    await asyncio.wait_for(started.wait(),2)
    assert not form['target']['ready']
    field.value=4
    await asyncio.sleep(.03)
    assert form['target']['field']['id']==4 and form['target']['ready']
    release.set();await asyncio.sleep(.03)
    assert form['target']['field']['id']==4


async def test_combined_month_scope_preview_sends_fictional_contexts_and_shows_each_reset(user):
    api,form,_,_=await open_dialog(user)
    controls=form['controls']
    controls['name'].value='Monthly unit series';controls['max_code_length'].value='100'
    controls['pattern'].value='{ORG_UNIT_CODE}/{YYYY}/{MM}/{SERIAL}'
    controls['scope'].value='org_unit';controls['reset_frequency'].value='monthly'
    form['scenario'].value='combined'
    form['sample_date'].value='2026-11-27'
    form['sample_controls']['A']['org_unit_code'].value='FIN'
    form['sample_controls']['B']['org_unit_code'].value='HR'
    items=[dict(value=value,serial=serial,date=day,scope_kind='org_unit',scope_id=scope,
        period_bucket=day[:7]+'-01',reset=reset) for value,serial,day,scope,reset in [
            ('FIN/2026/11/10','10','2026-11-30',1,False),
            ('FIN/2026/11/20','20','2026-11-30',1,False),
            ('HR/2026/11/10','10','2026-11-30',2,False),
            ('FIN/2026/12/10','10','2026-12-01',1,True),
            ('HR/2026/12/10','10','2026-12-01',2,True)]]
    api.preview={**samples(),'items':items}
    with form['dialog']:await form['preview']()
    body=next(v['json'] for _,p,v in api.calls if p==BASE+'/preview')
    assert body['scenario']=='combined' and body['context_a']['org_unit_code']=='FIN'
    assert body['context_b']['org_unit_code']=='HR'
    assert [bool(v['reset_label']) for v in form['table'].rows]==[False,False,False,True,True]
    assert [v['scope_label'] for v in form['table'].rows]==['Context A','Context A','Context B','Context A','Context B']
    assert not any('/counter' in p for _,p,_ in api.calls)


async def test_saving_freezes_controls_and_ignores_a_success_after_navigation(user):
    api=Api();started=asyncio.Event();release=asyncio.Event()
    async def saving(body):started.set();await release.wait()
    api.save_handler=saving
    _,form,live,saved=await open_dialog(user,api=api)
    form['controls']['name'].value='Pending save';form['controls']['max_code_length'].value='128'
    mark(user,form['save_button']).click()
    await asyncio.wait_for(started.wait(),2)
    assert all(not control.enabled for control in form['controls'].values())
    assert form['dialog']._props['persistent'] is True
    live['value']=False
    release.set();await asyncio.sleep(.03)
    assert saved.await_count==0


@pytest.mark.parametrize('language',['en','ar'])
async def test_history_uses_the_shared_timeline_and_styled_localized_change_table(user,language):
    from frontend.webui.audit_workspace import build_audit_workspace
    api=Api();holder={}
    api.history.return_value=[dict(id=1,entity_type='code_generator',entity_id=1,operation='UPDATE',
        occurred_at='2026-11-27T00:00:00Z',actor_name='Audit actor',actor_email='audit@test.invalid',
        source='web_ui',changed_fields=['name'],before_state={'name':'Original series'},
        after_state={'name':'Historical series'},metadata={},reason='Clarify purpose')]
    @ui.page('/generator-shared-history')
    async def page():
        set_locale_context(language,'UTC');set_active_messages(AR if language=='ar' else {})
        host=ui.column()
        workspace=build_audit_workspace(api=api,table_container=host,
            principal=lambda:{'global_privileges':['audit.view','app.settings.manage']},
            selected=lambda:False,enter=lambda:None,error_message=str,format_timestamp=str,
            set_connection_status=lambda _:None,can_open_settings=lambda:True,
            open_settings=AsyncMock(),open_destination=AsyncMock(),
            direction=lambda:'rtl' if language=='ar' else 'ltr')
        holder['form']=await edit_generator(api=api,row=definition(name='Current series'),
            active=lambda:True,on_error=str,bind_relationship=build_relationship_selector(api,error_message=str),
            direction=lambda:'rtl' if language=='ar' else 'ltr',on_saved=AsyncMock(),
            can_audit=lambda:True,render_history=workspace.render_event_timeline)
    await user.open('/generator-shared-history')
    holder['form']['tabs'].value='history';await asyncio.sleep(.03)
    assert any(label.text=='Historical series' for label in user.find(ui.label).elements)
    button=next(button for button in user.find(ui.button).elements if button.icon=='chevron_right')
    mark(user,button).click();await asyncio.sleep(.02)
    changes=next(table for table in user.find(ui.table).elements if table.rows and 'before' in table.rows[0])
    assert changes.rows==[{'field':'الاسم' if language=='ar' else 'Name',
                          'before':'Original series','after':'Historical series'}]
    assert 'erms-page-table' in changes._classes
    assert all(column['align']==('right' if language=='ar' else 'left') for column in changes.columns)


async def test_counter_adjustment_preserves_exact_strings_and_requires_reason_and_fresh_version(user):
    api=Api();holder={}
    @ui.page('/generator-counter')
    async def page():
        set_locale_context('en','UTC');set_active_messages({})
        holder['form']=await counter_dialog(api=api,row=definition(),active=lambda:True,on_error=str,direction=lambda:'ltr')
    await user.open('/generator-counter')
    form=holder['form']
    with form['dialog']:
        await form['load']()
    form['desired'].value='9'*300
    with form['dialog']:
        await form['apply']()
    assert not any(p.endswith('/advance') for _,p,_ in api.calls)
    form['reason'].value='Continue imported series'
    api.counter_error=ApiError(412,{'code':'code_generator_stale_version'})
    with form['dialog']:
        await form['apply']()
    assert form['desired'].value=='9'*300 and form['reason'].value=='Continue imported series'
    assert form['state']['loaded'] is None
    request=next(v for _,p,v in api.calls if p.endswith('/advance'))
    assert request['json']['next_number']=='9'*300 and request['headers']['If-Match']=='0'
    count=len(api.calls)
    with form['dialog']:await form['apply']()
    assert len(api.calls)==count
    api.counter_error=None;api.counter_version=1
    with form['dialog']:
        await form['load']()
        await form['apply']()
    assert [v['headers']['If-Match'] for _,p,v in api.calls if p.endswith('/advance')]==['0','1']


@pytest.mark.parametrize('language',['en','ar'])
@pytest.mark.parametrize('applicability',['all','untyped','type'])
async def test_applies_to_selector_sends_the_exact_population_and_clears_old_types(user,language,applicability):
    api,form,_,_=await open_dialog(user,language=language)
    form['controls']['name'].value='Scoped record numbers'
    form['controls']['max_code_length'].value='128'
    control=next(v for v in user.find(ui.select).elements if v.label==(AR['code_generation.ui.applies_to'] if language=='ar' else 'Applies to'))
    assert set(control.options)=={'all','untyped','type'}
    control.value=applicability
    await asyncio.sleep(.03)
    owners=[v for v in user.find(ui.select).elements if v.label==(AR['code_generation.ui.type'] if language=='ar' else 'Type')]
    if applicability=='type':
        assert len(owners)==1
        mark(user,form['save_button']).click();await asyncio.sleep(.02)
        assert not any(m=='POST' and p==BASE for m,p,_ in api.calls)
        owners[0].set_options({7:'Type007'},value=7)
        await asyncio.sleep(.04)
    else:assert not owners
    mark(user,form['save_button']).click();await asyncio.sleep(.03)
    body=next(v['json'] for m,p,v in api.calls if m=='POST' and p==BASE)
    assert body['applies_to']==applicability
    assert body['type_id']==(7 if applicability=='type' else None)


@pytest.mark.parametrize('language',['en','ar'])
async def test_editing_selected_type_to_untyped_clears_type_and_preserves_reason_rules(user,language):
    api,form,_,_=await open_dialog(user,language=language,row=definition(type_id=7,
        target_snapshot={'type_name':'Type007'}))
    control=next(v for v in user.find(ui.select).elements if v.label==(AR['code_generation.ui.applies_to'] if language=='ar' else 'Applies to'))
    assert control.value=='type'
    control.value='untyped';await asyncio.sleep(.03)
    assert form['target']['type'] is None
    assert not [v for v in user.find(ui.select).elements if v.label==(AR['code_generation.ui.type'] if language=='ar' else 'Type')]
    mark(user,form['save_button']).click();await asyncio.sleep(.02)
    assert not any(m=='PUT' for m,_,_ in api.calls)
    form['controls']['reason'].value='Separate untyped numbering'
    mark(user,form['save_button']).click();await asyncio.sleep(.03)
    request=next(v for m,_,v in api.calls if m=='PUT')
    assert request['json']['applies_to']=='untyped' and request['json']['type_id'] is None
    assert request['headers']['X-Change-Reason']=='Separate untyped numbering'
