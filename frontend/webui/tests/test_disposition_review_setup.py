"""Simple localized readiness warnings do not disable Save or correction actions."""
import asyncio
from types import SimpleNamespace
import pytest
from nicegui import ui,binding,core
from frontend.webui.api_client import ApiError
from frontend.webui.disposition import screens
from frontend.webui.disposition.messages import text,review_setup_message
from frontend.webui.disposition.review import ReviewForm
from frontend.webui.tests.test_disposition_tasks import host,view,Api
from frontend.webui.tests.test_disposition_bulk import click


@pytest.mark.parametrize('fa,manager,key',[(True,False,'review_assign_file_administrator'),(False,True,'review_assign_unit_manager'),(True,True,'review_assign_both'),(False,False,None)])
def test_simple_messages_explain_the_needed_people_and_system_administrator(host,fa,manager,key):
    with host:
        result=review_setup_message({'file_administrator_missing':fa,'unit_manager_missing':manager},'Records Unit')
        assert result==(text(key,unit='Records Unit') if key else '')


@pytest.mark.asyncio
@pytest.mark.parametrize('action',['submit','complete_review','approve'])
async def test_readiness_disables_only_progress_and_stays_disabled_after_comment_save(host,monkeypatch,action):
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    api=Api();workspace=view(actions=('save',action,'reject'))
    workspace['job']['review_setup']={'file_administrator_missing':False,'unit_manager_missing':True}
    async def after(result):pass
    with host:
        f=ReviewForm(api=api,workspace=workspace,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=after,format_timestamp=str,open_resource=None)
        await f.load();binding._refresh_step()
        progress=next(e for e in f.host.descendants() if isinstance(e,ui.button) and e.text==text(action))
        reject=next(e for e in f.host.descendants() if isinstance(e,ui.button) and e.text==text('reject'))
        assert not progress.enabled and reject.enabled
        await f.perform(action);assert not api.writes
        f.comments.value='Keep this work';await f.perform('save');binding._refresh_step()
        assert len(api.writes)==1 and api.writes[0][0].endswith('/review-work')
        assert not progress.enabled and reject.enabled and f.comments.enabled


@pytest.mark.asyncio
async def test_stale_server_readiness_error_disables_repeated_progress_but_keeps_work(host,monkeypatch):
    monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    api=Api();api.error=ApiError(409,{'code':'disposition_unit_manager_required'})
    async def after(result):pass
    with host:
        f=ReviewForm(api=api,workspace=view(),active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=after,format_timestamp=str,open_resource=None)
        await f.load();f.comments.value='Still here';await f.perform('submit')
        assert f.review_blocked and f.dirty() and f.comments.value=='Still here'
        assert not f.progress_buttons[0].enabled
        await f.perform('submit');assert len(api.writes)==1
        api.error=None;await f.perform('save')
        assert len(api.writes)==2 and not f.progress_buttons[0].enabled


@pytest.mark.asyncio
async def test_jobs_warning_uses_existing_page_and_clears_on_refresh(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    reads=[];blocked=True
    async def request(path,**params):
        reads.append((path,params))
        return {'roles':[]} if path=='context' else {'items':[{'id':5,'job_number':'DT-5','job_type':'destruction','owner':'Records Unit','disposition_status':6,'lifecycle_state':'active','review_setup':{'file_administrator_missing':False,'unit_manager_missing':blocked}}],'total':1}
    with host:
        await screens.jobs_screen(api=SimpleNamespace(disposition_page=request),container=host,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,open_job=lambda *a:None)
        table=next(e for e in host.descendants() if isinstance(e,ui.table))
        assert table.rows[0]['review_setup_warning']==text('review_setup_attention')
        assert len(table.columns)==6 and 'erms-page-table' in table.classes
        assert 'role="status"' in table.slots['body-cell-job_number'].template
        blocked=False
        await click(next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('refresh')))
        assert table.rows[0]['review_setup_warning']==''
        assert [path for path,_ in reads]==['context','jobs','jobs']
        assert all(p['limit']==25 and p['offset']==0 for path,p in reads if path=='jobs')


@pytest.mark.parametrize('unit',[
    "GMO · General Manager's Office",
    'Research & Development "Office"',
    'مكتب المدير العام · المدير العام’s Office',
    'Literal &amp; and &#x27; text',
    '<img src=x onerror="alert(1)">',
])
@pytest.mark.parametrize('fa,manager',[(True,False),(False,True),(True,True)])
def test_reviewer_warning_uses_shared_literal_text_rendering(host,unit,fa,manager):
    from frontend.webui.i18n_catalogue import ISOLATE_START,ISOLATE_END
    with host:
        flags={'file_administrator_missing':fa,'unit_manager_missing':manager}
        key='review_assign_both' if fa and manager else 'review_assign_file_administrator' if fa else 'review_assign_unit_manager'
        warning=review_setup_message(flags,unit)
        assert ISOLATE_START+unit+ISOLATE_END in warning
        assert warning == text(key,unit=unit)
        label=ui.label(warning)
        assert label.tag=='div' and label.text==warning and not list(label.descendants())


@pytest.mark.asyncio
async def test_create_warning_renders_apostrophe_like_the_selected_owner(host):
    unit="GMO · General Manager's Office"
    with host:
        await screens.create_dialog(api=None,context={'roles':[{'id':1,'profile_code':'INFO_GOV_OFFICER'}],
            'current_user':{'id':1,'name':'Officer'},'destruction_review_route':'standard'},
            bind_remote=lambda *a,**kw:None,active=lambda:True,on_error=str,after=lambda *a:None,
            owner_suggestion={'owner':{'id':2,'name':unit,'review_role_setup':{
                'has_file_administrator':False,'has_managing_role':True,
                'has_file_administrator_assignment':False,'has_managing_role_assignment':True}},'basis':'same_unit'})
        warning=next(e for e in host.descendants() if isinstance(e,ui.label) and e._props.get('aria-live')=='polite')
        owner=next(e for e in host.descendants() if isinstance(e,ui.select) and e.label==text('owner'))
        assert owner.options[owner.value]==unit
        assert unit in warning.text and '&#x27;' not in warning.text
        assert not next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('save')).enabled
