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
async def test_restored_page_size_and_offset_make_exactly_one_page_request(host):
    calls=[]
    async def request(path,**params):
        calls.append((path,params))
        return {'roles':[{'id':1,'name':'IG role'}]} if path=='context' else {'items':[],'total':50}
    with host:
        await jobs_screen(api=SimpleNamespace(disposition_page=request),container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=lambda identity:None,saved={'page':2,'size':10})
        await asyncio.sleep(0)
    assert [params for path,params in calls if path=='jobs']==[{'limit':10,'offset':10,'query':'','lifecycle':None,'sort':'id','descending':True}]


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
async def test_removed_reopened_episode_does_not_still_request_removal(host):
    from frontend.webui.disposition.screens import job_screen
    async def request(path,**params):
        if path=='context':return {'roles':[{'id':1,'name':'IG role'}]}
        if path=='jobs/1':return {'id':1,'job_number':'JOB','job_type':'destruction','lifecycle_state':'active','disposition_status':6,'workflow_stage':'officer_preparation','owner':'Owner','assignee':'Officer','assigned_user_id':1,'owning_org_unit_id':1,'version':2,'membership_editable':True,'owner_editable':True}
        if path.endswith('/documents'):return {'items':[],'total':0,'correction_roles':[]}
        if path.endswith('/artifact-destination'):return {'ready':False,'changed':False,'destination':None,'previous_destination':None,'warning':'disposition_destination_unset','token':'x'*64}
        if path.endswith('/memberships'):return {'items':[{'id':7,'root_aggregation_id':1,'root_version':2,'version':2,'aggregation_number':'ROOT','title':'Root','disposition_status':1,'membership_state':'removed','redacted':False,'added_at':'2026-01-01T00:00:00Z','removed_at':'2026-01-02T00:00:00Z','removal_required_reason':'reopened'}],'total':1}
        return {'items':[],'total':0}
    with host:
        await job_screen(api=SimpleNamespace(disposition_page=request),identity=1,container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=lambda identity:None,open_eligibility=lambda identity:None,open_resource=lambda *a:None,format_timestamp=str,event_label=str)
    row=next(e for e in host.descendants() if isinstance(e,ui.table)).rows[0]
    assert row['membership_label']=='Removed' and row['notice']=='' and not row['can_remove']
