"""Prominent server-owned progress; mounted-page polling has no shared cache."""
from uuid import uuid4
from nicegui import ui
from ..api_client import ApiError
from ..locale_services import current_locale_context
from .messages import text,KEYS
from .screens import failure


def panel(form,title):
    """Standard NiceGUI card used by durable approval and digital execution."""
    with getattr(form,'status_host',form.host):
        with ui.card().props('flat bordered').classes('w-full gap-3 bg-blue-50') as card:
            with ui.row().classes('items-center gap-3'):
                spinner=ui.spinner(size='lg').props('aria-hidden=true')
                ui.label(text(title)).classes('text-lg font-semibold')
            summary=ui.label('').props('role=status aria-live=polite').classes('font-medium')
            bar=ui.linear_progress(value=0,show_value=False,size='8px').props('aria-label='+repr(text(title))).classes('w-full')
            # NiceGUI has no constructor direction argument; QLinearProgress's
            # supported reverse prop follows the maintained Arabic UI direction.
            if current_locale_context()[0].split('-')[0]=='ar':bar.props('reverse')
            hint=ui.label(text('background_hint')).classes('text-sm text-slate-600')
            error=ui.label('').props('role=alert').classes('text-negative')
            actions=ui.row().classes('w-full gap-2 flex-wrap')
    return dict(card=card,summary=summary,bar=bar,spinner=spinner,hint=hint,error=error,actions=actions)


def controls(form):
    progress=form.view.get('operation')
    if not progress or progress['state']=='succeeded':return
    elements=panel(form,'approval_queued')
    state={'reading':False,'value':progress}
    def render(value):
        pending=value['state'] in ('queued','running')
        elements['summary'].text=text('approval_documents' if value['phase']=='documents' else 'approval_queued' if value['state']=='queued' else 'approval_processing') if pending else text('approval_documents_failed' if value['approval_committed'] else 'approval_failed')
        elements['spinner'].set_visibility(pending)
        elements['bar'].set_visibility(pending);elements['bar'].props('indeterminate' if pending else 'indeterminate=false')
        code=value.get('last_error_code');elements['error'].text=text(code) if code in KEYS else ''
        elements['hint'].set_visibility(pending)
    render(progress)
    if 'retry_approval_documents' in form.actions:
        async def retry():
            if not form.alive() or form.busy:return
            form.busy=True;button.disable()
            try:
                signature=('approval-documents',progress['operation_id'],form.acting_role_id)
                await form.api.disposition_command(f"jobs/{form.job['id']}/retry-approval-documents",{'command_id':form.retry.setdefault(signature,str(uuid4())),'acting_role_id':form.acting_role_id},reason=text('approval_retry_documents'))
                if form.alive():await form.after({})
            except ApiError as problem:form.error(problem)
            finally:
                form.busy=False
                if form.alive():button.enable()
        with elements['actions']:button=ui.button(text('approval_retry_documents'),icon='refresh',on_click=retry).props('no-caps')
    async def poll():
        if not form.alive():timer.deactivate();return
        if state['reading']:return
        state['reading']=True
        try:
            value=await form.api.disposition_page(f"jobs/{form.job['id']}/operation-progress")
            if not form.alive():timer.deactivate();return
            if not value:return
            with form.host:
                state['value']=value;render(value)
                if value['state'] in ('queued','running'):timer.activate()
                if value['state'] in ('succeeded','failed'):
                    timer.deactivate()
                    ui.notify(text('approval_ready' if value['state']=='succeeded' else 'approval_documents_failed' if value['approval_committed'] else 'approval_failed'),type='positive' if value['state']=='succeeded' else 'warning')
                    if value['state']=='succeeded' and form.on_approved:await form.on_approved(value)
                    else:await form.after({})
        except ApiError as problem:
            if form.alive():
                with form.host:elements['error'].text=text('progress_unavailable')
            # A lost status read is not failure of the durable operation.
        finally:state['reading']=False
    timer=ui.timer(2,poll,active=progress['state'] in ('queued','running'))
    with elements['actions']:ui.button(text('refresh'),icon='refresh',on_click=poll).props('outline no-caps')
