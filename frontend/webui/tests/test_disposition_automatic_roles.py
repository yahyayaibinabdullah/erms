"""Remove internal attribution controls while preserving scoped commands and audit IDs."""
import asyncio
import inspect
from types import SimpleNamespace
import pytest
from nicegui import core,ui
from frontend.webui.disposition.acting_role import automatic_role
from frontend.webui.disposition.messages import text
from frontend.webui.disposition.screens import command_dialog
from frontend.webui.disposition.task_assignment import reassign_task
from frontend.webui.tests.test_disposition_tasks import host,form,view


def no_acting_control(host):
    assert not any(isinstance(e,ui.select) and e.label in (text('role'),text('acting_task_role')) for e in host.descendants())


@pytest.mark.parametrize('roles',[[{'id':19},{'id':7}],[{'id':7},{'id':19}],{19:'Role in Arabic',7:'Role in English'}])
def test_attribution_stable_for_projection_order_and_language(roles):
    assert automatic_role(roles)==7
    assert automatic_role([]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('path',['jobs/5/assignment','jobs/5/owning-unit','aggregations/10/accelerate','jobs/5/terminate'])
async def test_generic_dialog_has_no_role_field_and_sends_stable_authorized_id(host,monkeypatch,path):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop());monkeypatch.setattr(ui,'notify',lambda *a,**k:None)
    calls=[]
    async def send(path,payload,**kwargs):calls.append((path,payload));return {'id':1}
    async def after(result):pass
    with host:
        await command_dialog(api=SimpleNamespace(disposition_command=send),context={'roles':[{'id':19,'name':'Manager'},{'id':7,'name':'Officer'}]},active=lambda:True,on_error=str,title='assign',build=lambda active:lambda:{'assigned_user_id':42},path=path,version=3,after=after)
        no_acting_control(host)
        reason=next(e for e in host.descendants() if isinstance(e,ui.textarea));reason.value='Authorized handover'
        button=next(e for e in host.descendants() if isinstance(e,ui.button) and e.text==text('save'))
        result=next(iter(button._event_listeners.values())).handler(None)
        if inspect.isawaitable(result):await result
        await asyncio.sleep(0)
    assert calls[0][1]['acting_role_id']==7 and calls[0][1]['assigned_user_id']==42


@pytest.mark.asyncio
async def test_task_forms_use_task_qualified_role_without_exposing_a_selector(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    f,api,_=await form(host)
    assert f.acting_role_id==7
    no_acting_control(host)


@pytest.mark.asyncio
async def test_handover_keeps_real_destination_role_queue_choice(host,monkeypatch):
    monkeypatch.setattr(core,'loop',asyncio.get_running_loop())
    requests=[]
    def bind(control,kind,*args,**kwargs):requests.append((kind,kwargs))
    with host:
        await reassign_task(api=None,task={'id':8,'version':3,'destination_role_id':70,'role_queue':'Unit review queue'},roles=[{'id':19,'name':'Manager'},{'id':7,'name':'Reviewer'}],bind_remote=bind,active=lambda:True,on_error=str,after=None)
        no_acting_control(host)
        assert any(isinstance(e,ui.select) and e.label==text('role_queue') for e in host.descendants())
        assert {kind for kind,_ in requests}=={'users','roles'}
