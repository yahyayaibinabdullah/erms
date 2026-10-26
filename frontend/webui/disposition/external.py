"""Current request controls, required-letter forms and paginated decisions."""
import hashlib
import json
import shutil
import tempfile
from uuid import uuid4
from nicegui import ui
from ..api_client import ApiError
from ..resource_relationships import PageTable
from .acting_role import automatic_role
from .handoff import notify_completion,task_finished
from .messages import text
from .artifacts import show_destination


def request_controls(form,host=None):
    value=form.view.get('external')
    if not value:return
    with host or form.host:
        ui.label(text('request_form')).classes('text-lg font-semibold')
        if not value['approval_current'] and form.job.get('lifecycle_state','active')=='active':ui.label(text('approval_changed')).props('role=alert').classes('text-amber-900')
        if value.get('received_decision'):ui.label(text('external_approved' if value['received_decision']=='approved' else 'external_rejected')).props('role=status')
        if value.get('generation_error'):
            from .screens import failure
            ui.label(failure(ApiError(409,{'code':value['generation_error']}),lambda _:text('request_pending'))).props('role=alert').classes('text-amber-900')
        if value.get('request'):ui.label(value['request']['file_name']).props('dir=auto')
        buttons={}
        for action,allowed,roles in [('generate_request',value['can_generate'],value['manager_roles']),('renew_review',value['can_renew'],value['renew_roles'])]:
            if not allowed:continue
            role_id=automatic_role(roles)
            async def run(action=action,role_id=role_id):
                if form.dirty():ui.notify(text('unsaved_warning'),type='warning');return
                form.busy=True;button=buttons[action];button.disable()
                try:
                    suffix='request' if action=='generate_request' else 'renew-review'
                    result=await form.api.disposition_command(f"jobs/{form.job['id']}/review-rounds/{value['round_id']}/{suffix}",{'command_id':form.retry.setdefault(json.dumps([action,role_id,form.job['version']]),str(uuid4())),'acting_role_id':role_id},version=form.job['version'],reason=text(action))
                    if not form.alive():return
                    pending=result.get('request_status')=='pending'
                    notify_completion(result,'request_pending' if pending else 'review_completed',type='warning' if pending else 'positive')
                    form.busy=False;await task_finished(form,result)
                except ApiError as error:form.error(error)
                finally:
                    form.busy=False
                    if form.alive():button.enable()
            buttons[action]=ui.button(text(action),on_click=run).props('outline no-caps')


async def task_form(form):
    value=form.view.get('external') or {};request=value.get('request')
    with form.body:
        ui.label(text('await_external')).classes('font-semibold')
        if request:
            ui.label(request['file_name']).props('dir=auto')
            async def preview():
                if form.preview:await form.preview({'id':request['record_id'],'title':request['file_name']},request['digital_component_id'])
            async def download():
                try:content=await form.api.request('GET',f"/api/v1/disposition/jobs/{form.job['id']}/documents/{request['id']}/content",_cancellable_read=True)
                except ApiError as error:form.error(error);return
                if form.alive():ui.download(content,request['file_name'])
            with ui.row().classes('w-full gap-2'):
                if form.preview:ui.button(text('preview_request'),icon='visibility',on_click=preview).tooltip(text('preview_request')).props('outline no-caps')
                ui.button(text('download_request'),icon='download',on_click=download).tooltip(text('download_request')).props('outline no-caps')
        if 'external_decide' in form.actions:
            with ui.row().classes('w-full gap-2'):
                ui.button(text('external_approve'),icon='verified',on_click=lambda:decision_dialog(form,'approved')).tooltip(text('external_approve')).props('no-caps')
                ui.button(text('external_reject'),icon='assignment_return',on_click=lambda:decision_dialog(form,'rejected')).tooltip(text('external_reject')).props('outline no-caps')
        form.history_sections()
        await form.proposals_panel()


async def decision_dialog(form,decision):
    from .screens import failure
    with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[720px] max-w-full gap-4'):
        def alive():return form.alive() and dialog.value and not dialog._deleted
        ui.label(text('external_approve' if decision=='approved' else 'external_reject')).classes('text-xl font-semibold')
        number=ui.input(text('destruction_number')).props('outlined').classes('w-full') if decision=='approved' else None
        if number:ui.label(text('number_hint')).classes('text-sm text-slate-600')
        notes=ui.textarea(text('authority_notes')).props('outlined autogrow').classes('w-full') if decision=='rejected' else None
        state={'file':None,'name':None,'mime':None,'digest':None,'destination':None,'busy':False,'signature':None,'command_id':None}
        destination_host=ui.column().classes('w-full');feedback=ui.label('').props('role=alert').classes('text-negative')
        def uploaded(event):
            if not alive() or state['busy']:return
            if state['file']:state['file'].close()
            state['file']=None
            if len(event.contents)!=1:feedback.text=text('external_required');return
            stream=tempfile.SpooledTemporaryFile(max_size=8*1024*1024);shutil.copyfileobj(event.contents[0],stream,length=1024*1024);stream.seek(0)
            digest=hashlib.sha256()
            while chunk:=stream.read(1024*1024):digest.update(chunk)
            stream.seek(0);state.update(file=stream,name=event.names[0],mime=event.types[0] or 'application/octet-stream',digest=digest.hexdigest());feedback.text=''
        uploader=ui.upload(label=text('approval_letter' if number else 'rejection_letter'),multiple=False,auto_upload=True,max_files=1,on_multi_upload=uploaded).props('flat bordered').classes('w-full')
        async def destination():
            try:result=await form.api.disposition_page(f"jobs/{form.job['id']}/artifact-destination",document_type='external_approval_letter' if number else 'external_rejection_letter')
            except ApiError as error:
                if alive():feedback.text=failure(error,form.on_error)
                return
            if not alive():return
            state['destination']=result;destination_host.clear()
            with destination_host:show_destination(result,'evidence_destination')
            save.set_enabled(result['ready'])
        refresh=ui.button(text('refresh_destination'),icon='refresh',on_click=destination).tooltip(text('refresh_destination')).props('flat no-caps')
        async def submit():
            if not alive() or state['busy']:return
            dest=state['destination']
            if not state['file'] or not dest or not dest['ready'] or number is not None and (not str(number.value or '').strip() or len(number.value)>20) or notes is not None and not str(notes.value or '').strip():
                feedback.text=text('external_required');ui.notify(feedback.text,type='warning');return
            signature=(state['digest'],state['name'],state['mime'],dest['token'],form.acting_role_id,number.value if number else None,notes.value if notes else None)
            if signature!=state['signature']:state.update(signature=signature,command_id=str(uuid4()))
            controls=[uploader,refresh,save,cancel]+([number] if number else [])+([notes] if notes else [])
            state['busy']=True;form.busy=True
            for control in controls:control.disable()
            state['file'].seek(0)
            try:
                result=await form.api.record_external_decision(form.task['id'],version=form.job['version'],command_id=state['command_id'],acting_role_id=form.acting_role_id,task_version=form.task['version'],request_document_id=form.task['request_document_id'],decision=decision,correction_notes=notes.value if notes else None,destruction_number=number.value if number else None,destination_token=dest['token'],name=state['name'],content=state['file'],mime_type=state['mime'])
            except ApiError as error:
                if alive():feedback.text=failure(error,form.on_error);ui.notify(feedback.text,type='negative')
                return
            finally:
                state['busy']=False;form.busy=False
                if alive():
                    for control in controls:control.enable()
                else:cleanup()
            if not alive():return
            dialog.close();notify_completion(result,'external_approved' if number else 'external_rejected')
            if result.get('physical_report_status')=='pending':ui.notify(text('physical_report_pending'),type='warning')
            await task_finished(form,result)
        with ui.row().classes('w-full justify-end gap-2'):
            cancel=ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
            save=ui.button(text('save'),icon='save',on_click=submit).tooltip(text('save')).props('no-caps');save.disable()
        def cleanup():
            if not state['busy'] and state['file']:state['file'].close();state['file']=None
        dialog.on('hide',cleanup)
    dialog.open();await destination()
    return dialog


async def decisions_panel(form,host=None,active=None):
    from .screens import column
    with host or form.host:
        async def fetch(p):
            result=await form.api.disposition_page(f"jobs/{form.job['id']}/external-decisions",limit=p.size,offset=(p.page-1)*p.size,sort={'time_label':'recorded_at','decision_label':'decision'}.get(p.sort,p.sort or 'recorded_at'),descending=p.descending if p.sort else True)
            for row in result['items']:
                if row.get('redacted'):row.update(decision_label=text('restricted'));continue
                row['decision_label']=text(row['decision']);row['time_label']=form.format_timestamp(row['recorded_at'])
            return result
        return PageTable(columns=[column('review_round',sortable=True),column('request_name','request_form'),column('decision_label','external_decision',True),column('correction_notes','authority_notes'),column('letter_name','external_letter'),column('destruction_number',sortable=True),column('actor'),column('role','acting_task_role'),column('time_label','occurred',True)],fetch=fetch,active=active or form.alive,on_error=form.on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
