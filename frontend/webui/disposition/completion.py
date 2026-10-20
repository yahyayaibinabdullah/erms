"""Native certificate controls; server-owned work survives page abandonment."""
from uuid import uuid4
from nicegui import ui
from ..api_client import ApiError
from .messages import text,KEYS
from .artifacts import show_destination


def controls(form):
    value=form.view.get('completion')
    if not value:return
    with form.host:
        if value['completed']:
            ui.label(text('completion_external_copies_warning')).props('role=alert').classes('text-amber-900 font-semibold')
        progress=value.get('progress')
        if progress and not value['completed']:
            ui.label(text('generate_certificate')).classes('text-lg font-semibold')
            ui.label(text('certificate_'+progress['state'])).props('role=status')
            if progress.get('last_error_code'):
                code=progress['last_error_code']
                ui.label(text(code) if code in KEYS else text('disposition_certificate_generation_failed')).props('role=alert').classes('text-negative')
            if value.get('destination'):show_destination(value['destination'],'digital_destruction_certificate')
            if 'retry_certificate' in form.actions:
                async def retry():
                    if not form.alive() or form.busy or not form.role.value:return
                    form.busy=True;button.disable();form.role.disable()
                    try:
                        signature=('certificate',form.job['version'],form.task['version'],form.role.value)
                        result=await form.api.disposition_command(f"jobs/{form.job['id']}/retry-certificate",{'command_id':form.retry.setdefault(signature,str(uuid4())),'acting_role_id':form.role.value,'task_id':form.task['id'],'task_version':form.task['version']},version=form.job['version'],reason=text('retry_certificate'))
                        if form.alive():ui.notify(text('certificate_retry_requested'),type='positive');await form.after(result)
                    except ApiError as problem:form.error(problem)
                    finally:
                        form.busy=False
                        if form.alive():button.enable();form.role.enable()
                button=ui.button(text('retry_certificate'),icon='refresh',on_click=retry).props('outline no-caps')
        certificate=value.get('certificate')
        if certificate:
            ui.label(text('digital_destruction_certificate')).classes('text-lg font-semibold')
            ui.label(certificate['file_name']).props('dir=auto')
            if certificate['can_download']:
                async def download():
                    if not form.alive() or form.busy:return
                    form.busy=True;download_button.disable()
                    try:
                        content=await form.api.request('GET',f"/api/v1/disposition/jobs/{form.job['id']}/documents/{certificate['id']}/content",_cancellable_read=True)
                        if form.alive():
                            ui.download(content,certificate['file_name']);ui.notify(text('certificate_download_recorded'),type='positive');await form.after({})
                    except ApiError as problem:form.error(problem)
                    finally:
                        form.busy=False
                        if form.alive():download_button.enable()
                download_button=ui.button(text('download_digital_certificate'),icon='download',on_click=download).props('outline no-caps')
        polling={'reading':False}
        async def poll():
            if not form.alive():timer.deactivate();return
            if polling['reading']:return
            polling['reading']=True
            try:
                latest=await form.api.disposition_page(f"jobs/{form.job['id']}/completion-progress")
                if not form.alive():timer.deactivate();return
                if not latest or latest['completed'] or not latest.get('progress') or latest['progress']['state'] not in ('queued','running'):
                    timer.deactivate();await form.after(latest or {})
            except ApiError as problem:
                timer.deactivate()
                if form.alive():form.error(problem)
            finally:polling['reading']=False
        timer=ui.timer(2,poll,active=bool(progress and progress['state'] in ('queued','running') and not value['completed']))
