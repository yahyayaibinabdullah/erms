"""Durable send controls and lazy attempt history; no browser-owned send task."""
import json
from uuid import uuid4
from nicegui import ui
from ..api_client import ApiError
from ..resource_relationships import PageTable
from .messages import text


def controls(form):
    value=form.view.get('email')
    if not value:return
    with form.host:
        if value['documents']:
            ui.label(text('email_recipient')).classes('font-semibold')
            ui.label(value['recipient'] or text('not_configured')).props('dir=auto')
            for doc in value['documents']:
                ui.label(doc['file_name']).props('dir=auto')
                choices={r['id']:r['name'] for r in value['roles'] if r['id'] in doc['role_ids']}
                role=ui.select(choices,label=text('acting_task_role'),value=next(iter(choices))).props('outlined dense').classes('w-full')
                state={'command_id':None,'signature':None,'busy':False}
                async def send(_=None,*,doc=doc,role=role,state=state):
                    if form.dirty():ui.notify(text('unsaved_warning'),type='warning');return
                    if state['busy']:return
                    signature=json.dumps([doc['id'],role.value,value['recipient']])
                    if state['signature']!=signature:state.update(signature=signature,command_id=str(uuid4()))
                    state['busy']=True;form.busy=True;role.disable();state['button'].disable()
                    try:
                        await form.api.disposition_command(f"jobs/{form.job['id']}/documents/{doc['id']}/email",{'command_id':state['command_id'],'acting_role_id':role.value,'expected_recipient':value['recipient']},reason=text('send_email'))
                        # Clear only on acknowledgement. A deliberately later
                        # click sends again; an uncertain retry keeps the key.
                        state.update(command_id=None,signature=None)
                        if form.alive():ui.notify(text('email_queued'),type='positive')
                    except ApiError as error:
                        if form.alive():form.error(error)
                    finally:
                        state['busy']=False;form.busy=False
                        if form.alive():role.enable();state['button'].enable()
                    if form.alive():
                        for table in getattr(form,'email_tables',[]):await table.load()
                state['button']=ui.button(text('send_email'),icon='mail',on_click=send).props('no-caps')
        if value['documents']:ui.label(text('email_acceptance_hint')).classes('text-sm text-slate-600')


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
        ui.button(text('refresh'),icon='refresh',on_click=table.load).props('outline no-caps')
        return table
