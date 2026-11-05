"""Early, non-modal selection checks before either destination flow opens."""
import asyncio
from copy import deepcopy
from itertools import combinations
from types import SimpleNamespace
import pytest
from nicegui import ui,core,binding
from frontend.webui.disposition import screens
from frontend.webui.disposition.messages import text
from frontend.webui.tests.test_disposition_tasks import host
from frontend.webui.tests.test_disposition_bulk import click


@pytest.mark.asyncio
@pytest.mark.parametrize('target_job',[None,7])
@pytest.mark.parametrize('statuses',[(n,n) for n in range(2,6)]+list(combinations(range(2,6),2)))
async def test_mixed_disposition_selection_blocks_both_destination_paths_and_recovers(host,monkeypatch,target_job,statuses):
    await selection_case(host,monkeypatch,target_job,statuses,[1,1],{1:[1]},len(set(statuses))>1,False)


@pytest.mark.asyncio
@pytest.mark.parametrize('target_job',[None,7])
@pytest.mark.parametrize('owners,compatible,blocked',[
    ([1,1],{1:[1]},False),
    ([1,2,3],{1:[1,2,3],2:[1,2,3],3:[1,2,3]},False),
    ([2,3],{2:[2,3],3:[2,3]},False),
    ([1,2,3],{1:[1,2,3],2:[1,2,3],3:[1,2,3]},False),
    ([2,4],{2:[2],4:[4]},True),
])
async def test_owner_selection_allows_shared_ancestor_and_rejects_disconnected_units(host,monkeypatch,target_job,owners,compatible,blocked):
    await selection_case(host,monkeypatch,target_job,[2]*len(owners),owners,compatible,False,blocked)


@pytest.mark.asyncio
@pytest.mark.parametrize('target_job',[None,7])
async def test_both_selection_problems_are_explained_together(host,monkeypatch,target_job):
    await selection_case(host,monkeypatch,target_job,[2,3],[2,3],{2:[2],3:[3]},True,True)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',screens.TYPES)
async def test_creation_from_selection_prefills_type_and_nearest_owning_unit(host,kind):
    with host:
        await screens.create_dialog(api=None,context={'roles':[{'id':1,'profile_code':'INFO_GOV_OFFICER'}],
            'current_user':{'id':1,'name':'Officer'}},bind_remote=lambda *a,**kw:None,active=lambda:True,
            on_error=str,after=lambda *a:None,
            owner_suggestion={'owner':{'id':2,'name':'Nearest selected unit'},'basis':'common_ancestor','job_type':kind})
        fields=[e for e in host.descendants() if isinstance(e,ui.select)]
        assert next(e for e in fields if e.label==text('job_type')).value==kind
        assert next(e for e in fields if e.label==text('owner')).value==2
        assert any(isinstance(e,ui.label) and e.text==text('owner_common_ancestor') for e in host.descendants())


@pytest.mark.asyncio
@pytest.mark.parametrize('route',['standard','simplified','records_manager_only'])
@pytest.mark.parametrize('kind',['destruction','permanent_transfer'])
@pytest.mark.parametrize('fa,manager,key',[(False,False,'review_assign_both'),(False,True,'review_assign_file_administrator'),(True,False,'review_assign_unit_manager'),(True,True,None)])
async def test_standard_creation_warns_only_for_missing_routing_roles(host,route,kind,fa,manager,key):
    with host:
        await screens.create_dialog(api=None,context={'roles':[{'id':1,'profile_code':'INFO_GOV_OFFICER'}],
            'current_user':{'id':1,'name':'Officer'},'destruction_review_route':route},bind_remote=lambda *a,**kw:None,
            active=lambda:True,on_error=str,after=lambda *a:None,owner_suggestion={'owner':{'id':2,'name':'Unit',
            'review_role_setup':{'has_file_administrator':fa,'has_managing_role':manager,'has_file_administrator_assignment':fa,'has_managing_role_assignment':manager}},'basis':'same_unit','job_type':kind})
        warning=next(e for e in host.descendants() if isinstance(e,ui.label) and e._props.get('aria-live')=='polite')
        assert warning.visible==(route=='standard' and kind=='destruction' and key is not None)
        if warning.visible:assert text(key,unit='Unit') in warning.text and text('review_setup_create_blocked') in warning.text
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('save'))
        await asyncio.sleep(.12)
        assert button.enabled is not (route=='standard' and kind=='destruction' and key is not None)


@pytest.mark.asyncio
@pytest.mark.parametrize('abandoned',[False,True])
async def test_owner_role_warning_tracks_changes_and_ignores_obsolete_response(host,monkeypatch,abandoned):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());pending=[]
    async def request(path,**params):
        future=asyncio.get_running_loop().create_future();pending.append((params['selected'],future));return await future
    with host:
        await screens.create_dialog(api=SimpleNamespace(disposition_page=request),context={'roles':[{'id':1}],
            'destruction_review_route':'standard'},bind_remote=lambda *a,**kw:None,active=lambda:True,on_error=str,
            after=lambda *a:None,owner_suggestion={'owner':{'id':2,'name':'Unit','review_role_setup':
            {'has_file_administrator':False,'has_managing_role':False}},'basis':'same_unit'})
        owner=next(e for e in host.descendants() if isinstance(e,ui.select) and e.label==text('owner'))
        warning=next(e for e in host.descendants() if isinstance(e,ui.label) and e._props.get('aria-live')=='polite')
        assert warning.visible
        owner.set_options({3:'Other unit'},value=3);await asyncio.sleep(.01)
        owner.set_options({4:'Latest unit'},value=4);await asyncio.sleep(.01)
        assert [identity for identity,_ in pending]==[3,4]
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('save'))
        await asyncio.sleep(.12);assert not button.enabled
        if abandoned:next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value).close()
        pending[1][1].set_result({'items':[{'review_role_setup':{'has_file_administrator':True,'has_managing_role':True,'has_file_administrator_assignment':True,'has_managing_role_assignment':True}}]});await asyncio.sleep(.01)
        pending[0][1].set_result({'items':[{'review_role_setup':{'has_file_administrator':False,'has_managing_role':False}}]});await asyncio.sleep(.01)
        # Unit clients do not run NiceGUI's application-wide binding timer.
        binding._refresh_step()
        assert button.enabled is not abandoned
        assert warning.visible==abandoned
        if abandoned:assert warning.text==text('review_setup_checking')


async def selection_case(host,monkeypatch,target_job,statuses,owners,compatible,mixed_types,mixed_branches):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    opened=[];reads=[]
    async def chooser(**kw):opened.append('chooser')
    async def confirmation(**kw):opened.append('confirmation')
    monkeypatch.setattr(screens,'choose_job_dialog',chooser)
    monkeypatch.setattr(screens,'command_dialog',confirmation)
    rows=[dict(id=i,version=2,redacted=False,selectable=True,aggregation_number=f'A-{i}',title='Review selection',
        disposition_status=status,owning_org_unit_id=owner,compatible_owning_org_unit_ids=compatible[owner],
        final_disposition='destruction',calculated_disposition_at='2025-01-01',date_closed='2020-01-01',owner=f'Unit {owner}',
        rule_source='classification',rule_source_label='C',vital=False,security=False,held=False,blocked=False,job_id=None)
        for i,(status,owner) in enumerate(zip(statuses,owners),1)]
    async def request(path,**kw):
        reads.append(path)
        if path=='context':return {'roles':[{'id':1}]}
        if path=='jobs/7':return {'version':2,'job_number':'DT-7'}
        return {'items':deepcopy(rows),'total':len(rows)}
    with host:
        await screens.eligibility_screen(api=SimpleNamespace(disposition_page=request),container=host,active=lambda:True,on_error=str,
            bind_remote=lambda *a,**kw:None,open_job=lambda *a:None,open_resource=lambda *a:None,format_timestamp=str,target_job=target_job)
        table=next(e for e in host.descendants() if isinstance(e,ui.table))
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('add'))
        warning=next(e for e in host.descendants() if isinstance(e,ui.label) and e._props.get('aria-live')=='polite')
        changed=[e.handler for e in table._event_listeners.values() if e.type=='selection'][-1]
        assert not button.enabled and not warning.visible
        table.selected=table.rows;changed()
        blocked=mixed_types or mixed_branches
        assert button.enabled is not blocked and warning.visible==blocked
        assert (text('selection_mixed_types') in warning.text)==mixed_types
        assert (text('selection_mixed_branches') in warning.text)==mixed_branches
        await click(button)  # The callback also guards synthetic/stale clicks.
        assert opened==([] if blocked else ['chooser' if target_job is None else 'confirmation'])
        assert len(reads)==(2 if blocked or target_job is None else 3)
        assert not any(isinstance(e,ui.dialog) for e in host.descendants())
        table.selected=[table.rows[0]];changed()
        assert button.enabled and not warning.visible
        table.selected=[];changed()
        assert not button.enabled and not warning.visible
        table.selected=table.rows;changed()
        refresh=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('refresh'))
        await click(refresh)
        assert table.selected==[] and not button.enabled and not warning.visible


@pytest.mark.asyncio
@pytest.mark.parametrize('fa,manager',[(False,False),(False,True),(True,False)])
async def test_unstaffed_defined_roles_disable_save_and_explain_each_missing_assignment(host,fa,manager):
    calls=[]
    async def command(*a,**kw):calls.append(kw)
    with host:
        await screens.create_dialog(api=SimpleNamespace(disposition_command=command),context={'roles':[{'id':1,'profile_code':'INFO_GOV_OFFICER'}],
            'current_user':{'id':1,'name':'Officer'},'destruction_review_route':'standard'},bind_remote=lambda *a,**kw:None,
            active=lambda:True,on_error=str,after=lambda *a:None,owner_suggestion={'owner':{'id':2,'name':'Unit',
            'review_role_setup':{'has_file_administrator':True,'has_managing_role':True,
            'has_file_administrator_assignment':fa,'has_managing_role_assignment':manager}},'basis':'same_unit'})
        warning=next(e for e in host.descendants() if isinstance(e,ui.label) and e._props.get('aria-live')=='polite')
        key='review_assign_both' if not fa and not manager else 'review_assign_file_administrator' if not fa else 'review_assign_unit_manager'
        assert text(key,unit='Unit') in warning.text
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('save'))
        await asyncio.sleep(.12)
        assert not button.enabled
        await click(button)
        assert not calls


@pytest.mark.asyncio
async def test_creation_stays_disabled_while_saving_and_allows_retry_after_failure(host,monkeypatch):
    from frontend.webui.api_client import ApiError
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    pending=asyncio.get_running_loop().create_future();calls=[]
    async def command(*a,**kw):
        calls.append(kw);return await pending
    with host:
        await screens.create_dialog(api=SimpleNamespace(disposition_command=command),context={'roles':[{'id':1,'profile_code':'INFO_GOV_OFFICER'}],
            'current_user':{'id':1,'name':'Officer'},'destruction_review_route':'standard'},bind_remote=lambda *a,**kw:None,
            active=lambda:True,on_error=str,after=lambda *a:None,owner_suggestion={'owner':{'id':2,'name':'Unit',
            'review_role_setup':{'has_file_administrator':True,'has_managing_role':True,
            'has_file_administrator_assignment':True,'has_managing_role_assignment':True}},'basis':'same_unit'})
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('save'))
        assert button.enabled
        first=asyncio.create_task(click(button));await asyncio.sleep(.01)
        binding._refresh_step();assert not button.enabled
        await click(button);assert len(calls)==1
        pending.set_exception(ApiError(409,{'code':'disposition_stale_version'}))
        await first;await asyncio.sleep(.01);binding._refresh_step()
        assert button.enabled


@pytest.mark.asyncio
async def test_rejected_stale_readiness_refreshes_assignments_and_disables_save(host,monkeypatch):
    from frontend.webui.api_client import ApiError
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());reads=[]
    async def request(path,**params):
        reads.append((path,params))
        return {'items':[{'review_role_setup':{'has_file_administrator':True,'has_managing_role':True,
            'has_file_administrator_assignment':False,'has_managing_role_assignment':True}}]}
    async def command(*a,**kw):raise ApiError(409,{'code':'disposition_file_administrator_required'})
    with host:
        await screens.create_dialog(api=SimpleNamespace(disposition_command=command,disposition_page=request),
            context={'roles':[{'id':1,'profile_code':'INFO_GOV_OFFICER'}],'current_user':{'id':1,'name':'Officer'},
            'destruction_review_route':'standard'},bind_remote=lambda *a,**kw:None,active=lambda:True,on_error=str,
            after=lambda *a:None,owner_suggestion={'owner':{'id':2,'name':'Unit','review_role_setup':{
            'has_file_administrator':True,'has_managing_role':True,'has_file_administrator_assignment':True,
            'has_managing_role_assignment':True}},'basis':'same_unit'})
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('save'))
        assert button.enabled
        await click(button);await asyncio.sleep(.01);binding._refresh_step()
        assert not button.enabled
        assert reads==[('selectors/owners',{'selected':2,'job_type':'destruction'})]
        warning=next(e for e in host.descendants() if isinstance(e,ui.label) and e._props.get('aria-live')=='polite')
        assert text('review_assign_file_administrator',unit='Unit') in warning.text
