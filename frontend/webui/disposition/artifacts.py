"""Job document panel: standard table/viewer/upload controls and live destinations."""
import asyncio
import hashlib
from html import escape
import shutil
import tempfile
from uuid import uuid4

from nicegui import ui
from ..api_client import ApiError
from ..resource_relationships import PageTable
from .messages import text


def destination_label(value):
    if not value:return text('restricted')
    return ' · '.join(str(value[k]) for k in ('scheme_code','classification_code','aggregation_number','title'))


def show_destination(value, category):
    with ui.column().classes('w-full gap-1'):
        ui.label(text(category)).classes('font-semibold')
        if value['warning']:
            ui.label(text(value['warning'])).classes('text-amber-900').props('role=alert')
        else:ui.label(destination_label(value['destination'])).props('dir=auto')
        if value['changed']:
            ui.label(text('destination_changed_warning')).classes('text-amber-900').props('role=alert')
            ui.label(text('previous_destination')+': '+destination_label(value['previous_destination'])).props('dir=auto')


async def correction_dialog(*, api, job, row, roles, active, on_error, after):
    from .screens import failure
    with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[680px] max-w-full gap-4'):
        def alive():return active() and dialog.value and not dialog._deleted
        ui.label(text('correct_evidence')).classes('text-xl font-semibold')
        ui.label(text('correction_preserves')).classes('text-sm')
        ui.label(row['file_name']).props('dir=auto')
        destination_host=ui.column().classes('w-full')
        state={'file':None,'name':None,'mime':None,'digest':None,'destination':None,'signature':None,'command_id':None,'busy':False}
        feedback=ui.label('').props('role=alert').classes('text-negative')
        async def load_destination():
            try:value=await api.disposition_page(f"jobs/{job['id']}/artifact-destination",document_type=row['document_type'])
            except ApiError as error:
                if alive():feedback.text=failure(error,on_error)
                return
            if not alive():return
            state['destination']=value;destination_host.clear()
            with destination_host:show_destination(value,'evidence_destination')
            button.set_enabled(value['ready'])
        refresh=ui.button(text('refresh_destination'),icon='refresh',on_click=load_destination).props('flat no-caps')
        def uploaded(event):
            if not alive() or state['busy']:return
            if state['file']:state['file'].close()
            state['file']=None
            if len(event.contents)!=1:
                feedback.text=text('required');return
            target=tempfile.SpooledTemporaryFile(max_size=8*1024*1024)
            shutil.copyfileobj(event.contents[0],target,length=1024*1024);target.seek(0)
            digest=hashlib.sha256()
            while chunk:=target.read(1024*1024):digest.update(chunk)
            target.seek(0)
            state.update(file=target,name=event.names[0],mime=event.types[0] or 'application/octet-stream',digest=digest.hexdigest())
            feedback.text=''
        uploader=ui.upload(label=text('corrected_file'),multiple=False,auto_upload=True,max_files=1,on_multi_upload=uploaded).props('flat bordered').classes('w-full')
        role=ui.select({r['id']:r['name'] for r in roles},label=text('role'),value=roles[0]['id'] if roles else None).props('outlined dense').classes('w-full')
        reason=ui.textarea(text('reason')).props('outlined autogrow').classes('w-full')
        async def save():
            if not alive() or state['busy']:return
            dest=state['destination']
            if not state['file'] or not role.value or not str(reason.value or '').strip() or not dest or not dest['ready']:
                feedback.text=text('required');ui.notify(feedback.text,type='warning');reason.run_method('focus');return
            signature=(state['digest'],state['name'],state['mime'],dest['token'],role.value,str(reason.value).strip())
            if signature!=state['signature']:state.update(signature=signature,command_id=str(uuid4()))
            button.disable();state['file'].seek(0);state['busy']=True
            for control in (uploader,role,reason,refresh):control.disable()
            try:
                result=await api.correct_disposition_evidence(job['id'],row['id'],version=job['version'],command_id=state['command_id'],acting_role_id=role.value,
                  destination_token=dest['token'],reason=str(reason.value).strip(),name=state['name'],content=state['file'],mime_type=state['mime'])
            except ApiError as error:
                if alive():feedback.text=failure(error,on_error);ui.notify(feedback.text,type='negative');button.enable()
                return
            finally:
                state['busy']=False
                if alive():
                    for control in (uploader,role,reason,refresh):control.enable()
                else:cleanup()
            if not alive():return
            dialog.close();ui.notify(text('saved'),type='positive');await after(result)
        with ui.row().classes('w-full justify-end gap-2'):
            ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
            button=ui.button(text('save'),icon='save',on_click=save).props('no-caps');button.disable()
        def cleanup():
            if not state['busy'] and state['file']:state['file'].close();state['file']=None
        dialog.on('hide',cleanup)
    dialog.open()
    await load_destination()
    return dialog


def documents_panel(*, api, job, active, on_error, after, open_resource, preview, format_timestamp, column):
    from .screens import failure
    ui.separator();ui.label(text('documents')).classes('text-lg font-semibold')
    warnings=ui.column().classes('w-full gap-3')
    roles=[]
    async def fetch(p):
        result=await api.disposition_page(f"jobs/{job['id']}/documents",limit=p.size,offset=(p.page-1)*p.size,sort=p.sort or 'id',descending=p.descending if p.sort else True)
        if not active():return result
        for row in result['items']:
            row['type_label']=text(row['document_type']);row['current_label']=text('current_version' if row['is_current'] else 'earlier_version')
            row['created_label']=format_timestamp(row['date_created'])
        return result
    table=PageTable(columns=[column('file_name','document',True),column('type_label','document_type',True),column('evidence_version','version',True),column('current_label','evidence_version_state'),column('created_label','occurred',True),column('actions')],
      fetch=fetch,active=active,on_error=on_error,empty='empty',on_loaded=lambda p,result:roles.__setitem__(slice(None),result['correction_roles']),wrap_cells=True,empty_text=lambda:text('no_documents'),loading_text=lambda:text('loading'))
    table.table.add_slot('body-cell-actions','''<q-td :props="props"><div class="row no-wrap gap-1">
     <q-btn v-if="props.row.can_preview" flat dense icon="visibility" aria-label="'''+escape(text('preview_document'))+'''" @click="$parent.$emit('preview',props.row.id)"><q-tooltip>'''+escape(text('preview_document'))+'''</q-tooltip></q-btn>
     <q-btn v-if="props.row.can_download" flat dense icon="download" aria-label="'''+escape(text('download_document'))+'''" @click="$parent.$emit('download',props.row.id)"><q-tooltip>'''+escape(text('download_document'))+'''</q-tooltip></q-btn>
     <q-btn flat dense icon="open_in_new" aria-label="'''+escape(text('open'))+'''" @click="$parent.$emit('open-record',props.row.id)"><q-tooltip>'''+escape(text('open'))+'''</q-tooltip></q-btn>
     <q-btn v-if="props.row.can_correct" flat dense icon="upload_file" aria-label="'''+escape(text('correct_evidence'))+'''" @click="$parent.$emit('correct',props.row.id)"><q-tooltip>'''+escape(text('correct_evidence'))+'''</q-tooltip></q-btn>
     </div></q-td>''')
    def selected(event):return next((r for r in table.table.rows if r['id']==event.args),None) if active() else None
    async def open_record(event):
        row=selected(event)
        if row:await open_resource('record',row['record_id'])
    async def view(event):
        row=selected(event)
        if row and row['can_preview'] and preview:await preview({'id':row['record_id'],'title':row['file_name']},row['digital_component_id'])
    async def download(event):
        row=selected(event)
        if not row or not row['can_download']:return
        try:content=await api.request('GET',f"/api/v1/disposition/jobs/{job['id']}/documents/{row['id']}/content",_cancellable_read=True)
        except ApiError as error:
            if active():ui.notify(failure(error,on_error),type='negative')
            return
        if active():ui.download(content,row['file_name'])
    async def correct(event):
        row=selected(event)
        if row and row['can_correct']:await correction_dialog(api=api,job=job,row=row,roles=roles,active=active,on_error=on_error,after=after)
    for name,handler in [('open-record',open_record),('preview',view),('download',download),('correct',correct)]:table.table.on(name,handler)
    async def load_warnings():
        try:
            values=await asyncio.gather(*(api.disposition_page(f"jobs/{job['id']}/artifact-destination",document_type=kind) for kind in ('external_approval_letter','destruction_request')))
        except ApiError as error:
            if active():
                with warnings:ui.label(failure(error,on_error)).props('role=alert')
            return
        if not active():return
        warnings.clear()
        with warnings:
            for value,category in zip(values,('evidence_destination','reports_destination')):show_destination(value,category)
    async def load():await asyncio.gather(table.load(),load_warnings())
    return load
