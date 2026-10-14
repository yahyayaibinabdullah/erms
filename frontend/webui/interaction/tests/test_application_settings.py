"""Real NiceGUI events and production selector binding; no database required."""
import ast
import asyncio
import copy
import json
from pathlib import Path
from typing import Any, Callable
from types import SimpleNamespace

import pytest
from nicegui import ui, background_tasks, events
from nicegui.testing import User

from frontend.webui.application_settings import settings_page, changed_rows, disposition_warning_panel, DESTINATION_KEYS
from frontend.webui.app import relationship_options, relationship_search_query
from frontend.webui.api_client import ApiError
from frontend.webui.capabilities import can_navigate
from frontend.webui.i18n_catalogue import render_message_plain, set_active_messages, strip_diagnostic_metadata
from backend.services.api.application_settings_registry import REGISTRY

pytest_plugins = ['nicegui.testing.user_plugin']
pytestmark = pytest.mark.asyncio
ROOT = Path(__file__).parents[4]
BINDING = next(n for n in ast.walk(ast.parse((ROOT/'frontend/webui/app.py').read_text()))
               if isinstance(n,ast.FunctionDef) and n.name=='bind_remote_relationship_select')
EN = {i['message_key']:i['default_text'] for i in json.loads((ROOT/'frontend/webui/i18n/messages.en.json').read_text())}
AR = {i['message_key']:i['translated_text'] for i in json.loads((ROOT/'frontend/webui/i18n/messages.ar.generated.json').read_text())['items']}


class Api:
    def __init__(self, language='en'):
        self.calls=[];self.language=language;self.gate=None;self.fail=False;self.saved=[]
        self.schemes=[dict(id=i,code=f'S{i:02}',title=f'Scheme {i}') for i in range(1,29)]
        self.nodes=[dict(id=i,code=f'B{i:02}',title=f'Branch {i}',is_terminal=False,
                         classification_scheme_id=1,parent_classification_id=None) for i in range(1,29)]
        self.nodes += [dict(id=300+i,code=f'T{i:03}',title=f'Terminal {i}',is_terminal=True,
                           classification_scheme_id=1,parent_classification_id=1) for i in range(1,29)]
        self.nodes.append(dict(id=999,code='OTHER',title='Other scheme',is_terminal=True,classification_scheme_id=2,parent_classification_id=None))
        texts=AR if language=='ar' else EN
        self.items={d.key:dict(key=d.key,kind=d.kind,value=d.default,category=d.category,
            category_label=texts[f'settings.category.{d.category}'],label=texts[d.label_key],description=texts[d.description_key],
            sensitive=d.secret,secret_is_set=False if d.secret else None,provenance='default',version=1,
            validation=dict(nullable=d.nullable,minimum=d.minimum,maximum=d.maximum,choices=d.choices,group=d.group)) for d in REGISTRY.values()}

    async def application_settings(self):
        self.calls.append(('settings',None))
        if self.gate:await self.gate.wait()
        return {'items':copy.deepcopy(list(self.items.values()))}

    async def save_application_settings(self,changes,reason):
        self.calls.append(('save',None));self.saved.append((copy.deepcopy(changes),reason))
        if self.fail:raise ApiError(409,{'code':'application_settings_stale_version'})
        if self.gate:await self.gate.wait()
        for change in changes:
            item=self.items[change['key']]
            if 'value' in change:item['value']=change['value']
            if 'secret_value' in change:item['secret_is_set']=True
            if 'clear_secret' in change:item['secret_is_set']=False
            if any(key in change for key in ('value','secret_value','clear_secret')):
                item['version']+=1;item['provenance']='configured'
        return {'items':copy.deepcopy(list(self.items.values()))}

    async def get(self,resource,identity):
        self.calls.append(('get',(resource,identity)))
        return copy.deepcopy(next(row for row in (self.schemes if resource=='classification-schemes' else self.nodes) if row['id']==identity))

    async def relationship_page(self,resource,fields,query,**params):
        self.calls.append(('search',(resource,query,params)))
        rows=self.schemes if resource=='classification-schemes' else self.nodes
        rows=[r for r in rows if all(r[k]==v for k,v in params.get('filters',{}).items())]
        return {'items':copy.deepcopy(rows[:params['limit']]),'total':len(rows)}

    async def request(self,method,path,*,params):
        self.calls.append(('browse',(path,params.copy())))
        rows=self.schemes if path.endswith('classification-schemes') else [r for r in self.nodes if r['classification_scheme_id']==params['classification_scheme_id'] and r['parent_classification_id']==params.get('parent_classification_id')]
        rows=sorted(rows,key=lambda row:(row['code'],row['id']))
        return copy.deepcopy(rows[params['offset']:params['offset']+params['limit']])


def mark(user,element):
    element.mark(f'element-{element.id}')
    return user.find(marker=f'element-{element.id}')


async def open_page(user,language='en',configured=False,initial_setting_key=None):
    api=Api(language);live={'active':True};holder={}
    if configured:
        for key,value in [('DISPOSITION_CLASSIFICATION_SCHEME_ID',1),('DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID',301),('DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID',301)]:api.items[key]['value']=value
    scope=dict(api=api,ui=ui,Any=Any,Callable=Callable,asyncio=asyncio,json=json,background_tasks=background_tasks,
               ApiError=ApiError,error_message=str,render_message_plain=render_message_plain,
               relationship_options=relationship_options,relationship_search_query=relationship_search_query,
               strip_diagnostic_metadata=strip_diagnostic_metadata)
    exec(compile(ast.Module(body=[BINDING],type_ignores=[]),'<settings-selector>','exec'),scope)
    @ui.page('/settings-test')
    async def page():
        set_active_messages(AR if language=='ar' else {})
        holder['container']=ui.column()
        holder['state']=await settings_page(api=api,container=holder['container'],active=lambda:live['active'],on_error=str,
            bind_relationship=scope['bind_remote_relationship_select'],direction=lambda:'rtl' if language=='ar' else 'ltr',initial_category='disposition',initial_setting_key=initial_setting_key)
    await user.open('/settings-test');await asyncio.sleep(.02)
    return api,holder,live


@pytest.mark.parametrize('key,category',[('DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID','disposition'),('SMTP_HOST','email'),('REVIEW_WARNING_WINDOW_DAYS','general')])
async def test_audit_target_opens_api_category_with_one_settings_read(user:User,key,category):
    api,_,_=await open_page(user,initial_setting_key=key)
    assert next(iter(user.find(ui.tabs).elements)).value==category
    assert api.calls==[('settings',None)]


@pytest.mark.parametrize('language',['en','ar'])
async def test_every_setting_has_visible_explanation_and_controls_and_no_secret(user:User,language):
    api,holder,_=await open_page(user,language)
    state=holder['state']
    assert sum(len(f['controls']) for f in state['forms'].values())==51
    texts=[label.text for label in user.find(ui.label).elements]
    assert all(item['description'] in texts for item in api.items.values())
    assert state['forms']['email']['password'].value==''
    assert len([kind for kind,_ in api.calls if kind=='settings'])==1
    assert not any(kind in {'search','browse'} for kind,_ in api.calls)


async def test_reason_atomic_destinations_and_other_unsaved_category_are_preserved(user:User):
    api,holder,_=await open_page(user)
    state=holder['state'];form=state['forms']['disposition'];other=state['forms']['general']
    with user:
        other['controls']['REVIEW_WARNING_WINDOW_DAYS'].value='81'
        form['controls']['DISPOSITION_CLASSIFICATION_SCHEME_ID'].set_options({1:'Scheme 1'},value=1)
    await asyncio.sleep(.02)
    mark(user,form['save']).click();await asyncio.sleep(.02)
    assert api.saved==[] and 'reason' in form['feedback'].text.lower()
    mark(user,form['reason']).type('Configure destinations')
    mark(user,form['save']).click();await asyncio.sleep(.06)
    changes,reason=api.saved[-1]
    assert {c['key'] for c in changes}==set(['DISPOSITION_CLASSIFICATION_SCHEME_ID','DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID','DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID'])
    assert all(c['expected_version']==1 for c in changes)
    assert other['controls']['REVIEW_WARNING_WINDOW_DAYS'].value=='81'
    assert api.items['REVIEW_WARNING_WINDOW_DAYS']['value']==30
    assert state['forms']['disposition']['reason'].value==''


async def test_conflict_keeps_form_and_password_replacement_clears_after_save(user:User):
    api,holder,_=await open_page(user);form=holder['state']['forms']['email']
    mark(user,form['password']).type('disposable-fixture-replacement')
    mark(user,form['reason']).type('Configure fixture SMTP')
    api.fail=True;mark(user,form['save']).click();await asyncio.sleep(.03)
    assert form['password'].value=='disposable-fixture-replacement' and form['save'].enabled
    assert 'stale' in form['feedback'].text
    api.fail=False;mark(user,form['save']).click();await asyncio.sleep(.06)
    fresh=holder['state']['forms']['email']
    assert fresh['password'].value=='' and api.items['SMTP_PASSWORD']['secret_is_set']
    assert len(api.saved[-1][0])==10
    assert not any('disposable-fixture' in str(getattr(e,'text','')) for e in user.find(ui.label).elements)


async def test_selected_ids_fetch_once_and_typeahead_starts_at_two_characters(user:User):
    api,holder,_=await open_page(user,configured=True);form=holder['state']['forms']['disposition']
    assert [value for kind,value in api.calls if kind=='get'].count(('classifications',301))==1
    control=form['controls']['DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID']
    for query in ('t','te'):
        with user:
            for listener in control._event_listeners.values():
                if listener.type=='inputValue':
                    events.handle_event(listener.handler,events.GenericEventArguments(sender=control,client=user.client,args=query))
        await asyncio.sleep(.25)
    searches=[v for kind,v in api.calls if kind=='search']
    assert len(searches)==1 and searches[0][1]=='te'
    assert searches[0][2]['limit']==25 and searches[0][2]['filters']=={'classification_scheme_id':1,'is_terminal':True}
    assert control.value==301 and 301 in control.options
    with user:form['controls']['DISPOSITION_CLASSIFICATION_SCHEME_ID'].set_options({1:'Scheme 1',2:'Scheme 2'},value=2)
    await asyncio.sleep(.03)
    assert control.value is None and control.options=={}


async def test_refresh_single_request_retains_old_content_and_ignores_abandoned_response(user:User):
    api,holder,live=await open_page(user)
    old=holder['state']['forms']['general']['controls']['REVIEW_WARNING_WINDOW_DAYS']
    api.gate=asyncio.Event();api.items['REVIEW_WARNING_WINDOW_DAYS']['value']=92
    user.find('Refresh').click();user.find('Refresh').click();await asyncio.sleep(.03)
    assert old.value=='30' and len([1 for k,_ in api.calls if k=='settings'])==2
    live['active']=False;api.gate.set();await asyncio.sleep(.03)
    assert old.value=='30'


async def test_warning_panel_does_not_grant_settings_authority(user:User):
    @ui.page('/warnings')
    def page():
        disposition_warning_panel([{'setting_key':'DISPOSITION_CLASSIFICATION_SCHEME_ID','code':'destination_unset'}],can_manage=False,open_settings=lambda:None)
    await user.open('/warnings')
    await user.should_see('Ask an authorized administrator')
    await user.should_not_see('Open Disposition settings')
    assert not can_navigate('application-settings',['authorization.administer','disposition.jobs.manage'])
    assert can_navigate('application-settings',['app.settings.manage'])


async def test_integer_input_preserves_precision_and_group_clear_is_write_only():
    item={'key':'BIG','kind':'integer','sensitive':False,'provenance':'default','value':1,'version':1,'validation':{'nullable':False,'group':None}}
    assert changed_rows([item],{'BIG':SimpleNamespace(value='9007199254740993')})[0]['value']==9007199254740993
    with pytest.raises(ValueError):changed_rows([item],{'BIG':SimpleNamespace(value='1.5')})


async def test_browse_pages_each_branch_and_revalidates_stale_terminal(user:User):
    api,holder,_=await open_page(user,configured=True)
    parent=1
    for depth in range(1,8):
        api.nodes.append(dict(id=1000+depth,code=f'D{depth:02}',title=f'Deep {depth}',is_terminal=False,
                             classification_scheme_id=1,parent_classification_id=parent))
        parent=1000+depth
    terminal=dict(id=2000,code='DEEP-TERM',title='Deep terminal',is_terminal=True,classification_scheme_id=1,parent_classification_id=parent)
    api.nodes.append(terminal)
    form=holder['state']['forms']['disposition']
    control=form['controls']['DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID']
    button=next(b for b in user.find(ui.button).elements if b.parent_slot.parent is control.parent_slot.parent)
    mark(user,button).click();await asyncio.sleep(.03)
    user.find('Next').click();await asyncio.sleep(.03)
    assert api.calls[-1][1][1]['offset']==25
    user.find('Previous').click();await asyncio.sleep(.03)
    user.find('B01 · Branch 1').click();await asyncio.sleep(.03)
    assert control.value==301  # A branch was navigated, never selected.
    # Fake API ordering below mirrors the real code/id ordering.
    for depth in range(1,8):
        user.find(f'D{depth:02} · Deep {depth}').click();await asyncio.sleep(.02)
    terminal['is_terminal']=False
    user.find('DEEP-TERM · Deep terminal').click();await asyncio.sleep(.03)
    assert control.value==301
    await user.should_see(EN['settings.error.invalid_value'])
    terminal['is_terminal']=True
    user.find('DEEP-TERM · Deep terminal').click();await asyncio.sleep(.03)
    assert control.value==2000
    assert all(payload[1]['limit']==26 for kind,payload in api.calls if kind=='browse')


async def test_old_search_cannot_restore_previous_scheme_options(user:User):
    api,holder,_=await open_page(user,configured=True)
    original=api.relationship_page;gate=asyncio.Event()
    async def blocked(*args,**kwargs):
        result=await original(*args,**kwargs)
        await gate.wait()
        return result
    api.relationship_page=blocked
    form=holder['state']['forms']['disposition'];key='DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID'
    with user:
        task=asyncio.create_task(form['loaders'][key]('te'))
    await asyncio.sleep(.02)
    with user:
        form['controls']['DISPOSITION_CLASSIFICATION_SCHEME_ID'].set_options({1:'Scheme 1',2:'Scheme 2'},value=2)
    await asyncio.sleep(.02);gate.set();await task
    assert form['controls'][key].value is None and form['controls'][key].options=={}


@pytest.mark.parametrize('language',['en','ar'])
async def test_optional_selector_clear_is_translated_and_resets_destination_drafts(user:User,language):
    _,holder,_=await open_page(user,language,configured=True)
    form=holder['state']['forms']['disposition'];scheme=form['controls'][DESTINATION_KEYS[0]]
    assert not scheme._props.get('clearable')
    clear=next(b for b in user.find(ui.button).elements if b.parent_slot.parent is scheme)
    assert clear._props['aria-label']==(AR if language=='ar' else EN)['settings.action.clear_selection']
    with user:
        listener=next(v for v in clear._event_listeners.values() if v.type=='click.stop')
        events.handle_event(listener.handler,events.GenericEventArguments(sender=clear,client=user.client,args=None))
    await asyncio.sleep(.02)
    assert all(form['controls'][key].value is None for key in DESTINATION_KEYS)


@pytest.mark.parametrize('language',['en','ar'])
async def test_timezone_dropdown_and_exact_integer_steppers(user:User,language):
    api,holder,_=await open_page(user,language)
    forms=holder['state']['forms']
    timezone=forms['general']['controls']['DEFAULT_WORKING_TIMEZONE']
    assert isinstance(timezone,ui.select) and timezone._props['use-input']
    assert timezone.options==sorted(timezone.options)
    assert {'Asia/Dubai','Europe/London','UTC'} <= set(timezone.options)
    with user:timezone.set_value('Europe/London')
    assert changed_rows(list(api.items.values())[:3],forms['general']['controls'])[0]['value']=='Europe/London'
    for item in api.items.values():
        if item['kind']!='integer':continue
        control=forms[item['category']]['controls'][item['key']]
        assert isinstance(control,ui.input) and control._props['type']=='number'
        assert not control.slots.get('append')  # No separately composed arrows.
        minimum=max(1,item['validation']['minimum'])
        assert control._props['step']=='1' and control._props['min']==str(minimum)
        assert control._props['max']==str(item['validation']['maximum'] or 9223372036854775807)
        with user:
            control.set_value(str(minimum));assert control.validate()
            control.set_value(str(minimum-1));assert not control.validate()
            if item['validation']['maximum']:
                control.set_value(str(item['validation']['maximum']+1));assert not control.validate()
    big=forms['content']['controls']['MAX_UPLOAD_SIZE_BYTES']
    with user:big.set_value('9007199254740993')
    assert big.value=='9007199254740993'
    changes=changed_rows([api.items['MAX_UPLOAD_SIZE_BYTES']],forms['content']['controls'])
    assert changes[0]['value']==9007199254740993


@pytest.mark.parametrize('language',['en','ar'])
async def test_successful_save_has_translated_toast_but_conflict_does_not(user:User,language):
    api,holder,_=await open_page(user,language)
    form=holder['state']['forms']['general']
    with user:form['controls']['REVIEW_WARNING_WINDOW_DAYS'].set_value('31')
    mark(user,form['reason']).type('Update warning window')
    api.fail=True
    mark(user,form['save']).click();await asyncio.sleep(.03)
    assert not user.notify.messages
    api.fail=False
    mark(user,form['save']).click();await asyncio.sleep(.06)
    assert len(user.notify.messages)==1
    assert strip_diagnostic_metadata(user.notify.messages[0])==(AR if language=='ar' else EN)['settings.page.saved']


@pytest.mark.parametrize('language',['en','ar'])
@pytest.mark.parametrize('reason',['','   '])
async def test_missing_reason_warns_without_saving_or_losing_draft(user:User,language,reason):
    api,holder,_=await open_page(user,language)
    form=holder['state']['forms']['general']
    with user:
        form['controls']['REVIEW_WARNING_WINDOW_DAYS'].set_value('29')
        form['reason'].set_value('First successful update')
    mark(user,form['save']).click();await asyncio.sleep(.06)
    assert len(api.saved)==1
    form=holder['state']['forms']['general']
    calls_before=list(api.calls)
    user.notify.messages.clear()
    with user:
        form['controls']['REVIEW_WARNING_WINDOW_DAYS'].set_value('31')
        form['reason'].set_value(reason)
    mark(user,form['save']).click();await asyncio.sleep(.03)
    assert len(api.saved)==1 and api.calls==calls_before
    assert form['controls']['REVIEW_WARNING_WINDOW_DAYS'].value=='31' and form['save'].enabled
    expected=(AR if language=='ar' else EN)['settings.error.reason_required']
    assert strip_diagnostic_metadata(form['feedback'].text)==expected
    assert [strip_diagnostic_metadata(message) for message in user.notify.messages]==[expected]
    saved=(AR if language=='ar' else EN)['settings.page.saved']
    assert not any(strip_diagnostic_metadata(label.text)==saved for label in user.find(ui.label).elements)


async def test_integer_minimum_blocks_invalid_save_without_rewriting_existing_zero(user:User):
    api,holder,_=await open_page(user)
    form=holder['state']['forms']['general']
    with user:form['controls']['REVIEW_WARNING_WINDOW_DAYS'].set_value('0')
    mark(user,form['reason']).type('Update warning window')
    mark(user,form['save']).click();await asyncio.sleep(.02)
    assert not api.saved and form['feedback'].text
    item=copy.deepcopy(api.items['REVIEW_WARNING_WINDOW_DAYS']);item['value']=0
    assert changed_rows([item],{item['key']:SimpleNamespace(value='0')})==[]


@pytest.mark.parametrize('language',['en','ar'])
async def test_scheme_first_browse_unlocks_both_two_character_destination_searches(user:User,language):
    api,holder,_=await open_page(user,language)
    form=holder['state']['forms']['disposition'];scheme=form['controls'][DESTINATION_KEYS[0]]
    assert 'lg:col-span-2' in scheme.parent_slot.parent.classes
    for key in DESTINATION_KEYS[1:]:
        assert not form['controls'][key].enabled and not form['browse_buttons'][key].enabled
        assert strip_diagnostic_metadata(form['selector_help'][key].text)==(AR if language=='ar' else EN)['settings.selector.choose_scheme']
    mark(user,form['browse_buttons'][DESTINATION_KEYS[0]]).click();await asyncio.sleep(.03)
    user.find('S01 · Scheme 1').click();await asyncio.sleep(.03)
    assert scheme.value==1
    for key in DESTINATION_KEYS[1:]:
        assert form['controls'][key].enabled and form['browse_buttons'][key].enabled
        control=form['controls'][key]
        for query in ('t','te'):
            with user:
                listener=next(v for v in control._event_listeners.values() if v.type=='inputValue')
                events.handle_event(listener.handler,events.GenericEventArguments(sender=control,client=user.client,args=query))
            await asyncio.sleep(.25)
    searches=[v for kind,v in api.calls if kind=='search']
    assert len(searches)==2
    assert all(v[1]=='te' and v[2]['limit']==25 and v[2]['filters']=={'classification_scheme_id':1,'is_terminal':True} for v in searches)
