"""Job-scoped admission picker; bounded server pages, no operational cache.

Selection belongs to this mounted dialog/identity/language only. Filters and
refresh clear it; paging retains exact selected versions. Closing discards it.
An uncertain mutation retains its exact command UUID/payload for safe retry.
"""
from uuid import uuid4
from nicegui import ui
from ..api_client import ApiError
from ..locale_services import current_locale_context
from ..resource_relationships import PageTable
from .acting_role import automatic_role
from .bulk import BulkSelection
from .messages import text, status_label


async def add_aggregations_dialog(*,api,job,context,active,on_error,format_timestamp,after):
    from .screens import addition_feedback,column,date_filter,failure,wall_filter
    if not active():return
    state={'busy':False,'pending':None,'refresh':False,'changed':False,'scope':dict(job),
           'criteria':{'query':'','due_from':None,'due_to':None}}
    # Inline card width overrides the observed 560px QDialog default without
    # full-width's viewport-wide expansion. Native flex/overflow lets the body
    # fit its contents, shrinking only at the responsive maximum height.
    with ui.dialog().props('persistent') as dialog, ui.card().classes(
            'messaging-workspace !max-h-[calc(100vh-48px)] sm:!max-h-[75vh] gap-3 flex-nowrap').style(
            'width:1100px;max-width:calc(100vw - 48px)').props(
            'dir='+('rtl' if current_locale_context()[0]=='ar' else 'ltr')):
        def alive():return active() and dialog.value and not dialog._deleted
        ui.label(text('picker_title',job=job['job_number'])).classes('text-xl font-semibold').props('dir=auto')
        scope_label=ui.label(text('picker_owner_scope',type=text(job['job_type']),owner=job.get('owner') or '—')
            if job['job_type']=='destruction' else text('picker_type_scope',type=text(job['job_type']))).classes('font-semibold').props('dir=auto')
        ui.label(text('picker_hint')).classes('text-sm text-slate-600')
        ui.label(text('picker_relationship_hint')).classes('text-sm text-slate-600')
        content=ui.column().classes('w-full min-h-0 overflow-y-auto flex-nowrap gap-3')
        with content, ui.column().classes('w-full min-w-0 gap-3 shrink-0'):
            with ui.row().classes('w-full gap-3 items-start'):
                query=ui.input(text('picker_search')).props('outlined dense maxlength=200').classes('grow min-w-0')
                query.on('keydown.enter',lambda:load(reset=True))
                ui.button(text('filters'),icon='filter_alt',on_click=lambda:load(reset=True)).props('outline no-caps').tooltip(text('filters'))
                ui.button(text('refresh'),icon='refresh',on_click=lambda:load()).props('outline no-caps').tooltip(text('refresh'))
            with ui.expansion(text('filters'),icon='filter_alt').classes('w-full'):
                with ui.grid(columns=2).classes('w-full gap-3 grid-cols-1 md:grid-cols-2'):
                    due_from,from_fold=wall_filter('due_from',{})
                    due_to,to_fold=wall_filter('due_to',{})
                ui.button(text('filters'),icon='filter_alt',on_click=lambda:load(reset=True)).props('outline no-caps').tooltip(text('filters'))
            selection=BulkSelection(eligible=lambda row:row.get('selectable',False),label=lambda row:row['identity'],
                                    active=alive,actions=[],on_change=lambda:validity())

            async def fetch(p):
                result=await api.disposition_page('eligibility',job_id=job['id'],**state['criteria'],
                    limit=p.size,offset=(p.page-1)*p.size,
                    sort={'identity':'id','owner_label':'owner','due_label':'due','status_label':'status'}.get(p.sort,p.sort) or 'due',descending=p.descending)
                for row in result['items']:
                    row['identity']=row['aggregation_number']+' · '+row['title']
                    row['owner_label']=row.get('owner') or '—'
                    row['due_label']=format_timestamp(row['calculated_disposition_at']) if row.get('calculated_disposition_at') else text('no_date')
                    row['status_label']=status_label(row['disposition_status'])
                    row['relationship_label']=text('picker_relationship_warning') if row.get('relationships_block_final') else '—'
                return result

            def loaded(p,result):
                state['scope']=result['scope']
                scope=state['scope']
                scope_label.text=(text('picker_owner_scope',type=text(scope['job_type']),owner=scope.get('owner') or '—')
                                  if scope['job_type']=='destruction' else text('picker_type_scope',type=text(scope['job_type'])))
                selection.loaded(p,result)
                validity()

            page=PageTable(columns=[column('identity','aggregation',True),column('owner_label','owner',True),
                column('status_label','status',True),column('due_label','normal_due',True),column('relationship_label','picker_relationships')],
                fetch=fetch,active=alive,on_error=lambda error:failure(error,on_error),empty='empty',
                empty_text=lambda:text('picker_empty'),loading_text=lambda:text('loading'),
                wrap_cells=True,selection='multiple',on_loaded=loaded)
            selection.attach(page)
            page.table.add_slot('body-cell-relationship_label','''<q-td :props="props"><span :class="props.row.relationships_block_final ? 'text-amber-900' : ''">{{ props.row.relationship_label }}</span></q-td>''')
            for field in ('identity','owner_label'):
                page.table.add_slot('body-cell-'+field,'<q-td :props="props"><span dir="auto">{{ props.row.'+field+' }}</span></q-td>')
        feedback=ui.label('').classes('text-negative whitespace-pre-wrap').props('role=alert')
        results=ui.column().classes('w-full gap-2')
        results.set_visibility(False)

        async def close():
            if state['busy']:return
            dialog.close()
            if state['changed'] and active():await after()

        async def load(reset=False):
            if not alive() or state['busy'] or state['pending']:return
            if reset:
                try:
                    criteria={'query':query.value or '',
                        'due_from':date_filter(due_from.value,from_fold.value),
                        'due_to':date_filter(due_to.value,to_fold.value)}
                except ApiError as error:
                    feedback.text=failure(error,on_error);return
                state['criteria']=criteria
            selection.clear();state['refresh']=False;feedback.text=''
            await page.load(reset=reset)
            validity()

        async def add():
            if not alive() or state['busy']:return
            if state['refresh']:
                await load()
                return
            if state['pending'] is None:
                rows=selection.selected()
                if not rows:return
                scope=state['scope']
                roles=[{'id':scope['membership_add_role_id']}] if scope.get('membership_add_role_id') else context['roles']
                role=automatic_role(roles)
                if not role:
                    feedback.text=text('required_fields');return
                state['pending']={'payload':{'items':[{'root_id':r['id'],'expected_version':r['version']} for r in rows],
                    'acting_role_id':role,'command_id':str(uuid4())},'version':scope['version'],
                    'labels':{r['id']:r['identity'] for r in rows}}
            pending=state['pending'];state['busy']=True;feedback.text='';validity()
            try:
                result=await api.disposition_command(f"jobs/{job['id']}/memberships",pending['payload'],reason='',version=pending['version'])
            except ApiError as error:
                if alive():
                    definitive=error.status_code in (403,404,409,422)
                    feedback.text=(text('picker_changed') if definitive else text('bulk_uncertain'))+'\n'+failure(error,on_error)
                    state['refresh']=definitive
                    if definitive:state['pending']=None
                    else:state['changed']=True  # Closing must reread a potentially committed result.
                return
            finally:
                state['busy']=False
                if alive():validity()
            if not alive():return
            state['pending']=None;selection.clear()
            successful=any(item.get('success') for item in result['items'])
            state['changed']|=successful
            addition_feedback(container=results,active=alive,result=result,labels=pending['labels'],job_number=job['job_number'])
            if all(item.get('success') for item in result['items']):
                await close()
            else:
                # Keep the per-item failure summary visible and fetch a fresh
                # candidate page. Never silently reselect a stale/hidden root.
                await load()

        def validity():
            if dialog._deleted:return
            frozen=state['busy'] or state['pending'] is not None
            content.props('inert' if frozen else '',remove='' if frozen else 'inert')
            cancel.set_enabled(not state['busy'])
            count=len(state['pending']['payload']['items']) if state['pending'] else len(selection.rows)
            button.text=text('bulk_refresh_selection') if state['refresh'] else text('picker_retry') if state['pending'] else text('picker_add',count=count)
            button.set_enabled(not state['busy'] and bool(state['refresh'] or state['pending'] or count))
            cancel.text=text('close') if state['changed'] else text('cancel')

        with ui.row().classes('w-full justify-end gap-2 shrink-0'):
            cancel=ui.button(text('cancel'),on_click=close).props('flat no-caps')
            button=ui.button(text('picker_add',count=0),icon='playlist_add',on_click=add).props('no-caps').tooltip(text('add_aggregations'))
            button.disable()
    dialog.open()
    await page.load()
    return dialog
