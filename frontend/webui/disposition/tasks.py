"""Current-user task inbox: server pages, shared Wathiq table, no result cache."""
from html import escape
from nicegui import ui
from ..resource_relationships import PageTable
from .messages import text,KEYS,action_required_label
from .screens import column,restore_page


async def tasks_screen(*,api,container,active,on_error,open_task,format_timestamp,saved=None,remember=lambda value:None,filters_expanded=False,remember_filters=lambda value:None,**unused):
    saved=dict(saved or {})
    if saved.get('sort')=='priority':saved.update(sort='',descending=False)
    with container,ui.card().classes('detail-surface messaging-workspace w-full p-5 gap-4') as host:
        def alive():return active() and not host._deleted
        def disclosure_changed(event):
            if alive():
                remember_filters(bool(event.value))
        with ui.expansion(text('filters'), icon='filter_list', value=bool(filters_expanded),
                          on_value_change=disclosure_changed).classes('w-full'):
            with ui.grid().classes('w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-3 items-end gap-3'):
                search=ui.input(text('search'),value=saved.get('query','')).props('outlined dense maxlength=200').classes('w-full')
                state=ui.select({'':text('any'),'open':text('open'),'claimed':text('claimed')},value=saved.get('state',''),label=text('task_state')).props('outlined dense').classes('w-full')
                stage=ui.select({'':text('any'),**{k:text(k) for k in ('officer_preparation','officer_correction','manager_preparation','manager_correction','file_administrator_review','unit_manager_review','records_manager_review','external_approval_pending','physical_destruction','digital_destruction','certificate_generation')}},label=text('stage'),value=saved.get('stage','')).props('outlined dense').classes('w-full')
                kind=ui.select({'':text('any'),**{k:text(k) for k in ('preparation','correction','file_administrator_review','unit_manager_review','records_manager_review')}},label=text('task_type'),value=saved.get('task_type','')).props('outlined dense').classes('w-full')
                indicator=ui.select({'':text('any'),**{k:action_required_label(k) for k in ('blocked','removal_required','failed_reports','destruction_failed','certificate_failed')}},label=text('action_required'),value=saved.get('indicator','')).props('outlined dense').classes('w-full')
                priority=ui.number(text('min_priority'),value=saved.get('min_priority'),step=1,precision=0).props('outlined dense').classes('w-full')
                roots=ui.number(text('min_roots'),value=saved.get('min_roots'),min=0,step=1,precision=0).props('outlined dense').classes('w-full')
                claimant=ui.select({'':text('any'),'yes':text('yes'),'no':text('no')},label=text('has_claimant'),value=saved.get('has_claimant','')).props('outlined dense').classes('w-full')
                ui.button(text('refresh'),icon='refresh',on_click=lambda:page.load(reset=True)).tooltip(text('refresh')).props('outline no-caps')
        async def fetch(p):
            view=dict(page=p.page,size=p.size,sort=p.sort,descending=p.descending,query=search.value,state=state.value,stage=stage.value,task_type=kind.value,indicator=indicator.value,min_priority=priority.value,min_roots=roots.value,has_claimant=claimant.value)
            result=await api.disposition_page('tasks',limit=p.size,offset=(p.page-1)*p.size,sort={'action_label':'task_type','stage_label':'workflow_stage','received_label':'received','state_label':'state','type_label':'job_type','age_days':'age','digital_label':'digital_state'}.get(p.sort,p.sort) or 'received',descending=p.descending,query=search.value,state=state.value or None,stage=stage.value or None,task_type=kind.value or None,indicator=indicator.value or None,min_priority=int(priority.value) if priority.value is not None else None,min_roots=int(roots.value) if roots.value is not None else None,has_claimant={'yes':True,'no':False}.get(claimant.value))
            for row in result['items']:
                row['action_label']=text('retry_certificate') if row.get('certificate_failed') else text('certificate_final_task') if row['task_type']=='certificate_download' else text(row['task_type']) if row['task_type'] in KEYS else text(row['workflow_stage'])
                row['stage_label']=text(row['workflow_stage']);row['type_label']=text(row['job_type'])
                row['received_label']=format_timestamp(row['date_created']);row['age_days']=max(0,int(row['age_seconds'])//86400)
                row['state_label']=text(row['task_state'])
                row['digital_label']=(text('execution_'+row['digital_state'])+' · '+str(row['digital_completed'])+'/'+str(row['digital_total'])) if row.get('digital_state') else '—'
            result['_view']=view
            return result
        def task_column(*args, **kwargs):
            return {**column(*args, **kwargs), 'headerStyle': 'vertical-align: top'}
        page=PageTable(columns=[task_column('action_label','task_type',True),task_column('job_number',sortable=True),task_column('type_label','job_type',True),task_column('owner',sortable=True),task_column('stage_label','stage',True),task_column('direct_assignee',sortable=True),task_column('role_queue',sortable=True),task_column('claimant',sortable=True),task_column('received_label','received',True),task_column('age_days','age',True),task_column('root_count',sortable=True),task_column('state_label','task_state',True),task_column('digital_label','execution_progress',True),task_column('actions')],fetch=fetch,active=alive,on_error=on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'),initial=saved,on_loaded=lambda p,r:remember(r['_view']))
        restore_page(page,saved)
        page.table.add_slot('body-cell-actions','''<q-td :props="props"><q-btn flat dense icon="open_in_new" aria-label="'''+escape(text('open'))+'''" @click="$parent.$emit('open-task',props.row.id)"><q-tooltip>'''+escape(text('open'))+'''</q-tooltip></q-btn></q-td>''')
        async def opened(event):
            row=next((r for r in page.table.rows if r['id']==event.args),None)
            if row:await open_task(row['job_id'],row['id'])
        page.table.on('open-task',opened)
        search.on('keydown.enter',lambda:page.load(reset=True));state.on_value_change(lambda:page.load(reset=True));stage.on_value_change(lambda:page.load(reset=True))
        for control in (kind,indicator,claimant):control.on_value_change(lambda:page.load(reset=True))
        for control in (priority,roots):control.on('keydown.enter',lambda:page.load(reset=True))
        await page.load()
