import asyncio
from copy import deepcopy
import pytest
from nicegui import ui,core
from frontend.webui.tests.test_disposition_tasks import host
from frontend.webui.disposition.process import process_diagram
from frontend.webui.disposition.messages import text


@pytest.mark.asyncio
async def test_previous_rounds_lazy_paging_no_duplicate_tracker_and_abandonment(host,monkeypatch):
    monkeypatch.setattr(core,"loop",asyncio.get_running_loop())
    timers=[]
    monkeypatch.setattr(ui,'timer',lambda interval,callback,**kw:timers.append(callback))
    row={'round_number':1,'started_at':'2026-10-22','actor_name':'Reviewer',
         'decisions':[{'review_stage':'unit_manager_review','decision':'rejected','reason':'Revise membership','decided_at':'2026-10-22','actor_name':'Manager'}]}
    calls=[];mounted=[True]
    class Api:
        async def disposition_page(self,path,**params):
            calls.append(params)
            return {'items':[deepcopy(row)],'has_more':len(calls)==1}
    with host:
        process_diagram({'id':1,'review_route':'standard','workflow_stage':'officer_correction','current_review_round':1},api=Api(),active=lambda:mounted[0],expanded=True)
        assert calls==[]
        await timers[0]()
        expansion=next(e for e in host.descendants() if isinstance(e,ui.expansion) and e._props['label']==text('tracker_previous'))
        assert not expansion.value
        expansion.value=True
        await asyncio.sleep(.01)
        assert len(calls)==1
        labels=[e.text for e in host.descendants() if isinstance(e,ui.label)]
        assert 'Revise membership' in labels
        assert labels.count(text('unit_manager_review'))==2 # current tracker and actual prior decision
        assert labels.count(text('records_manager_review'))==1 # not reached in prior round
        more=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('tracker_more'))
        next(iter(more._event_listeners.values())).handler(None)
        await asyncio.sleep(.02)
        assert calls==[{'limit':1,'offset':0},{'limit':25,'offset':1}]
        mounted[0]=False
        await timers[0]()
        assert len(calls)==2


@pytest.mark.asyncio
async def test_abandoned_response_does_not_render(host,monkeypatch):
    timers=[];mounted=[True]
    monkeypatch.setattr(ui,'timer',lambda interval,callback,**kw:timers.append(callback))
    class Api:
        async def disposition_page(self,*a,**k):
            mounted[0]=False
            return {'items':[{'round_number':99}],'has_more':False}
    with host:
        process_diagram({'id':1,'review_route':'standard','workflow_stage':'officer_correction','current_review_round':1},api=Api(),active=lambda:mounted[0])
        await timers[0]()
        assert not any(isinstance(e,ui.label) and '99' in e.text for e in host.descendants())


@pytest.mark.asyncio
async def test_manager_only_invalidation_is_not_a_submission_or_rejection(host,monkeypatch):
    timers=[]
    monkeypatch.setattr(ui,'timer',lambda interval,callback,**kw:timers.append(callback))
    class Api:
        async def disposition_page(self,*a,**k):
            return {'items':[{'id':1,'round_number':1,'started_at':'2026-10-22',
                'invalidated_at':'2026-10-23','invalidation_reason':'Facts changed','decisions':[
                    {'review_stage':'manager_preparation','decision':'approved','decided_at':'2026-10-22','actor_name':'Manager','reason':'Approved proposal set'}]}],'has_more':False}
    with host:
        process_diagram({'id':1,'review_route':'records_manager_only','workflow_stage':'manager_correction','current_review_round':1},api=Api())
        await timers[0]()
        labels=[e.text for e in host.descendants() if isinstance(e,ui.label)]
        badges=[e.text for e in host.descendants() if isinstance(e,ui.badge)]
        assert text('tracker_submitted') not in badges
        assert text('rejected') not in badges
        assert text('tracker_invalidated') in labels
        assert 'Facts changed' in labels
