"""Native termination and explicit single/all-unit status-13 recovery forms."""
from nicegui import ui
from ..api_client import ApiError
from .messages import text,status_label
from .screens import command_dialog,failure


def controls(*,api,job,value,active,on_error,after,can_mutate=lambda:True):
    if not value:return
    context={'roles':value['roles']}
    if value['physical_confirmed'] and job['lifecycle_state']=='active':
        ui.label(text('physical_recovery_warning')).props('role=alert').classes('text-amber-900')
    async def terminate(_=None):
        if not can_mutate():ui.notify(text('unsaved_warning'),type='warning');return
        def build(alive):
            confirmed=ui.checkbox(text('terminate_confirm'),value=False)
            return lambda:{'confirmed':True} if confirmed.value else None
        await command_dialog(api=api,context=context,active=active,on_error=on_error,title='terminate_job',confirm='physical_recovery_warning' if value['physical_confirmed'] else 'terminate_hint',build=build,path=f"jobs/{job['id']}/terminate",version=job['version'],after=after)
    async def bulk(_=None):
        if not can_mutate():ui.notify(text('unsaved_warning'),type='warning');return
        try:preview=await api.disposition_page(f"jobs/{job['id']}/partial-recovery-preview")
        except ApiError as error:
            if active():ui.notify(failure(error,on_error),type='negative')
            return
        if not active():return
        if not preview['affected_count']:ui.notify(text('disposition_recovery_empty'),type='warning');return
        def build(alive):
            ui.label(text('recover_count',count=preview['affected_count']))
            selected=ui.select({i:status_label(i) for i in range(2,6)},label=text('recovery_status'),value=None).props('outlined').classes('w-full')
            confirmed=ui.checkbox(text('recover_all_confirm'),value=False)
            return lambda:{'target_status':selected.value,'confirmed':True,**preview} if selected.value in range(2,6) and confirmed.value else None
        await command_dialog(api=api,context=context,active=active,on_error=on_error,title='recover_all',confirm='recovery_hint',build=build,path=f"jobs/{job['id']}/partial-recovery",after=after)
    with ui.row().classes('w-full gap-3'):
        if value['can_terminate']:ui.button(text('terminate_job'),icon='stop_circle',on_click=terminate).tooltip(text('terminate_job')).props('outline no-caps color=negative')
        if value['can_resolve_bulk']:ui.button(text('recover_all'),icon='restore',on_click=bulk).tooltip(text('recover_all')).props('outline no-caps')


async def resolve_unit(*,api,job,row,roles,active,on_error,after):
    def build(alive):
        ui.label(row['identity']).props('dir=auto')
        selected=ui.select({i:status_label(i) for i in range(2,6)},label=text('recovery_status'),value=None).props('outlined').classes('w-full')
        return lambda:{'target_status':selected.value,'root_version':row['root_version']} if selected.value in range(2,6) else None
    await command_dialog(api=api,context={'roles':roles},active=active,on_error=on_error,title='recover_unit',confirm='recovery_hint',build=build,path=f"jobs/{job['id']}/partial-recovery/{row['root_aggregation_id']}",after=after)
