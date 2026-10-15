"""Four fixed template controls and bounded, live organization-wide history."""
import hashlib
from html import escape
import shutil
import tempfile
from uuid import uuid4

from nicegui import ui
from ..api_client import ApiError
from ..resource_relationships import PageTable
from .messages import text


async def upload_dialog(*,api,job,row,roles,active,on_error,after):
    from .screens import failure
    with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[680px] max-w-full gap-4'):
        def alive():return active() and dialog.value and not dialog._deleted
        ui.label(text('upload_template')).classes('text-xl font-semibold')
        ui.label(text(row['document_type'])).classes('font-semibold')
        ui.label(text('template_scope')).classes('text-sm')
        state={'file':None,'name':None,'checksum':None,'signature':None,'command_id':None,'busy':False}
        feedback=ui.label('').props('role=alert').classes('text-negative')
        def uploaded(event):
            if not alive() or state['busy']:return
            if state['file']:state['file'].close()
            state['file']=None
            if len(event.contents)!=1:feedback.text=text('required');return
            target=tempfile.SpooledTemporaryFile(max_size=8*1024*1024)
            shutil.copyfileobj(event.contents[0],target,length=1024*1024);target.seek(0)
            digest=hashlib.sha256()
            while chunk:=target.read(1024*1024):digest.update(chunk)
            target.seek(0);state.update(file=target,name=event.names[0],checksum=digest.hexdigest());feedback.text=''
        uploader=ui.upload(label=text('template_file'),multiple=False,auto_upload=True,max_files=1,on_multi_upload=uploaded).props('flat bordered accept=.docx').classes('w-full')
        role=ui.select({r['id']:r['name'] for r in roles},label=text('role'),value=roles[0]['id'] if roles else None).props('outlined dense').classes('w-full')
        reason=ui.textarea(text('reason')).props('outlined autogrow').classes('w-full')
        async def save():
            if not alive() or state['busy']:return
            if not state['file'] or not role.value or not str(reason.value or '').strip():
                feedback.text=text('required');ui.notify(feedback.text,type='warning');reason.run_method('focus');return
            signature=(state['checksum'],state['name'],role.value,str(reason.value).strip(),row['reference'])
            if signature!=state['signature']:state.update(signature=signature,command_id=str(uuid4()))
            state['busy']=True;state['file'].seek(0)
            for control in (button,uploader,role,reason):control.disable()
            try:
                result=await api.revise_disposition_template(job['id'],row['document_type'],command_id=state['command_id'],
                  acting_role_id=role.value,expected_reference=row['reference'],reason=str(reason.value).strip(),
                  name=state['name'],content=state['file'])
            except ApiError as error:
                if alive():feedback.text=failure(error,on_error);ui.notify(feedback.text,type='negative')
                return
            finally:
                state['busy']=False
                if alive():
                    for control in (button,uploader,role,reason):control.enable()
                else:cleanup()
            if not alive():return
            dialog.close();ui.notify(text('saved'),type='positive');await after(result)
        with ui.row().classes('w-full justify-end gap-2'):
            ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
            button=ui.button(text('save'),icon='save',on_click=save).props('no-caps')
        def cleanup():
            if not state['busy'] and state['file']:state['file'].close();state['file']=None
            if not state['busy'] and not dialog._deleted:dialog.delete()
        dialog.on('hide',cleanup)
    dialog.open();return dialog


async def download(*,api,job,row,active,on_error):
    from .screens import failure
    try:
        content=await api.request('GET',f"/api/v1/disposition/jobs/{job['id']}/templates/{row['document_type']}/content",
          params={'reference':row['reference']},_cancellable_read=True)
    except ApiError as error:
        if active():ui.notify(failure(error,on_error),type='negative')
        return
    if active():ui.download(content,row['original_filename'],media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')


async def history_dialog(*,api,job,kind,active,on_error,format_timestamp,column):
    # Live inspection found QDialog's 560px default cap overrode the card's
    # width class. Native full-width removes that cap without CSS overrides.
    with ui.dialog().props('full-width') as dialog,ui.card().classes('messaging-workspace w-full gap-4'):
        def alive():return active() and dialog.value and not dialog._deleted
        ui.label(text('template_history')).classes('text-xl font-semibold');ui.label(text(kind))
        async def fetch(p):
            result=await api.disposition_page(f"jobs/{job['id']}/templates/{kind}/revisions",limit=p.size,offset=(p.page-1)*p.size,
              sort=p.sort or 'revision_number',descending=p.descending if p.sort else True)
            for row in result['items']:
                row['uploaded_at_label']=format_timestamp(row['uploaded_at']) if row['uploaded_at'] else text('repository_default')
                row['uploader_label']=row.get('uploader') or '—';row['acting_role_label']=row.get('acting_role') or '—'
                row['id']=row['reference']
            return result
        table=PageTable(columns=[column('revision_number','version',True),column('original_filename','document',True),
          column('uploaded_at','occurred',True),column('uploader_label','actor'),column('acting_role_label','role'),
          column('checksum','template_checksum'),column('actions')],fetch=fetch,active=alive,on_error=on_error,empty='empty',
          wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
        table.table.add_slot('body-cell-uploaded_at','<q-td :props="props">{{props.row.uploaded_at_label}}</q-td>')
        # wrap-cells wraps words; checksums contain no spaces. The standard
        # utility lets this single data value wrap instead of widening columns.
        table.table.add_slot('body-cell-checksum','<q-td :props="props"><span class="break-all">{{props.row.checksum}}</span></q-td>')
        table.table.add_slot('body-cell-actions','''<q-td :props="props"><q-btn flat dense icon="download" aria-label="'''+escape(text('download_template'))+'''" @click="$parent.$emit('download',props.row.id)"><q-tooltip>'''+escape(text('download_template'))+'''</q-tooltip></q-btn></q-td>''')
        async def selected(event):
            row=next((r for r in table.table.rows if r['reference']==event.args),None)
            if row and alive():await download(api=api,job=job,row=row,active=alive,on_error=on_error)
        table.table.on('download',selected)
        ui.button(text('close'),on_click=dialog.close).props('flat no-caps').classes('self-end')
        dialog.on('hide',lambda:dialog.delete() if not dialog._deleted else None)
    dialog.open();await table.load();return dialog


def templates_panel(*,api,job,context,active,on_error,format_timestamp,column,after=None):
    from .screens import failure
    # No request for users whose already-loaded role context cannot use these
    # controls. The API independently rechecks effective roles on every read.
    if not any(r.get('profile_code') in ('INFO_GOV_OFFICER','INFO_GOV_MGR') for r in context['roles']) or job['job_type']!='destruction':
        async def unused():pass
        return unused
    ui.separator();ui.label(text('templates')).classes('text-lg font-semibold')
    ui.label(text('template_scope')).classes('text-sm')
    host=ui.column().classes('w-full gap-3');revision=[0]
    async def load():
        revision[0]+=1;token=revision[0]
        def alive():return active() and not host._deleted and token==revision[0]
        try:result=await api.disposition_page(f"jobs/{job['id']}/templates")
        except ApiError as error:
            if alive():
                host.clear()
                with host:
                    ui.label(failure(error,on_error)).props('role=alert').classes('text-negative')
                    ui.button(text('refresh'),icon='refresh',on_click=load).props('flat no-caps')
            return
        if not alive():return
        host.clear()
        with host:
            for row in result['items']:
                with ui.card().classes('w-full gap-2 p-4'):
                    ui.label(text(row['document_type'])).classes('font-semibold')
                    ui.label(row['original_filename']).classes('text-sm break-all').props('dir=ltr')
                    ui.label(text('repository_default') if row['revision_number']==0 else text('version')+' '+str(row['revision_number'])).classes('text-sm')
                    with ui.row().classes('w-full gap-2 flex-wrap'):
                        ui.button(text('download_template'),icon='download',on_click=lambda row=row:download(api=api,job=job,row=row,active=alive,on_error=on_error)).props('flat no-caps')
                        ui.button(text('template_history'),icon='history',on_click=lambda row=row:history_dialog(api=api,job=job,kind=row['document_type'],active=alive,on_error=on_error,format_timestamp=format_timestamp,column=column)).props('flat no-caps')
                        async def saved(result):
                            if after:await after(result)
                            else:await load()
                        ui.button(text('upload_template'),icon='upload_file',on_click=lambda row=row:upload_dialog(api=api,job=job,row=row,roles=result['roles'],active=alive,on_error=on_error,after=saved)).props('outline no-caps')
    return load
