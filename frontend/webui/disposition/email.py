"""Durable send controls shared across tabs; bounded, visibility-owned reads."""
import asyncio
import json
from uuid import uuid4
from nicegui import ui
from ..api_client import ApiError
from ..resource_relationships import PageTable
from .acting_role import automatic_role
from .messages import text


def _sender(form,value,doc):
    """Mounted-form state only; both tabs share one exact uncertain submission.

    Key: document ID in this identity/job/language-isolated form. No result cache:
    workspace supplies initial state, tab entry and acknowledged sends refresh it,
    and visible pending attempts poll until terminal. Failure keeps last known
    state and stops polling. Page abandonment discards state and late reads.
    """
    if not hasattr(form,'email_sends'):form.email_sends={}
    if doc['id'] in form.email_sends:return form.email_sends[doc['id']]
    choices={r['id']:r['name'] for r in value['roles'] if r['id'] in doc['role_ids']}
    state=dict(command_id=None,signature=None,busy=False,reading=False,buttons=[],summaries=[],latest=doc.get('latest_attempt'),role_id=automatic_role(choices))
    form.email_sends[doc['id']]=state
    def visible():return form.alive() and any(active() and not label._deleted for label,active in state['summaries'])
    def paint():
        latest=state['latest']
        label=text('email_not_sent') if not latest else ' · '.join([
            text('email_'+latest['status']),form.format_timestamp(latest.get('outcome_at') or latest['requested_at']),latest['recipient']])
        if form.alive():
            for target,_ in state['summaries']:
                if not target._deleted:target.set_text(label)
    async def refresh():
        if not visible() or state['reading']:return
        state['reading']=True
        try:
            page=await form.api.disposition_page(f"jobs/{form.job['id']}/email-attempts",document_id=doc['id'],limit=1,offset=0,sort='requested_at',descending=True)
            if not visible():return
            state['latest']=next(iter(page['items']),None);paint()
            timer.active=bool(state['latest'] and state['latest']['status']=='sending')
        except ApiError as error:
            timer.deactivate()
            if visible():form.error(error)
        finally:state['reading']=False
    async def poll():
        if not form.alive():timer.deactivate();return
        await refresh()
    timer=ui.timer(3,poll,active=bool(state['latest'] and state['latest']['status']=='sending'))
    state.update(refresh=refresh,paint=paint,timer=timer)
    async def refresh_all():await asyncio.gather(*(s['refresh']() for s in form.email_sends.values()))
    form.refresh_email_summaries=refresh_all
    return state


def send_button(form,value,doc,*,active=None):
    active=active or form.alive;state=_sender(form,value,doc)
    async def send(_=None):
        if not form.alive() or not active() or state['busy'] or form.busy:return
        if form.dirty():ui.notify(text('unsaved_warning'),type='warning');return
        signature=json.dumps([doc['id'],state['role_id'],value['recipient']])
        if state['signature']!=signature:state.update(signature=signature,command_id=str(uuid4()))
        state['busy']=True;form.busy=True
        for button in state['buttons']:
            if not button._deleted:button.disable()
        try:
            await form.api.disposition_command(f"jobs/{form.job['id']}/documents/{doc['id']}/email",{'command_id':state['command_id'],'acting_role_id':state['role_id'],'expected_recipient':value['recipient']},reason=text('send_email'))
            state.update(command_id=None,signature=None)
            if form.alive():ui.notify(text('email_queued'),type='positive')
        except ApiError as error:
            if form.alive():form.error(error)
        finally:
            state['busy']=False;form.busy=False
            if form.alive():
                for button in state['buttons']:
                    if not button._deleted:button.enable()
        if form.alive():
            await asyncio.gather(state['refresh'](),*(table.load() for table in getattr(form,'email_tables',[])))
    button=ui.button(text('send_email'),icon='mail',on_click=send).tooltip(text('send_email')).props('no-caps')
    state['buttons'].append(button)
    return button


def latest_attempt(form,value,doc,*,active=None):
    state=_sender(form,value,doc)
    with ui.column().classes('w-full gap-1'):
        ui.label(text('email_latest_attempt')).classes('text-sm font-semibold')
        label=ui.label('').props('dir=auto role=status').classes('text-sm break-words')
    state['summaries'].append((label,active or form.alive));state['paint']()


def controls(form,host=None):
    value=form.view.get('email')
    if not value:
        history_section(form,host)
        return
    active=getattr(form,'documents_active',form.alive)
    with host or form.host:
        if value['documents']:
            ui.label(text('email_recipient')).classes('font-semibold')
            ui.label(value['recipient'] or text('not_configured')).props('dir=auto')
            for doc in value['documents']:
                ui.label(doc['file_name']).props('dir=auto')
                send_button(form,value,doc,active=active)
                latest_attempt(form,value,doc,active=active)
        if value['documents']:ui.label(text('email_acceptance_hint')).classes('text-sm text-slate-600')
    history_section(form,host)


def history_section(form,host=None):
    """Reachable from both task and job documents, without an eager request."""
    if getattr(form,'email_history_built',False):return
    form.email_history_built=True
    with host or form.host:
        with ui.expansion(text('email_attempts'),icon='history').classes('w-full') as expansion:
            table_host=ui.column().classes('w-full gap-3')
    state={'page':None}
    def active():
        return form.alive() and getattr(form,'documents_active',form.alive)() and expansion.value and not expansion._deleted
    async def refresh():
        if not active():return
        with table_host:
            if state['page'] is None:state['page']=await attempts_panel(form,host=table_host,active=active)
            await state['page'].load()
    async def opened(event):
        if event.value:await refresh()
    expansion.on_value_change(opened)
    form.refresh_email_history=refresh


async def attempts_panel(form,host=None,active=None):
    from .screens import column
    with host or form.host:
        async def fetch(p):
            result=await form.api.disposition_page(f"jobs/{form.job['id']}/email-attempts",limit=p.size,offset=(p.page-1)*p.size,
              sort={'time_label':'requested_at','status_label':'status'}.get(p.sort,p.sort or 'requested_at'),descending=p.descending if p.sort else True)
            for row in result['items']:
                row.update(status_label=text('email_'+row['status']),time_label=form.format_timestamp(row['requested_at']),outcome_label=form.format_timestamp(row['outcome_at']) if row.get('outcome_at') else '',error_label=text(row['error_code']) if row.get('error_code') else '')
            return result
        table=PageTable(columns=[column('file_name','document'),column('status_label','email_status',True),column('recipient','email_recipient',True),column('sender','email_sender'),column('actor'),column('role','acting_task_role'),column('time_label','email_requested',True),column('outcome_label','email_outcome'),column('error_label','error')],fetch=fetch,active=active or form.alive,on_error=form.on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
        if not hasattr(form,'email_tables'):form.email_tables=[]
        form.email_tables.append(table)
        ui.label(text('email_acceptance_hint')).classes('text-sm text-slate-600')
        ui.button(text('refresh'),icon='refresh',on_click=table.load).tooltip(text('refresh')).props('outline no-caps')
        return table
