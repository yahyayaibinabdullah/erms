"""Readable actions, lazy bounded disclosures and shared contextual labels."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import pytest
from nicegui import ui
from frontend.webui.tests.test_disposition_tasks import host,Api,view
from frontend.webui.disposition.history import action_details
from frontend.webui.disposition.history_presenter import subject
from frontend.webui.disposition.messages import text
from frontend.webui.disposition.review import ReviewForm
from frontend.webui.event_labels import event_label


def test_distinct_recorded_changes_use_specific_labels_and_affected_proposals(host):
    events=[
        ('disposition_review_round',None,{'round_number':2}),
        ('disposition_job',{'current_review_round':1},{'current_review_round':2}),
        ('disposition_job',{'workflow_stage':'officer_correction'},{'workflow_stage':'records_manager_review'}),
        ('disposition_task',{'task_state':'open'},{'task_state':'completed','workflow_stage':'officer_correction'}),
        ('disposition_task',None,{'task_state':'open','workflow_stage':'records_manager_review'}),
    ]
    with host:
        labels=[event_label('REVIEW_SUBMIT',event=dict(entity_type=entity,metadata={'before':before,'after':after})) for entity,before,after in events]
        assert len(set(labels))==5 and labels[0]!=event_label('REVIEW_SUBMIT')
        for decision in ('approved','rejected'):
            assert event_label('REVIEW_DECIDE',event=dict(entity_type='disposition_review_decision',metadata={'after':{'review_stage':'records_manager_review','decision':decision}}))!=event_label('REVIEW_DECIDE')
        row={'entity_type':'disposition_review_proposal','metadata':{'after':{'proposal_type':'make_vital','target_aggregation_id':9}},'display_references':{'aggregation:9':'1141/DEMO/016/2026 · Meetings'}}
        assert text('make_vital') in subject(row) and '1141/DEMO/016/2026' in subject(row)
        hidden={**row,'metadata':{'redacted':True}}
        assert subject(hidden)==text('history_unavailable')
        assert event_label('REVIEW_SUBMIT',event=hidden)==event_label('REVIEW_SUBMIT')


@pytest.mark.asyncio
async def test_group_details_start_collapsed_load_one_server_page_and_ignore_abandoned_response(host):
    class HistoryApi:
        def __init__(self):self.reads=[];self.future=None
        async def disposition_page(self,path,**kwargs):
            self.reads.append((path,kwargs))
            if self.future:await self.future
            return {'total':300,'items':[dict(id=1,operation='REVIEW_SUBMIT',entity_type='disposition_review_round',occurred_at='2026-10-29',metadata={'after':{'round_number':2}})]}
    api=HistoryApi()
    row=dict(id=10,operation='REVIEW_SUBMIT',entity_type='disposition_review_round',occurred_at='2026-10-29',metadata={'after':{'round_number':2}},history_group={'event_count':300},reason='Authored reason <unchanged>')
    with host:
        await action_details(row,str,api=api,job_id=2,active=lambda:True,on_error=str)
        expansion=next(e for e in host.descendants() if isinstance(e,ui.expansion))
        assert not expansion.value and not api.reads
        expansion.value=True
        await expansion._change_handlers[-1](SimpleNamespace(value=True))
        assert api.reads==[('jobs/2/history/10/events',{'limit':25,'offset':0})]
        table=next(e for e in host.descendants() if isinstance(e,ui.table))
        assert 'erms-page-table' in table.classes and len(table.rows)==1
        assert table.rows[0]['subject_label']==text('tracker_round',number=2)
        expansion.value=False
        api.future=asyncio.get_running_loop().create_future()
        expansion.value=True
        pending=asyncio.create_task(expansion._change_handlers[-1](SimpleNamespace(value=True)))
        await asyncio.sleep(.02)
        dialog=next(e for e in host.descendants() if isinstance(e,ui.dialog));dialog.close()
        old=deepcopy(table.rows);api.future.set_result(None);await pending
        assert table.rows==old and len(api.reads)==2


@pytest.mark.asyncio
async def test_previous_comments_are_accessible_in_review_without_initial_history_request(host):
    workspace=view();workspace['job'].update(workflow_stage='records_manager_review',current_review_round=2)
    workspace['task'].update(workflow_stage='records_manager_review')
    api=Api()
    async def noop(*args):pass
    with host:
        form=ReviewForm(api=api,workspace=workspace,active=lambda:True,on_error=str,bind_remote=lambda *a,**k:None,after=noop,format_timestamp=str,open_resource=None)
        await form.load()
        expansion=next(e for e in form.body.descendants() if isinstance(e,ui.expansion) and e.text==text('tracker_previous'))
        assert not expansion.value and not any('workflow-progress' in path for path,_ in api.reads)
