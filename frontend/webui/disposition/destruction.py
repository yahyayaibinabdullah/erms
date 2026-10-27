"""Native confirmed execution and bounded read-only retained proof views."""
import json
from html import escape
from uuid import uuid4
from nicegui import ui
from ..api_client import ApiError
from ..resource_relationships import PageTable
from .handoff import notify_completion
from .messages import text,KEYS
from .screens import column,failure


def controls(form):
    value=form.view.get('destruction')
    if not value or form.job['workflow_stage']!='digital_destruction':return
    state={'progress':value.get('progress'),'reading':False}
    with form.host:
        ui.label(text('execution_progress')).classes('text-lg font-semibold')
        summary=ui.label('').props('role=status')
        error=ui.label('').props('role=alert').classes('text-negative')
        def render(progress):
            if not progress:summary.text=text('execution_not_requested');error.text='';return
            summary.text=text('execution_counts',state=text('execution_'+progress['state']),completed=progress['overall_completed_units'],total=progress['overall_total_units'],queued=progress['queued_units'],running=progress['running_units'],failed=progress['failed_units'])
            error.text=text(progress['last_error_code']) if progress.get('last_error_code') in KEYS else text('execution_action_required') if progress['state']=='failed' else ''
        render(state['progress'])
        if 'destroy_digital' in form.actions:
            confirmed=ui.checkbox(text('digital_confirm'),value=False)
            async def execute(_=None):
                if not form.alive() or form.busy or not confirmed.value or not form.acting_role_id:return
                form.busy=True;button.disable();confirmed.disable()
                try:
                    signature=('digital',form.job['version'],form.task['version'],form.acting_role_id)
                    result=await form.api.disposition_command(f"tasks/{form.task['id']}/digital-destruction",{'command_id':form.retry.setdefault(signature,str(uuid4())),'acting_role_id':form.acting_role_id,'task_version':form.task['version'],'confirmed':True},version=form.job['version'],reason=text('destroy_digital'))
                    if form.alive():ui.notify(text('execution_requested'),type='positive');await form.after(result)
                except ApiError as problem:form.error(problem)
                finally:
                    form.busy=False
                    if form.alive():confirmed.enable();button.set_enabled(bool(confirmed.value and form.acting_role_id))
            button=ui.button(text('retry_digital') if state['progress'] else text('destroy_digital'),icon='delete_forever',on_click=execute).tooltip(text('retry_digital') if state['progress'] else text('destroy_digital')).props('no-caps color=negative')
            button.disable()
            confirmed.on_value_change(lambda:button.set_enabled(bool(confirmed.value and form.acting_role_id and not form.busy)))
        async def poll():
            if not form.alive():timer.deactivate();return
            if state['reading']:return
            state['reading']=True
            try:
                latest=await form.api.disposition_page(f"jobs/{form.job['id']}/destruction-progress")
                if not form.alive():timer.deactivate();return
                state['progress']=latest;render(latest)
                if not latest or latest['state'] in ('succeeded','failed'):
                    timer.deactivate()
                    if latest and latest['state']=='succeeded':
                        from .completion import status_message
                        notify_completion(latest,status_message(form.view))
                    await form.after(latest or {})
            except ApiError as problem:
                timer.deactivate()
                if form.alive():form.error(problem)
            finally:state['reading']=False
        timer=ui.timer(2,poll,active=bool(state['progress'] and state['progress']['state'] in ('queued','running')))


# QDialog caps direct cards at 560px, overriding NiceGUI width classes.
# Its Python API has no width parameter; use Wathiq's existing bounded card
# sizing pattern (app.py detail dialogs), scoped to these three proof dialogs.
async def retained_detail(*,api,proof,active,on_error,format_timestamp=str):
    dialog=ui.dialog()
    with dialog,ui.card().classes('p-5 gap-4').style('width: 1024px; max-width: calc(100vw - 32px)'):
        ui.label(text('retained_record')).classes('text-xl font-semibold')
        ui.label(text('retained_read_only')).classes('text-sm text-slate-600')
        from .messages import status_label
        facts=[('title',proof.get('title')),('number',proof.get('resource_number')),
               ('status',status_label(10)),('job_number',proof.get('job_number')),
               ('classification',proof.get('classification_label') or ' · '.join(str(v) for v in ((proof.get('classification_snapshot') or {}).get('code'),(proof.get('classification_snapshot') or {}).get('title')) if v)),
               ('owner',proof.get('owner_label') or (proof.get('owner_snapshot') or {}).get('name')),
               ('security_level_id',proof.get('security_label')),
               ('history_current_years',(proof.get('rule_snapshot') or {}).get('current_period_years')),
               ('history_intermediate_years',(proof.get('rule_snapshot') or {}).get('intermediate_period_years')),
               ('medium',text(proof['medium']) if proof.get('medium') in KEYS else proof.get('medium')),
               ('history_closed_at',format_timestamp(proof['date_closed']) if proof.get('date_closed') else None),
               ('due',format_timestamp(proof['calculated_disposition_at']) if proof.get('calculated_disposition_at') else None),
               ('history_executed_at',format_timestamp(proof['destroyed_at']) if proof.get('destroyed_at') else None),
               ('actor',proof.get('executor_label') or proof.get('executor_name')),('destruction_number',proof.get('destruction_number'))]
        with ui.grid().classes('w-full grid-cols-1 md:grid-cols-2 gap-4'):
            for label,value in facts:
                with ui.column().classes('w-full gap-1'):
                    ui.label(text(label)).classes('font-semibold')
                    ui.label(str(value) if value is not None and value!='' else '—').props('dir=auto').classes('whitespace-normal')
        async def manifest():
            await manifest_dialog(api=api,proof=proof,active=lambda:active() and dialog.value,on_error=on_error,format_timestamp=format_timestamp)
        if proof.get('manifest_count'):ui.button(text('destruction_manifest'),icon='fact_check',on_click=manifest).tooltip(text('destruction_manifest')).props('outline no-caps')
        ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
    if active():dialog.open()


async def retained_unit(*,api,root_id,active,on_error,format_timestamp):
    try:proof=await api.disposition_page(f'retained/aggregation/{root_id}')
    except ApiError as problem:
        if active():ui.notify(failure(problem,on_error),type='negative')
        return
    if not active():return
    dialog=ui.dialog()
    with dialog,ui.card().classes('p-5 gap-4').style('width: 1024px; max-width: calc(100vw - 32px)'):
        ui.label(text('retained_record')).classes('text-xl font-semibold')
        ui.label(text('retained_read_only')).classes('text-sm text-slate-600')
        def alive():return active() and dialog.value
        async def fetch(page):
            result=await api.disposition_page(f"jobs/{proof['job_id']}/retained-records",root_id=root_id,limit=page.size,offset=(page.page-1)*page.size,sort={'kind_label':'resource_kind','medium_label':'medium','at_label':'destroyed_at'}.get(page.sort,page.sort) or 'resource_id',descending=page.descending if page.sort else False)
            for row in result['items']:
                row['id']=str(row['resource_kind'])+':'+str(row['resource_id']);row['kind_label']=text(row['resource_kind']);row['medium_label']=text(row['medium']);row['at_label']=format_timestamp(row['destroyed_at'])
            return result
        page=PageTable(columns=[column('resource_id','retained_identifier',True),column('kind_label','retained_kind',True),column('medium_label','medium',True),column('at_label','occurred',True),column('executor_name','retained_executor'),column('actions')],fetch=fetch,active=alive,on_error=on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
        page.table.add_slot('body-cell-actions','''<q-td :props="props"><q-btn flat dense icon="description" aria-label="'''+escape(text('details'))+'''" @click="$parent.$emit('retained-detail',props.row.id)"><q-tooltip>'''+escape(text('details'))+'''</q-tooltip></q-btn></q-td>''')
        async def opened(event):
            row=next((r for r in page.table.rows if r['id']==event.args),None)
            if not row:return
            try:item=await api.disposition_page(f"retained/{row['resource_kind']}/{row['resource_id']}")
            except ApiError as problem:
                if alive():ui.notify(failure(problem,on_error),type='negative')
                return
            if alive():await retained_detail(api=api,proof=item,active=alive,on_error=on_error,format_timestamp=format_timestamp)
        page.table.on('retained-detail',opened)
        ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
    if not active():return
    dialog.open();await page.load()


async def manifest_dialog(*,api,proof,active,on_error,format_timestamp):
    dialog=ui.dialog()
    with dialog,ui.card().classes('p-5 gap-4').style('width: 1024px; max-width: calc(100vw - 32px)'):
        ui.label(text('destruction_manifest')).classes('text-xl font-semibold')
        async def fetch(page):
            result=await api.disposition_page(f"jobs/{proof['job_id']}/destruction-manifest",root_id=proof['root_id'],limit=page.size,offset=(page.page-1)*page.size,sort={'kind_label':'resource_kind','medium_label':'medium','state_label':'destruction_state'}.get(page.sort,page.sort) or 'id',descending=page.descending if page.sort else False)
            for row in result['items']:
                row['kind_label']=text('retained_component') if row['resource_kind']=='component' else text(row['resource_kind']);row['medium_label']=text(row['medium']);row['state_label']=text('execution_'+row['destruction_state'])
            return result
        page=PageTable(columns=[column('kind_label','retained_kind',True),column('resource_id','retained_identifier',True),column('medium_label','medium',True),column('size_in_bytes','manifest_size',True),column('checksum_value','manifest_checksum',True),column('state_label','execution_progress',True)],fetch=fetch,active=lambda:active() and dialog.value,on_error=on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
        ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
    if active():dialog.open();await page.load()
