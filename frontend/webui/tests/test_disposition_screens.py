"""Disposition screen state, bounded requests, selection and localized controls."""
import asyncio
from types import SimpleNamespace
import pytest
from nicegui import ui
from frontend.webui.locale_services import set_locale_context
from frontend.webui.disposition.messages import status_label,KEYS
from frontend.webui.disposition.screens import jobs_screen,eligibility_screen
from frontend.webui.resource_relationships import PageTable


@pytest.fixture
def host():
    host=ui.column()
    with host:set_locale_context('en','Asia/Dubai')
    return host


@pytest.mark.asyncio
async def test_job_page_loads_context_and_one_bounded_page_concurrently(host):
    calls=[];started=asyncio.Event()
    async def request(path,**params):
        calls.append((path,params))
        if len(calls)==2:started.set()
        await asyncio.wait_for(started.wait(),1)
        return {'roles':[{'id':1,'name':'IG role'}]} if path=='context' else {'items':[],'total':0}
    remembered=[]
    with host:
        await jobs_screen(api=SimpleNamespace(disposition_page=request),container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=lambda identity:None,remember=remembered.append)
    assert {x[0] for x in calls}=={'context','jobs'}
    assert calls[1][1]['limit']==25 and calls[1][1]['offset']==0
    assert remembered[0]['page']==1


@pytest.mark.asyncio
async def test_eligibility_redacted_rows_disable_selection_and_never_hydrate_hidden_ids(host):
    calls=[]
    async def request(path,**params):
        calls.append((path,params))
        return {'roles':[{'id':1,'name':'IG role'}]} if path=='context' else {'items':[{'id':'redacted-0','redacted':True,'selectable':False}],'total':1}
    with host:
        await eligibility_screen(api=SimpleNamespace(disposition_page=request),container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=lambda identity:None,open_resource=lambda *a:None,format_timestamp=str)
    tables=[e for e in host.descendants() if isinstance(e,ui.table)]
    assert tables[0].rows[0]['identity'].startswith('Restricted')
    assert '!props.row.selectable' in tables[0].slots['body'].template
    assert {x[0] for x in calls}=={'context','eligibility'}
    assert all(c['headerStyle']=='vertical-align: top' for c in tables[0].columns)


@pytest.mark.asyncio
@pytest.mark.parametrize('language',['en','ar'])
@pytest.mark.parametrize('expanded',[False,True])
async def test_eligibility_filter_disclosure_remembers_only_active_changes(host,language,expanded):
    calls=[];choices=[];current={'active':True}
    async def request(path,**params):
        calls.append(path)
        return {'roles':[]} if path=='context' else {'items':[],'total':0}
    with host:
        set_locale_context(language,'Asia/Dubai')
        await eligibility_screen(api=SimpleNamespace(disposition_page=request),container=host,
            active=lambda:current['active'],on_error=str,bind_remote=lambda *a,**k:None,
            open_job=lambda *a:None,open_resource=lambda *a:None,format_timestamp=str,
            filters_expanded=expanded,remember_filters=choices.append)
    disclosure=next(e for e in host.descendants() if isinstance(e,ui.expansion))
    assert disclosure.value is expanded
    disclosure.value=not expanded;await asyncio.sleep(0)
    disclosure.value=expanded;await asyncio.sleep(0)
    assert choices==[not expanded,expanded]
    assert sorted(calls)==['context','eligibility']
    current['active']=False
    disclosure.value=not expanded;await asyncio.sleep(0)
    assert choices==[not expanded,expanded]


@pytest.mark.asyncio
async def test_guarded_loaded_callback_ignores_abandoned_and_obsolete_responses(host):
    futures=[];accepted=[]
    async def fetch(p):
        f=asyncio.get_running_loop().create_future();futures.append(f);return await f
    alive=[True]
    with host:
        page=PageTable(columns=[],fetch=fetch,active=lambda:alive[0],on_error=str,empty='empty',on_loaded=lambda p,r:accepted.append(r['items']))
        old=asyncio.create_task(page.load());await asyncio.sleep(0)
        new=asyncio.create_task(page.load());await asyncio.sleep(0)
        futures[1].set_result({'items':[{'id':2}],'total':1});await new
        futures[0].set_result({'items':[{'id':1}],'total':1});await old
        abandoned=asyncio.create_task(page.load());await asyncio.sleep(0);alive[0]=False
        futures[2].set_result({'items':[{'id':3}],'total':1});await abandoned
    assert accepted==[[{'id':2}]]


def test_all_stored_statuses_have_contextual_labels():
    assert all('status_'+str(i) in KEYS for i in range(1,14))
    assert status_label(6)=='Pending destruction'


@pytest.mark.asyncio
@pytest.mark.parametrize('language',['en','ar'])
@pytest.mark.parametrize('route,profile,destruction',[
    ('standard','INFO_GOV_OFFICER',True),('simplified','INFO_GOV_OFFICER',True),
    ('records_manager_only','INFO_GOV_MGR',True),('standard','INFO_GOV_MGR',False),
    ('records_manager_only','INFO_GOV_OFFICER',False)])
async def test_create_job_uses_route_and_auto_selects_single_role(host,monkeypatch,route,profile,destruction,language):
    from nicegui import core
    from frontend.webui.disposition.screens import create_dialog
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    with host:
        set_locale_context(language,'Asia/Dubai')
        await create_dialog(api=None,context={'destruction_review_route':route,
            'roles':[{'id':7,'name':'Governance role','profile_code':profile}]},
            bind_remote=lambda *a,**k:None,active=lambda:True,on_error=str,after=lambda *a:None)
    selects=[e for e in host.descendants() if isinstance(e,ui.select)]
    from frontend.webui.disposition.messages import text
    kind=next(e for e in selects if e.label==text('job_type'))
    assert 'destruction' in kind.options
    assert not any(isinstance(e,ui.textarea) for e in host.descendants())
    from frontend.webui.disposition.messages import text
    role=next(e for e in selects if e.label==text('role'))
    assert role.value==7 and not role.visible


@pytest.mark.asyncio
async def test_create_job_role_choices_follow_type_and_preserve_valid_selection(host,monkeypatch):
    from nicegui import core
    from frontend.webui.disposition.screens import create_dialog
    from frontend.webui.disposition.messages import text
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    with host:
        await create_dialog(api=None,context={'destruction_review_route':'records_manager_only',
            'roles':[{'id':1,'name':'Officer','profile_code':'INFO_GOV_OFFICER'},
                     {'id':2,'name':'Manager','profile_code':'INFO_GOV_MGR'}]},
            bind_remote=lambda *a,**k:None,active=lambda:True,on_error=str,after=lambda *a:None)
    selects=[e for e in host.descendants() if isinstance(e,ui.select)]
    kind=next(e for e in selects if e.label==text('job_type'))
    role=next(e for e in selects if e.label==text('role'))
    assert role.options=={1:'Officer',2:'Manager'} and role.value==1 and role.visible
    kind.value='permanent_transfer';await asyncio.sleep(0)
    assert role.visible and set(role.options)=={1,2} and role.value==1
    role.value=1
    kind.value='destruction';await asyncio.sleep(0)
    assert role.value==1 and role.visible


@pytest.mark.asyncio
async def test_restored_page_size_and_offset_make_exactly_one_page_request(host):
    calls=[]
    async def request(path,**params):
        calls.append((path,params))
        return {'roles':[{'id':1,'name':'IG role'}]} if path=='context' else {'items':[],'total':50}
    with host:
        await jobs_screen(api=SimpleNamespace(disposition_page=request),container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=lambda identity:None,saved={'page':2,'size':10})
        await asyncio.sleep(0)
    assert [params for path,params in calls if path=='jobs']==[{'limit':10,'offset':10,'query':'','lifecycle':None,'job_type':None,'owner':'','assignee':'','unassigned':False,'sort':'id','descending':True}]


def test_due_filters_use_working_timezone_and_require_explicit_overlap_choice(host):
    from frontend.webui.disposition.screens import date_filter
    from frontend.webui.api_client import ApiError
    with host:
        assert date_filter('2025-01-01T04:00')=='2025-01-01T00:00:00Z'
        set_locale_context('en','Europe/London')
        with pytest.raises(ApiError) as error:date_filter('2026-10-25T01:30')
        assert error.value.detail['message_key']=='timezone.validation.wall_time.ambiguous'
        from frontend.webui.disposition.screens import wall_filter
        control,fold=wall_filter('due_from',{'due_from':'2026-10-25T01:30'})
        assert fold.visible
        fold.value='earlier'
        assert date_filter(control.value,fold.value)=='2026-10-25T00:30:00Z'
        assert date_filter('2026-10-25T01:30','later')=='2026-10-25T01:30:00Z'
        with pytest.raises(ApiError) as error:date_filter('2026-03-29T01:30')
        assert error.value.detail['message_key']=='timezone.validation.wall_time.nonexistent'


@pytest.mark.asyncio
async def test_command_reason_warning_and_mixed_result_never_claim_total_success(host,monkeypatch):
    import inspect
    from nicegui import core
    from frontend.webui.disposition.screens import command_dialog
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    calls=[];notices=[];saved=[]
    monkeypatch.setattr(ui,'notify',lambda message,**options:notices.append((message,options.get('type'))))
    async def command(*args,**kwargs):
        calls.append((args,kwargs));return {'items':[{'root_id':1,'success':True},{'root_id':2,'success':False,'code':'disposition_stale_version'}]}
    async def after(result):saved.append(result)
    with host:
        await command_dialog(api=SimpleNamespace(disposition_command=command),context={'roles':[{'id':1,'name':'IG role'}]},active=lambda:True,on_error=str,title='add',build=lambda alive:lambda:{'items':[{'root_id':1,'expected_version':1},{'root_id':2,'expected_version':1}]},path='jobs/1/memberships',version=2,after=after)
        save=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text=='Save')
        handler=next(iter(save._event_listeners.values())).handler
        response=handler(None)
        if inspect.isawaitable(response):await response
        await asyncio.sleep(0)
        assert calls==[] and notices[-1][1]=='warning'
        reason=next(e for e in host.descendants() if isinstance(e,ui.textarea))
        reason.value='Authorized membership reason'
        response=handler(None)
        if inspect.isawaitable(response):await response
        await asyncio.sleep(0)
    assert len(calls)==1 and len(saved)==1
    assert notices[-1]==('Some roots were not added. Review the individual results.','warning')


@pytest.mark.asyncio
async def test_removed_reopened_episode_does_not_still_request_removal(host,monkeypatch):
    from nicegui import core
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    from frontend.webui.disposition.screens import job_screen
    async def request(path,**params):
        if path=='context':return {'roles':[{'id':1,'name':'IG role'}]}
        if path=='jobs/1/workspace':return {'job': {'id':1,'job_number':'JOB','job_type':'destruction','review_route':'standard','current_review_round':0,'lifecycle_state':'active','disposition_status':6,'workflow_stage':'officer_preparation','owner':'Owner','assignee':'Officer','assigned_user_id':1,'owning_org_unit_id':1,'version':2,'membership_editable':True,'owner_editable':True},'task':None,'actions':[],'roles':[],'management_roles':[]}
        if path.endswith('/documents'):return {'items':[],'total':0,'correction_roles':[]}
        if path.endswith('/artifact-destination'):return {'ready':False,'changed':False,'destination':None,'previous_destination':None,'warning':'disposition_destination_unset','token':'x'*64}
        if path.endswith('/memberships'):return {'items':[{'id':7,'root_aggregation_id':1,'root_version':2,'version':2,'aggregation_number':'ROOT','title':'Root','disposition_status':1,'membership_state':'removed','redacted':False,'added_at':'2026-01-01T00:00:00Z','removed_at':'2026-01-02T00:00:00Z','removal_required_reason':'reopened'}],'total':1}
        return {'items':[],'total':0}
    with host:
        await job_screen(api=SimpleNamespace(disposition_page=request),identity=1,container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=lambda identity:None,open_eligibility=lambda identity:None,open_resource=lambda *a:None,format_timestamp=str,event_label=str)
    navigation=next(e for e in host.descendants() if isinstance(e,ui.tabs))
    assert navigation.value=='workspace_details'
    navigation.value='members'
    await asyncio.sleep(.02)
    row=next(r for e in host.descendants() if isinstance(e,ui.table) for r in e.rows if r.get('root_aggregation_id')==1)
    assert row['membership_label']=='Removed' and row['notice']=='' and not row['can_remove']


@pytest.mark.parametrize('language',['en','ar'])
@pytest.mark.asyncio
async def test_existing_job_assignee_search_and_selected_hydration_use_saved_route_scope(host,language):
    from frontend.webui.disposition.screens import selector
    calls=[];callbacks={}
    async def request(path,**params):
        calls.append((path,params));return {'items':[{'id':7,'name':'Selected preparer'}]}
    def bind(control,*args,**kw):callbacks.update(kw)
    with host:
        set_locale_context(language,'Asia/Dubai')
        control=selector(api=SimpleNamespace(disposition_page=request),bind_remote=bind,
          kind='assignees',label='assignee',active=lambda:True,job_id=42,
          selected={'id':7,'name':'Selected preparer'})
    assert control.value==7 and callbacks['min_query_length']==2
    await callbacks['page_loader']('pr');await callbacks['selected_loader'](7)
    assert calls==[('selectors/assignees',{'query':'pr','job_type':'destruction','job_id':42}),
                   ('selectors/assignees',{'selected':7,'job_type':'destruction','job_id':42})]


@pytest.mark.asyncio
@pytest.mark.parametrize('language',['en','ar'])
async def test_eligibility_acceleration_labels_and_refresh_use_only_current_page(host,language,monkeypatch):
    import json
    from pathlib import Path
    from copy import deepcopy
    from frontend.webui.i18n_catalogue import set_active_messages, clear_active_messages
    from frontend.webui.disposition.messages import text
    from frontend.webui.disposition import screens
    pages=[]
    def capture_page(**kwargs):
        page=PageTable(**kwargs);pages.append(page);return page
    monkeypatch.setattr(screens,'PageTable',capture_page)
    catalogue=Path(__file__).resolve().parents[1]/'i18n'
    entries=json.loads((catalogue/'messages.en.json').read_text()) if language=='en' else json.loads((catalogue/'messages.ar.generated.json').read_text())['items']
    base=dict(id=1,redacted=False,selectable=True,aggregation_number='1141/DEMO/001/2026',title='Meetings',disposition_status=2,final_disposition='destruction',calculated_disposition_at='2031-10-22T05:33:00Z',date_closed='2026-10-22T05:33:00Z',owner='Records',owning_org_unit_id=1,rule_source='classification',rule_source_label='1141',vital=False,security=False,held=False,blocked=False,days_overdue=0,job_id=None)
    provenance=dict(occurred_at='2026-10-21T22:33:00Z',actor_name='Yahya',reason='<b>Exceptional reason</b>')
    rows=[dict(base,acceleration=provenance,blocked=True,vital=True,vital_count=1,selectable=False),dict(base,id=2,acceleration=None,job_id=7,job_number='JOB-7',selectable=False),dict(base,id=3,acceleration=None),dict(base,id=4,job_id=8,job_number='JOB-8',blocked=True,held=True,hold_count=None,selectable=False),dict(base,id='redacted-4',redacted=True,selectable=False)]
    calls=[]
    async def request(path,**params):
        calls.append((path,params))
        return {'roles':[]} if path=='context' else {'items':deepcopy(rows),'total':2}
    with host:
        set_locale_context(language,'Asia/Dubai')
        set_active_messages({i['message_key']:i.get('default_text',i.get('translated_text')) for i in entries})
        await eligibility_screen(api=SimpleNamespace(disposition_page=request),container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=lambda *a:None,open_resource=lambda *a:None,format_timestamp=str)
        table=next(e for e in host.descendants() if isinstance(e,ui.table))
        assert table.rows[0]['acceleration_label']==text('accelerated_badge',date='22 أكتوبر 2026' if language=='ar' else '22 Oct 2026')
        assert table.rows[0]['acceleration_reason']==provenance['reason']
        assert table.rows[1]['acceleration_label'] is None
        assert all('type_label' not in row for row in table.rows)
        assert next(c for c in table.columns if c['name']=='due_label')['label']==text('normal_due')
        slot=table.slots['body'].template
        assert 'props.row.type_label' not in slot and '{{ props.row.acceleration_reason }}' in slot
        assert 'v-else-if="props.row.days_overdue' in slot
        assert {p for p,_ in calls}=={'context','eligibility'} and len(calls)==2
        assert table.rows[0]['unavailable'] and text('vital') in table.rows[0]['unavailable_reason']
        assert table.rows[1]['unavailable'] and 'JOB-7' in table.rows[1]['unavailable_reason']
        assert table.rows[1]['admission_label']==text('in_active_job')
        assert not table.rows[2]['unavailable']
        assert 'JOB-8' in table.rows[3]['unavailable_reason'] and text('held') in table.rows[3]['unavailable_reason']
        assert 'unavailable_reason' not in table.rows[4] and 'unavailable' not in table.rows[4]
        assert 'bg-amber-50' in slot and 'name="lock"' in slot
        membership_filter=next(e for e in host.descendants() if isinstance(e,ui.select) and e.label==text('active_job'))
        assert membership_filter.value=='false' and calls[-1][1]['active_job']=='false'
        membership_filter.value='true'
        # Simulate a fresh page read after the acceleration is invalidated.
        rows[0]['acceleration']=None
        await pages[0].load()
        assert table.rows[0]['acceleration_label'] is None and len(calls)==3
        assert calls[-1][1]['active_job']=='true'
        membership_filter.value=''
        await pages[0].load()
        assert calls[-1][1]['active_job']=='all'
        set_active_messages({});clear_active_messages(host.client.id)


@pytest.mark.asyncio
@pytest.mark.parametrize('route,profile,expected',[('standard','INFO_GOV_MGR',None),('standard','INFO_GOV_OFFICER',7),('records_manager_only','INFO_GOV_MGR',7)])
async def test_job_creator_default_is_editable_and_creation_has_no_number_or_reason(host,monkeypatch,route,profile,expected):
    from nicegui import core
    from frontend.webui.disposition.screens import create_dialog
    from frontend.webui.disposition.messages import text
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    with host:
        await create_dialog(api=None,context={'destruction_review_route':route,'current_user':{'id':7,'name':'Creator'},'roles':[{'id':1,'name':'Governance','profile_code':profile}]},bind_remote=lambda *a,**k:None,active=lambda:True,on_error=str,after=lambda *a:None)
    selects=[e for e in host.descendants() if isinstance(e,ui.select)]
    assigned=next(e for e in selects if e.label==text('assignee'))
    kind=next(e for e in selects if e.label==text('job_type'))
    assert assigned.value==expected and assigned.enabled
    assert not any(isinstance(e,ui.textarea) for e in host.descendants())
    assert not any(isinstance(e,ui.input) and e.label==text('job_number') for e in host.descendants())
    kind.value='permanent_transfer';await asyncio.sleep(0)
    assert assigned.value==7
    assigned.set_options({8:'Other eligible person'},value=8)
    assert assigned.value==8


@pytest.mark.asyncio
@pytest.mark.parametrize('language',['en','ar'])
async def test_jobs_filters_sort_mapping_and_disclosure_are_restored(host,language,monkeypatch):
    from frontend.webui.disposition import screens
    pages=[];calls=[];disclosures=[];remembered=[]
    def capture(**kwargs):
        page=PageTable(**kwargs);pages.append(page);return page
    monkeypatch.setattr(screens,'PageTable',capture)
    async def request(path,**params):
        calls.append((path,params))
        return {'roles':[]} if path=='context' else {'items':[],'total':0}
    saved={'query':'DT','job_type':'destruction','lifecycle':'active','owner':'إدارة','assignee':'يحيى','unassigned':False,'sort':'type_label','descending':False}
    with host:
        set_locale_context(language,'Asia/Dubai')
        await jobs_screen(api=SimpleNamespace(disposition_page=request),container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=lambda *a:None,saved=saved,remember=remembered.append,filters_expanded=True,remember_filters=disclosures.append)
        disclosure=next(e for e in host.descendants() if isinstance(e,ui.expansion))
        assert disclosure.value is True
        disclosure.value=False;await asyncio.sleep(0)
        assert disclosures==[False]
        params=next(p for path,p in calls if path=='jobs')
        assert params['sort']=='job_type' and params['owner']=='إدارة' and params['assignee']=='يحيى'
        assert params['job_type']=='destruction' and params['lifecycle']=='active'
        assert remembered[-1]['query']=='DT'
        assert all(c.get('sortable') for c in pages[0].table.columns if c['name']!='actions')
        pages[0].sort='state_label';await pages[0].load()
        assert calls[-1][1]['sort']=='lifecycle_state'


@pytest.mark.asyncio
@pytest.mark.parametrize('language',['en','ar'])
async def test_chooser_creates_job_and_resumes_selection_only_while_open(host,monkeypatch,language):
    from nicegui import core
    from frontend.webui.disposition import screens
    from frontend.webui.disposition.messages import text
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    callbacks=[];chosen=[];calls=[]
    current={'active':True}
    context={'roles':[{'id':1,'name':'IG'}]}
    async def request(path,**params):
        calls.append((path,params))
        return {'owner':{'id':9,'name':'Parent'},'basis':'common_ancestor'} if path=='suggested-owner' else {'items':[],'total':0}
    async def create(**kwargs):callbacks.append(kwargs)
    async def choose(identity):chosen.append(identity)
    monkeypatch.setattr(screens,'create_dialog',create)
    with host:
        set_locale_context(language,'Asia/Dubai')
        await screens.choose_job_dialog(api=SimpleNamespace(disposition_page=request),context=context,
            bind_remote=lambda *a,**k:None,active=lambda:current['active'],on_error=str,choose=choose,root_ids=[1,2])
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog))
        search=next(e for e in host.descendants() if isinstance(e,ui.input))
        search.value='missing job'
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('create'))
        next(iter(button._event_listeners.values())).handler(None)
        await asyncio.sleep(0)
        assert callbacks[0]['context'] is context
        assert callbacks[0]['owner_suggestion']['owner']['id']==9
        assert calls[-1]==('suggested-owner',{'root_ids':[1,2]})
        # Cancelling creation does not choose a job or reset the original search.
        assert dialog.value and search.value=='missing job' and not chosen
        await callbacks[0]['after']({'id':42,'job_number':'DT-2026-42'})
        assert chosen==[42] and not dialog.value
        await callbacks[0]['after']({'id':43})
        assert chosen==[42]
        dialog.open();current['active']=False
        await callbacks[0]['after']({'id':44})
        assert chosen==[42]
        assert len(calls)==2 and calls[0][0]=='jobs' and calls[0][1]['limit']==25


@pytest.mark.asyncio
@pytest.mark.parametrize('basis,owner',[('same_unit',{'id':9,'name':'Owner'}),('common_ancestor',{'id':9,'name':'Parent'}),('no_common_ancestor',None)])
async def test_suggested_owner_prefills_editable_control_and_explains_scope(host,monkeypatch,basis,owner):
    from nicegui import core
    from frontend.webui.disposition.screens import create_dialog
    from frontend.webui.disposition.messages import text
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    with host:
        await create_dialog(api=None,context={'roles':[{'id':1,'name':'IG'}]},bind_remote=lambda *a,**k:None,
            active=lambda:True,on_error=str,after=lambda *a:None,owner_suggestion={'owner':owner,'basis':basis})
        control=next(e for e in host.descendants() if isinstance(e,ui.select) and e.label==text('owner'))
        assert control.value==(owner['id'] if owner else None) and control.enabled
        if basis!='same_unit':
            assert any(isinstance(e,ui.label) and e.text==text('owner_'+basis) for e in host.descendants())
        control.set_options({10:'Different unit'},value=10)
        assert control.value==10


def test_owner_selector_reuses_standard_relationship_presentation(host):
    from frontend.webui.disposition.screens import selector
    bindings=[]
    with host:
        control=selector(api=None,bind_remote=lambda *a,**k:bindings.append((a,k)),kind='owners',label='owner',active=lambda:True,selected={'id':9,'code':'RMD','name':'Records'})
    assert control.options[9]=='RMD · Records'
    assert 'relationship-select' in control.classes
    assert 'corporate_fare' in control.slots['prepend'].template
    assert 'q-badge' in control.slots['option'].template
    assert bindings[0][0][2:]==(('code','name'),('code','name'))
    assert bindings[0][1]['min_query_length']==2


@pytest.mark.asyncio
async def test_job_chooser_explains_and_rejects_incompatible_selection(host,monkeypatch):
    from nicegui import core
    from frontend.webui.disposition import screens
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    chosen=[];calls=[]
    async def request(path,**params):
        calls.append(params)
        return {'items':[{'id':1,'job_number':'DT-1','owner':'وحدة الوثائق','job_type':'destruction','selection_error':'disposition_owning_unit_mismatch'},
                         {'id':2,'job_number':'DT-2','job_type':'destruction','selection_error':None}],'total':2}
    async def choose(identity):chosen.append(identity)
    with host:
        await screens.choose_job_dialog(api=SimpleNamespace(disposition_page=request),context={'roles':[]},bind_remote=lambda *a,**k:None,active=lambda:True,on_error=str,choose=choose,root_ids=[10,20])
        table=next(e for e in host.descendants() if isinstance(e,ui.table))
        assert calls[0]['root_ids']==[10,20]
        assert table.rows[0]['selection_reason'] and not table.rows[1]['selection_reason']
        assert table.rows[0]['selection_owner']=='وحدة الوثائق' and table.rows[1]['selection_owner'] is None
        assert '<bdi>{{ props.row.selection_owner }}</bdi>' in table.slots['body-cell-actions'].template
        assert ':disable="!!props.row.selection_error"' in table.slots['body-cell-actions'].template
        listener=next(e for e in table._event_listeners.values() if e.type=='choose')
        await listener.handler(SimpleNamespace(args=1));assert chosen==[]
        await listener.handler(SimpleNamespace(args=2));assert chosen==[2]
