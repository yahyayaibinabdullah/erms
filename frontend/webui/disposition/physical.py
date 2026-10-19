"""Native physical preparation controls; operational actions remain release-gated."""
import hashlib
import shutil
import tempfile
from uuid import uuid4
from nicegui import ui
from ..api_client import ApiError
from .messages import text
from .artifacts import show_destination


def controls(form):
    value=form.view.get('physical')
    if not value:return
    with form.host:
        if not value.get('physical_required',True):
            if not value['released']:ui.label(text('disposition_physical_release_pending')).props('role=status').classes('text-amber-900')
            return
        ui.label(text('physical_preparation_report')).classes('text-lg font-semibold')
        if not value['released']:ui.label(text('disposition_physical_release_pending')).props('role=status').classes('text-amber-900')
        report=value.get('report')
        if report:
            ui.label(report['file_name']).props('dir=auto')
            with ui.row().classes('w-full gap-2'):
                async def preview():
                    if form.preview:await form.preview({'id':report['record_id'],'title':report['file_name']},report['digital_component_id'])
                async def download():
                    try:content=await form.api.request('GET',f"/api/v1/disposition/jobs/{form.job['id']}/documents/{report['id']}/content",_cancellable_read=True)
                    except ApiError as error:form.error(error);return
                    if form.alive():ui.download(content,report['file_name'])
                if form.preview and report.get('can_preview',False):ui.button(text('preview_physical_report'),icon='visibility',on_click=preview).props('outline no-caps')
                if report.get('can_download',False):ui.button(text('download_physical_report'),icon='download',on_click=download).props('outline no-caps')
        else:ui.label(text('physical_report_pending')).props('role=alert')
        if value['can_generate']:
            roles=value['manager_roles'];role=ui.select({r['id']:r['name'] for r in roles},label=text('acting_task_role'),value=roles[0]['id']).props('outlined dense').classes('w-full')
            async def generate(_=None):
                if form.busy or not form.alive():return
                form.busy=True;button.disable();role.disable()
                try:
                    signature=('physical_report',form.job['version'],role.value)
                    result=await form.api.disposition_command(f"jobs/{form.job['id']}/physical-preparation-report",{'command_id':form.retry.setdefault(signature,str(uuid4())),'acting_role_id':role.value},version=form.job['version'],reason=text('generate_physical_report'))
                    if form.alive():ui.notify(text('saved'),type='positive');await form.after(result)
                except ApiError as error:form.error(error)
                finally:
                    form.busy=False
                    if form.alive():button.enable();role.enable()
            button=ui.button(text('generate_physical_report'),icon='description',on_click=generate).props('outline no-caps')
        confirmation=value.get('confirmation')
        if confirmation:
            ui.label(text('physical_confirmed')).classes('font-semibold')
            ui.label(confirmation['certificate_reference']).props('dir=auto')
            ui.label(form.format_timestamp(confirmation['confirmed_at']))
            ui.label(confirmation['confirmation_text']).props('dir=auto')


async def task_form(form):
    with form.body:
        if 'check_physical_work' in form.actions:
            async def check(_=None):
                if form.busy:return
                form.busy=True;button.disable()
                try:
                    result=await form.api.disposition_command(f"tasks/{form.task['id']}/physical-work-check",{'command_id':str(uuid4()),'acting_role_id':form.role.value,'task_version':form.task['version']},version=form.job['version'],reason=text('check_physical_work'))
                    if form.alive():ui.notify(text('physical_work_checked'),type='positive')
                except ApiError as error:form.error(error)
                finally:
                    form.busy=False
                    if form.alive():button.enable()
            button=ui.button(text('check_physical_work'),icon='fact_check',on_click=check).props('outline no-caps')
        if 'confirm_physical' in form.actions:ui.button(text('confirm_physical'),icon='verified',on_click=lambda:confirmation_dialog(form)).props('no-caps')
        form.history_sections()


async def confirmation_dialog(form):
    from .screens import failure
    with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[720px] max-w-full gap-4'):
        def alive():return form.alive() and dialog.value and not dialog._deleted
        ui.label(text('confirm_physical')).classes('text-xl font-semibold')
        number=ui.input(text('physical_certificate_reference')).props('outlined').classes('w-full')
        successful=ui.checkbox(text('physical_confirmation_text'),value=False)
        state={'file':None,'name':None,'mime':None,'digest':None,'destination':None,'busy':False,'signature':None,'command_id':None}
        destination_host=ui.column().classes('w-full');feedback=ui.label('').props('role=alert').classes('text-negative')
        def uploaded(event):
            if not alive() or state['busy']:return
            if state['file']:state['file'].close()
            state['file']=None
            if len(event.contents)!=1:feedback.text=text('disposition_physical_required');return
            stream=tempfile.SpooledTemporaryFile(max_size=8*1024*1024);shutil.copyfileobj(event.contents[0],stream,length=1024*1024);stream.seek(0)
            digest=hashlib.sha256()
            while chunk:=stream.read(1024*1024):digest.update(chunk)
            stream.seek(0);state.update(file=stream,name=event.names[0],mime=event.types[0] or 'application/octet-stream',digest=digest.hexdigest());feedback.text=''
        uploader=ui.upload(label=text('physical_destruction_certificate'),multiple=False,auto_upload=True,max_files=1,on_multi_upload=uploaded).props('flat bordered').classes('w-full')
        async def destination():
            try:result=await form.api.disposition_page(f"jobs/{form.job['id']}/artifact-destination",document_type='physical_destruction_certificate')
            except ApiError as error:
                if alive():feedback.text=failure(error,form.on_error)
                return
            if not alive():return
            state['destination']=result;destination_host.clear()
            with destination_host:show_destination(result,'evidence_destination')
            save.set_enabled(result['ready'])
        refresh=ui.button(text('refresh_destination'),icon='refresh',on_click=destination).props('flat no-caps')
        async def submit():
            if not alive() or state['busy']:return
            dest=state['destination']
            if not state['file'] or not dest or not dest['ready'] or not str(number.value or '').strip() or not successful.value:
                feedback.text=text('disposition_physical_required');ui.notify(feedback.text,type='warning');return
            signature=(state['digest'],state['name'],state['mime'],dest['token'],form.role.value,number.value,successful.value)
            if signature!=state['signature']:state.update(signature=signature,command_id=str(uuid4()))
            controls=[uploader,refresh,save,cancel,number,successful]
            state['busy']=True;form.busy=True
            for control in controls:control.disable()
            state['file'].seek(0)
            try:
                result=await form.api.confirm_physical(form.task['id'],version=form.job['version'],command_id=state['command_id'],acting_role_id=form.role.value,task_version=form.task['version'],successful=successful.value,certificate_reference=number.value,destination_token=dest['token'],name=state['name'],content=state['file'],mime_type=state['mime'])
            except ApiError as error:
                if alive():feedback.text=failure(error,form.on_error);ui.notify(feedback.text,type='negative')
                return
            finally:
                state['busy']=False;form.busy=False
                if alive():
                    for control in controls:control.enable()
                else:cleanup()
            if not alive():return
            dialog.close();ui.notify(text('physical_confirmed'),type='positive');await form.after(result)
        with ui.row().classes('w-full justify-end gap-2'):
            cancel=ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
            save=ui.button(text('save'),icon='save',on_click=submit).props('no-caps');save.disable()
        def cleanup():
            if not state['busy'] and state['file']:state['file'].close();state['file']=None
        dialog.on('hide',cleanup)
    dialog.open();await destination()
    return dialog
