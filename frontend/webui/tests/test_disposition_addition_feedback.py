"""Counted membership feedback, bounded failure details and redaction."""
import asyncio
import inspect
from types import SimpleNamespace

import pytest
from nicegui import core, ui

from frontend.webui.disposition.screens import addition_feedback, eligibility_screen
from frontend.webui.disposition.messages import text
from frontend.webui.resource_relationships import PageTable, text as relationship_text
from frontend.webui.tests.test_disposition_tasks import host


async def click(button):
    callback=next(listener.handler for listener in button._event_listeners.values() if listener.type=='click')
    result=callback(None) if len(inspect.signature(callback).parameters) else callback()
    if inspect.isawaitable(result):await result
    await asyncio.sleep(0)


@pytest.mark.parametrize('count',[1,100])
def test_complete_success_is_one_counted_toast_without_a_result_list(host,monkeypatch,count):
    notices=[];monkeypatch.setattr(ui,'notify',lambda message,**kw:notices.append((message,kw)))
    with host:
        feedback=ui.column()
        addition_feedback(container=feedback,active=lambda:True,job_number='DT-2026-004',
                          labels={i:'Successful aggregation '+str(i) for i in range(count)},
                          result={'items':[{'root_id':i,'success':True} for i in range(count)]})
        assert notices==[(text('addition_success_one' if count==1 else 'addition_success_many',count=count,job='DT-2026-004'),{'type':'positive'})]
    assert not feedback.visible and not list(feedback.descendants())


@pytest.mark.asyncio
async def test_mixed_result_has_only_failed_details_and_ten_per_page(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    notices=[];monkeypatch.setattr(ui,'notify',lambda message,**kw:notices.append((message,kw)))
    results=[{'root_id':i,'success':i<83,**({'code':'disposition_stale_version'} if i>=83 else {})} for i in range(100)]
    labels={i:('Successful ' if i<83 else 'Failed ')+str(i) for i in range(100)}
    with host:
        feedback=ui.column()
        addition_feedback(container=feedback,active=lambda:True,result={'items':results},labels=labels,job_number='DT-7')
        assert notices==[(text('addition_partial',added=83,total=100,failed=17,job='DT-7'),{'type':'warning'})]
        button=next(e for e in feedback.descendants() if isinstance(e,ui.button))
        assert button.text==text('addition_view_failures',count=17)
        assert not any(isinstance(e,ui.label) for e in feedback.descendants())
        await click(button)
        dialog=next(e for e in feedback.descendants() if isinstance(e,ui.dialog))
        visible=[e.text for e in dialog.descendants() if isinstance(e,ui.label)]
        assert all(label not in visible for i,label in labels.items() if i<83)
        assert sum(label in visible for i,label in labels.items() if i>=83)==10
        assert text('addition_failure_range',start=1,end=10,total=17) in visible
        next_button=next(e for e in dialog.descendants() if isinstance(e,ui.button) and e._props.get('aria-label')==relationship_text('next'))
        await click(next_button)
        visible=[e.text for e in dialog.descendants() if isinstance(e,ui.label)]
        assert sum(label in visible for i,label in labels.items() if i>=83)==7
        assert text('addition_failure_range',start=11,end=17,total=17) in visible
        assert not next_button.enabled


@pytest.mark.asyncio
async def test_zero_success_warns_and_does_not_reveal_stale_identity_or_raw_error(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    notices=[];monkeypatch.setattr(ui,'notify',lambda message,**kw:notices.append((message,kw)))
    with host:
        feedback=ui.column()
        addition_feedback(container=feedback,active=lambda:True,job_number='DT-8',labels={1:'No longer accessible identity',2:'Visible aggregation'},
                          result={'items':[{'root_id':1,'success':False,'code':'disposition_resource_access_required'},
                                           {'root_id':2,'success':False,'code':'PRIVATE RAW ERROR'}]})
        assert notices==[(text('addition_none',job='DT-8'),{'type':'warning'})]
        await click(next(e for e in feedback.descendants() if isinstance(e,ui.button)))
        labels=[e.text for e in feedback.descendants() if isinstance(e,ui.label)]
        assert text('restricted') in labels and text('not_added') in labels
        assert 'No longer accessible identity' not in labels and 'PRIVATE RAW ERROR' not in labels


@pytest.mark.asyncio
async def test_abandoned_page_has_no_late_feedback_or_failure_dialog(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    notices=[];monkeypatch.setattr(ui,'notify',lambda *a,**kw:notices.append(a))
    live={'active':False}
    with host:
        feedback=ui.column()
        args=dict(container=feedback,active=lambda:live['active'],job_number='DT-9',labels={1:'Aggregation'},
                  result={'items':[{'root_id':1,'success':False}]})
        addition_feedback(**args)
        assert not notices and not list(feedback.descendants())
        live['active']=True;addition_feedback(**args)
        button=next(e for e in feedback.descendants() if isinstance(e,ui.button))
        live['active']=False;await click(button)
        assert not any(isinstance(e,ui.dialog) for e in feedback.descendants())


@pytest.mark.asyncio
async def test_real_addition_flow_notifies_once_and_refreshes_membership_state(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    from frontend.webui.disposition import screens
    pages=[];calls=[];notices=[]
    monkeypatch.setattr(ui,'notify',lambda message,**kw:notices.append((message,kw)))
    def capture(**kw):
        page=PageTable(**kw);pages.append(page);return page
    monkeypatch.setattr(screens,'PageTable',capture)
    row=dict(id=1,redacted=False,selectable=True,aggregation_number='A-1',title='Aggregation one',
             disposition_status=2,final_disposition='destruction',calculated_disposition_at='2025-01-01T00:00:00Z',
             date_closed='2020-01-01',owner='Unit',owning_org_unit_id=1,rule_source='classification',rule_source_label='C',
             vital=False,security=False,held=False,blocked=False,days_overdue=1,job_id=None,version=1)
    async def request(path,**kw):
        calls.append(path)
        if path=='context':return {'roles':[{'id':1,'name':'Officer'}]}
        if path=='jobs/7':return {'version':2,'job_number':'DT-7'}
        return {'items':[dict(row)],'total':1}
    async def command(*a,**kw):return {'items':[{'root_id':1,'success':True}]}
    with host:
        await eligibility_screen(api=SimpleNamespace(disposition_page=request,disposition_command=command),container=host,
                                 active=lambda:True,on_error=str,bind_remote=lambda *a,**kw:None,open_job=lambda *a:None,
                                 open_resource=lambda *a:None,format_timestamp=str,target_job=7)
        pages[0].table.selected=[pages[0].table.rows[0]]
        await click(next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('add')))
        await click(next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('save')))
        assert notices==[(text('addition_success_one',count=1,job='DT-7'),{'type':'positive'})]
        assert calls.count('eligibility')==2 and pages[0].table.selected==[]
