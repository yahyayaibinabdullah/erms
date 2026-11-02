"""Structured proposal dialog, lazy revisions, bounded pages and close guards."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import pytest
from nicegui import ui,core
from frontend.webui.api_client import ApiError
from frontend.webui.tests.test_disposition_tasks import host,Api,form
from frontend.webui.tests.test_disposition_proposal_presentation import proposal
from frontend.webui.disposition.proposal_details import ProposalRevisions,revision_changes
from frontend.webui.disposition.messages import text


@pytest.mark.asyncio
async def test_history_is_lazy_inline_and_refreshed_on_tab_return(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    class HistoryApi(Api):
        async def disposition_page(self,path,**params):
            if '/review-history/' in path:
                self.reads.append((path,params))
                return {'total':1,'items':[dict(id=1,operation='REVIEW_PROPOSAL_REVISED',entity_type='disposition_review_proposal',occurred_at='2026-10-29',actor_name='Reviewer',reason='Updated periods',can_view_technical_details=True,metadata={'before':{'proposed_values':{'current_period_years':1}},'after':{'proposed_values':{'current_period_years':2}}})]}
            return await super().disposition_page(path,**params)
    f,api,_=await form(host,HistoryApi())
    with host:
        await f.details(proposal())
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        tabs=next(e for e in dialog.descendants() if isinstance(e,ui.tabs))
        assert tabs.value=='details' and not any('/review-history/' in p for p,_ in api.reads)
        assert all(not e.value for e in dialog.descendants() if isinstance(e,ui.expansion))
        tabs.value='history';await asyncio.sleep(0)
        assert api.reads[-1]==('jobs/5/review-history/proposal/1',dict(limit=25,offset=0))
        entry=next(e for e in dialog.descendants() if isinstance(e,ui.expansion) and e.icon=='history')
        assert not entry.value
        assert not any(isinstance(e,ui.label) and e.text=='Updated periods' for e in entry.descendants())
        entry.value=True
        assert any(isinstance(e,ui.label) and e.text=='Updated periods' for e in entry.descendants())
        assert any(isinstance(e,ui.label) and e.text=='2' for e in entry.descendants())
        assert any(isinstance(e,ui.expansion) and e.icon=='code' and not e.value for e in entry.descendants())
        assert len([e for e in host.descendants() if isinstance(e,ui.dialog) and e.value])==1
        tabs.value='details';await asyncio.sleep(0);tabs.value='history';await asyncio.sleep(0)
        assert sum('/review-history/' in p for p,_ in api.reads)==2
    assert not api.writes


@pytest.mark.asyncio
async def test_revision_pages_errors_and_abandoned_responses(host):
    class HistoryApi:
        def __init__(self):self.reads=[];self.future=None;self.error=False
        async def disposition_page(self,path,**params):
            self.reads.append((path,params))
            if self.future:await self.future
            if self.error:raise ApiError(403,{'code':'forbidden'})
            return {'total':60,'items':[dict(id=len(self.reads),operation='REVIEW_PROPOSAL_CREATED',occurred_at='2026-10-29',metadata={'redacted':True},reason='DO NOT SHOW')]}
    api=HistoryApi();active=[True]
    review=SimpleNamespace(api=api,job={'id':5},format_timestamp=str,on_error=lambda e:'Access unavailable')
    with host:
        history=ProposalRevisions(review,7,lambda:active[0]);await history.load();await history.move(1)
        assert api.reads[-1]==('jobs/5/review-history/proposal/7',dict(limit=25,offset=25))
        entry=next(e for e in history.entries.descendants() if isinstance(e,ui.expansion));entry.value=True
        entry._change_handlers[-1](SimpleNamespace(value=True))
        assert text('history_unavailable') in [e.text for e in entry.descendants() if isinstance(e,ui.label)]
        assert 'DO NOT SHOW' not in [e.text for e in entry.descendants() if isinstance(e,ui.label)]
        api.future=asyncio.get_running_loop().create_future();old=list(history.entries.default_slot.children)
        pending=asyncio.create_task(history.load());await asyncio.sleep(0);active[0]=False;api.future.set_result(None);await pending
        assert history.entries.default_slot.children==old
        active[0]=True;api.future=None;api.error=True;await history.load()
        assert history.status.text=='Access unavailable' and not history.entries.default_slot.children


@pytest.mark.asyncio
async def test_partial_proposal_retains_permitted_information_without_history_tab(host):
    f,api,_=await form(host)
    row=proposal();row.update(redacted=True,partial=True,target_summary={'number':'AGG-10','title':'Visible target'})
    row.pop('current_values');row.pop('proposed_values')
    with host:
        await f.details(row)
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog) and e.value)
        assert [e._props['name'] for e in dialog.descendants() if isinstance(e,ui.tab)]==['details']
        labels=[e.text for e in dialog.descendants() if isinstance(e,ui.label)]
        assert 'Original author' in labels and 'AGG-10 · Visible target' in labels
        assert 'Authored reason' not in labels and text('restricted_text') in labels
    assert not any('/review-history/' in path for path,_ in api.reads)


def test_revision_comparison_keeps_cleared_values_and_hides_internal_attribution(host):
    with host:
        row={'metadata':{'before':{'proposed_values':{'instructions':'Old instructions','current_period_years':1},'version':1},'after':{'proposed_values':{'instructions':None,'current_period_years':2},'version':2,'last_revised_by_user_id':99}}}
        changes=revision_changes(row,str)
        assert (text('instructions'),'Old instructions',text('history_not_set')) in changes
        assert (text('current_period_years'),'1','2') in changes
        assert len(changes)==2
        row['metadata']['redacted']=True
        assert revision_changes(row,str)==[]
