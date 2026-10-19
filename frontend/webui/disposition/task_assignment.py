"""Reasoned handover using current bounded task candidates and task versions."""
import json
from uuid import uuid4
from nicegui import ui
from ..remote_select import RemoteSelect
from ..api_client import ApiError
from .messages import text
from .screens import failure


async def reassign_task(*,api,task,roles,bind_remote,active,on_error,after):
    with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[650px] max-w-full gap-4'):
        def alive():return active() and dialog.value and not dialog._deleted
        ui.label(text('reassign')).classes('text-xl font-semibold')
        role=ui.select({r['id']:r['name'] for r in roles},label=text('acting_task_role'),value=roles[0]['id']).props('outlined dense').classes('w-full')
        mode=ui.select({k:text(k) for k in ('reassign_person','reassign_queue')},label=text('assignment_mode'),value='reassign_person').props('outlined dense').classes('w-full')
        controls={}
        for kind,label in [('users','assignee'),('roles','role_queue')]:
            control=RemoteSelect({},label=text(label),with_input=True).props('outlined dense clearable').classes('w-full');controls[kind]=control
            async def request(kind=kind,**params):return await api.disposition_page(f"tasks/{task['id']}/assignment-candidates/{kind}",acting_role_id=role.value,**params)
            async def load(query,request=request):return await request(query=query)
            async def hydrate(identity,request=request):
                response=await request(selected=identity)
                if not response['items']:raise ApiError(404,{'code':'disposition_task_ineligible'})
                return response['items'][0]
            bind_remote(control,kind,('name',),('name',),page_loader=load,selected_loader=hydrate,min_query_length=2,active=alive)
        controls['roles'].options={task['destination_role_id']:task['role_queue']};controls['roles'].value=task['destination_role_id'];controls['roles'].update()
        def changed():
            controls['users'].set_visibility(mode.value=='reassign_person');controls['roles'].set_visibility(mode.value=='reassign_queue')
        mode.on_value_change(changed);changed()
        reason=ui.textarea(text('reason')).props('outlined autogrow').classes('w-full')
        feedback=ui.label('').props('role=alert').classes('text-negative');retry={}
        async def save():
            if not alive():return
            target=controls['users'].value if mode.value=='reassign_person' else controls['roles'].value
            if not target or not str(reason.value or '').strip():
                feedback.text=text('required');ui.notify(feedback.text,type='warning');return
            payload={'acting_role_id':role.value,'assigned_user_id':target if mode.value=='reassign_person' else None,'destination_role_id':task['destination_role_id'] if mode.value=='reassign_person' else target}
            signature=json.dumps([payload,reason.value],sort_keys=True);payload['command_id']=retry.setdefault(signature,str(uuid4()));button.disable()
            try:result=await api.disposition_command(f"tasks/{task['id']}/reassignment",payload,version=task['version'],reason=reason.value.strip())
            except ApiError as error:
                if alive():feedback.text=failure(error,on_error);ui.notify(feedback.text,type='negative');button.enable()
                return
            if not alive():return
            dialog.close();ui.notify(text('saved'),type='positive');await after(result)
        with ui.row().classes('w-full justify-end gap-2'):
            ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps');button=ui.button(text('reassign'),on_click=save).props('no-caps')
    dialog.open()
