"""Current-server-state screens; page-local state, no result cache or access grants."""
import asyncio
from datetime import datetime
from html import escape
from uuid import uuid4
from nicegui import ui
from ..api_client import ApiError
from ..locale_services import current_locale_context, working_datetime_to_utc, LocalizedTimezoneError, format_local_date, utc_instant_to_working
from ..remote_select import RemoteSelect
from ..relationship_select import relationship_select
from ..resource_relationships import PageTable
from .acting_role import automatic_role
from .messages import text, status_label, KEYS

TYPES=('destruction','permanent_transfer','selective_transfer','local_archives')
ACTIONS={'destruction':'destruction','transfer_to_external_archive':'permanent_transfer',
         'selective_preservation':'selective_transfer','retain_as_local_archives':'local_archives'}


def failure(error, on_error):
    code=error.detail.get('code') if isinstance(error.detail,dict) else None
    return text(code) if code in KEYS else on_error(error)


def column(name, label=None, sortable=False):
    return {'name':name,'field':name,'label':text(label or name),'sortable':sortable,
            'align':'right' if current_locale_context()[0]=='ar' else 'left'}


def selector(*, api, bind_remote, kind, label, active, job_type=lambda:'destruction', selected=None, job_id=None):
    with ui.column().classes('w-full min-w-0 gap-1'):
        control=(relationship_select(text(label),{},remote=True,icon='corporate_fare') if kind=='owners' else
                 RemoteSelect({},label=text(label),value=None,with_input=True).props('outlined dense clearable').classes('w-full'))
        async def load(query):
            return await api.disposition_page('selectors/'+kind,query=query,job_type=job_type(),**({'job_id':job_id} if job_id is not None else {}))
        async def hydrate(identity):
            response=await api.disposition_page('selectors/'+kind,selected=identity,job_type=job_type(),**({'job_id':job_id} if job_id is not None else {}))
            if not response['items']:raise ApiError(404,{'code':'disposition_resource_access_required'})
            return response['items'][0]
        if selected:
            control.options={selected['id']:' · '.join(str(selected[k]) for k in (('code','name') if kind=='owners' else ('name',)) if selected.get(k))};control.value=selected['id'];control.update()
        bind_remote(control,'users' if kind=='assignees' else 'org-units',(('code','name') if kind=='owners' else ('name',)),(('code','name') if kind=='owners' else ('name',)),
                    page_loader=load,selected_loader=hydrate,min_query_length=2,active=active)
        ui.label(text('selector_hint')).classes('text-xs text-slate-500')
    return control


def date_filter(value, ambiguity=None):
    """Resolve wall-clock filter input in the user's working IANA timezone."""
    if not value:return None
    try:
        return working_datetime_to_utc(datetime.fromisoformat(value),current_locale_context()[1],ambiguity).isoformat().replace('+00:00','Z')
    except LocalizedTimezoneError as error:
        raise ApiError(422,{'message_key':error.message_key,'parameters':error.parameters}) from None
    except ValueError:
        raise ApiError(422,{'message_key':'common.error.bad_request','parameters':{}}) from None


def wall_filter(name, saved):
    with ui.column().classes('w-full min-w-0 gap-1'):
        control=ui.input(text(name),value=saved.get(name,'')).props('outlined dense type=datetime-local stack-label')
        fold=ui.select({key:text(key) for key in ('earlier','later')},label=text('overlap'),value=saved.get(name+'_fold')).props('outlined dense clearable').classes('w-full')
        def show_choice():
            ambiguous=False
            try:date_filter(control.value)
            except ApiError as error:ambiguous=error.detail.get('message_key')=='timezone.validation.wall_time.ambiguous'
            fold.set_visibility(ambiguous)
        control.on_value_change(show_choice);show_choice()
    return control,fold


async def command_dialog(*, api, context, active, on_error, title, build, path, version=None,
                         after, confirm=None, reason_required=True):
    """A retry retains its UUID for the exact payload/reason, including failures."""
    if not active(): return
    with ui.dialog() as dialog, ui.card().classes('messaging-workspace w-[600px] max-w-full gap-4'):
        ui.label(text(title)).classes('text-xl font-semibold')
        def alive():return active() and dialog.value and not dialog._deleted
        if confirm:ui.label(text(confirm)).classes('text-sm')
        collect=build(alive)
        role_id=automatic_role(context['roles'])
        reason=ui.textarea(label=text('reason')).props('outlined autogrow').classes('w-full') if reason_required else None
        feedback=ui.label('').classes('text-negative').props('role=alert')
        retry={'signature':None,'id':None}
        async def save():
            if not alive():return
            values=collect()
            reason_value=str(reason.value or '').strip() if reason else ''
            if values is None or (reason_required and not reason_value) or not role_id:
                feedback.text=text('required');ui.notify(text('required'),type='warning')
                if reason:reason.run_method('focus')
                return
            payload={**values,'acting_role_id':role_id}
            signature=repr((payload,reason_value))
            if signature!=retry['signature']:retry.update(signature=signature,id=str(uuid4()))
            payload['command_id']=retry['id'];button.disable();feedback.text=''
            try:
                result=await api.disposition_command(path,payload,reason=reason_value,version=version)
            except ApiError as error:
                if alive():feedback.text=failure(error,on_error);ui.notify(feedback.text,type='negative');button.enable()
                return
            if not alive():return
            dialog.close()
            if isinstance(result.get('items'),list):
                successes=sum(bool(item.get('success')) for item in result['items'])
                ui.notify(text('saved' if successes==len(result['items']) else 'partial_add' if successes else 'no_add'),type='positive' if successes==len(result['items']) else 'warning')
            else:ui.notify(text('saved'),type='positive')
            await after(result)
        with ui.row().classes('w-full justify-end gap-2'):
            ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
            button=ui.button(text('save'),icon='save',on_click=save).tooltip(text('save')).props('no-caps')
    dialog.open()


async def create_dialog(*, api, context, bind_remote, active, on_error, after, owner_suggestion=None):
    def build(alive):
        kind=ui.select({k:text(k) for k in TYPES},value=TYPES[0],label=text('job_type')).props('outlined dense').classes('w-full')
        with ui.column().classes('w-full gap-0') as owner_section:
            owner=selector(api=api,bind_remote=bind_remote,kind='owners',label='owner',active=alive,selected=(owner_suggestion or {}).get('owner'))
            if owner_suggestion and owner_suggestion['basis'] in ('common_ancestor','no_common_ancestor'):
                ui.label(text('owner_'+owner_suggestion['basis'])).classes('text-sm text-slate-600').props('role=status')
        def default_assignee():
            profile='INFO_GOV_MGR' if context.get('destruction_review_route')=='records_manager_only' else 'INFO_GOV_OFFICER'
            return context.get('current_user') if kind.value!='destruction' or any(r.get('profile_code')==profile for r in context['roles']) else None
        assigned=selector(api=api,bind_remote=bind_remote,kind='assignees',label='assignee',active=alive,job_type=lambda:kind.value,selected=default_assignee())
        def changed():
            person=default_assignee()
            assigned.set_options({person['id']:person['name']} if person else {},value=person['id'] if person else None)
            owner_section.set_visibility(kind.value=='destruction')
        kind.on_value_change(changed)
        return lambda:({'job_type':kind.value,
                        'owning_org_unit_id':owner.value if kind.value=='destruction' else None,
                        'assigned_user_id':assigned.value} if kind.value!='destruction' or owner.value else None)
    await command_dialog(api=api,context=context,active=active,on_error=on_error,title='create',build=build,path='jobs',after=after,reason_required=False)


async def blockers_dialog(*, api, root, active, on_error, open_resource):
    if not active():return
    with ui.dialog() as dialog, ui.card().classes('messaging-workspace w-[760px] max-w-full gap-3'):
        ui.label(text('blockers')).classes('text-xl font-semibold')
        ui.label(root['aggregation_number']+' · '+root['title']).props('dir=auto')
        feedback=ui.label('').props('role=status').classes('text-sm')
        content=ui.column().classes('w-full gap-3')
        offset=0
        async def load():
            nonlocal offset
            if not active() or not dialog.value:return
            button.disable();feedback.text=text('loading')
            try:result=await api.disposition_page(f"aggregations/{root['id']}/blockers",limit=25,offset=offset)
            except ApiError as error:
                if active() and dialog.value:
                    feedback.text=failure(error,on_error);feedback.classes(add='text-negative');button.text=text('blockers_retry');button.enable();button.set_visibility(True)
                return
            if not active() or not dialog.value:return
            feedback.text='';feedback.classes(remove='text-negative');button.text=text('more')
            with content:
                if offset==0 and result['relationships_block_final']:ui.label(text('final_blocked')).classes('text-amber-900')
                if offset==0 and not result['items'] and not result['relationships_block_final']:ui.label(text('blockers_empty_all')).props('role=status')
                for item in result['items']:
                    with ui.card().classes('w-full p-3 gap-1'):
                        ui.label(text('hidden') if item['redacted'] else item.get('resource_label') or text(item['resource_kind'])+' #'+str(item['resource_id'])).props('dir=auto')
                        ui.label(' · '.join(text(key) for key,flag in [('vital',item['is_vital']),('security',item['security_blocked']),('held',item['legal_hold'])] if flag)).classes('font-semibold text-amber-900')
                        for hold in item['holds']:ui.label(hold['code']+' · '+hold['name']).props('dir=auto')
                        if not item['redacted']:
                            ui.button(text('open'),icon='open_in_new',on_click=lambda i=item:open_resource(i['resource_kind'],i['resource_id'])).tooltip(text('open')).props('flat dense no-caps')
                for relation in result.get('relationships',[]):
                    if not relation['blocks_final']:continue
                    with ui.card().classes('w-full p-3 gap-1'):
                        ui.label(relation.get('relationship_label') or text('history_relationships')).classes('font-semibold')
                        for endpoint,label in [('source','blocker_source'),('target','blocker_target')]:
                            value=relation.get(endpoint)
                            with ui.row().classes('w-full items-baseline gap-1'):
                                ui.label(text(label)+' ·')
                                if value:
                                    ui.label(value['number']).props('dir=ltr')
                                    ui.label('·')
                                    ui.label(value['title']).props('dir=auto')
                                else:ui.label(text('restricted_resource'))
            offset+=max(len(result['items']),len(result.get('relationships',[])))
            button.set_visibility(result['has_more']);button.enable()
        with ui.row().classes('w-full justify-end gap-2'):
            button=ui.button(text('more'),icon='expand_more',on_click=load).tooltip(text('more')).props('flat no-caps')
            ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
    dialog.open();await load()


def restore_page(page, saved):
    page.page=max(1,int(saved.get('page',1)))
    page.size=saved.get('size',25) if saved.get('size',25) in (10,25,50) else 25
    page.sort=saved.get('sort','');page.descending=bool(saved.get('descending',False))
    page.page_size.value=page.size


async def jobs_screen(*, api, container, active, on_error, bind_remote, open_job, saved=None, remember=lambda value:None,
                      filters_expanded=False, remember_filters=lambda value:None):
    saved=saved or {}
    with container, ui.card().classes('detail-surface messaging-workspace w-full p-5 gap-4') as host:
        def alive():return active() and not host._deleted
        context_task=asyncio.create_task(api.disposition_page('context'))
        context={}
        def disclosure_changed(event):
            if alive():remember_filters(bool(event.value))
        with ui.expansion(text('filters'),icon='filter_alt',value=bool(filters_expanded),on_value_change=disclosure_changed).classes('w-full'):
            with ui.grid().classes('w-full gap-3 grid-cols-1 md:grid-cols-2 xl:grid-cols-3'):
                search=ui.input(text('search'),value=saved.get('query','')).props('outlined dense maxlength=200')
                kind=ui.select({'':text('any'),**{v:text(v) for v in TYPES}},value=saved.get('job_type',''),label=text('job_type')).props('outlined dense')
                lifecycle=ui.select({'':text('any'),**{v:text(v) for v in ('active','completed','terminated')}},value=saved.get('lifecycle',''),label=text('lifecycle')).props('outlined dense')
                owner=ui.input(text('owner'),value=saved.get('owner','')).props('outlined dense maxlength=200')
                assignee=ui.input(text('assignee'),value=saved.get('assignee','')).props('outlined dense maxlength=200')
                unassigned=ui.checkbox(text('unassigned'),value=saved.get('unassigned',False))
            ui.button(text('filters'),icon='filter_alt',on_click=lambda:page.load(reset=True)).tooltip(text('filters')).props('outline no-caps')
        with ui.row().classes('w-full justify-between gap-3'):
            ui.button(text('refresh'),icon='refresh',on_click=lambda:page.load()).tooltip(text('refresh')).props('outline no-caps')
            async def created(result):await open_job(result['id'])
            ui.button(text('create'),icon='add',on_click=lambda:create_dialog(api=api,context=context,bind_remote=bind_remote,active=alive,on_error=on_error,after=created)).tooltip(text('create')).props('no-caps')
        async def fetch(p):
            result=await api.disposition_page('jobs',limit=p.size,offset=(p.page-1)*p.size,query=search.value,
                lifecycle=lifecycle.value or None,job_type=kind.value or None,owner=owner.value,assignee=assignee.value,unassigned=unassigned.value,
                sort={'type_label':'job_type','state_label':'lifecycle_state'}.get(p.sort,p.sort) or 'id',descending=p.descending if p.sort else True)
            for row in result['items']:
                row['type_label']=text(row['job_type']);row['state_label']=text(row['lifecycle_state'])
                row['assignee']=row.get('assignee') or text('unassigned')
            result['_view']={'page':p.page,'size':p.size,'sort':p.sort,'descending':p.descending,'query':search.value,'lifecycle':lifecycle.value,'job_type':kind.value,'owner':owner.value,'assignee':assignee.value,'unassigned':unassigned.value}
            return result
        page=PageTable(columns=[column('job_number',sortable=True),column('type_label','job_type',True),column('state_label','lifecycle',True),column('owner',sortable=True),column('assignee',sortable=True),column('actions')],fetch=fetch,active=alive,on_error=on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'),on_loaded=lambda p,result:remember(result['_view']),initial=saved)
        restore_page(page,saved)
        page.table.add_slot('body-cell-actions','''<q-td :props="props"><q-btn flat dense icon="open_in_new" aria-label="'''+escape(text('open'))+'''" @click="$parent.$emit('open-job', props.row.id)"><q-tooltip>'''+escape(text('open'))+'''</q-tooltip></q-btn></q-td>''')
        page.table.on('open-job',lambda event:open_job(event.args))
        search.on('keydown.enter',lambda:page.load(reset=True))
        context,_=await asyncio.gather(context_task,page.load())


async def eligibility_screen(*, api, container, active, on_error, bind_remote, open_job, open_resource,
                             format_timestamp, saved=None, remember=lambda value:None, target_job=None,
                             filters_expanded=False, remember_filters=lambda value:None):
    saved=saved or {};filters=saved.get('filters',{})
    with container, ui.card().classes('detail-surface messaging-workspace w-full p-5 gap-4') as host:
        def alive():return active() and not host._deleted
        context_task=asyncio.create_task(api.disposition_page('context'))
        context={}
        ui.label(text('select_hint')).classes('text-sm text-slate-500')
        def disclosure_changed(event):
            if alive():remember_filters(bool(event.value))
        with ui.expansion(text('filters'),icon='filter_alt',value=bool(filters_expanded),
                          on_value_change=disclosure_changed).classes('w-full'):
            with ui.grid().classes('w-full gap-3 grid-cols-1 md:grid-cols-2 xl:grid-cols-3').props('dir='+('rtl' if current_locale_context()[0]=='ar' else 'ltr')):
                owner=selector(api=api,bind_remote=bind_remote,kind='owners',label='owner',active=alive,selected=filters.get('owner_selected'))
                status=ui.select({'':text('any'),**{i:status_label(i) for i in range(1,14)}},value=filters.get('status',''),label=text('status')).props('outlined dense')
                due_from,from_fold=wall_filter('due_from',filters)
                due_to,to_fold=wall_filter('due_to',filters)
                boolean={};tri={'':text('any'),'true':text('yes'),'false':text('no')}
                for name in ('vital','security','held'):
                    boolean[name]=ui.select(tri,value=filters.get(name,''),label=text(name)).props('outlined dense')
                boolean['active_job']=ui.select({'':text('any'),'true':text('in_active_job'),'false':text('no_active_job')},value=filters.get('active_job','false'),label=text('active_job')).props('outlined dense')
                sort=ui.select({key:text('normal_due' if key=='due' else key) for key in ('due','owner','status','type','vital','security','held')},value=filters.get('sort','due'),label=text('sort')).props('outlined dense')
                grouped=ui.checkbox(text('group_owner'),value=filters.get('group_owner',False))
                descending=ui.checkbox(text('descending'),value=saved.get('descending',False))
            async def apply_filters():
                page.sort='';page.descending=descending.value
                await page.load(reset=True)
            ui.button(text('filters'),icon='filter_alt',on_click=apply_filters).tooltip(text('filters')).props('outline no-caps')
        with ui.row().classes('w-full justify-between gap-3'):
            ui.button(text('refresh'),icon='refresh',on_click=lambda:page.load()).tooltip(text('refresh')).props('outline no-caps')
            add_button=ui.button(text('add'),icon='playlist_add',on_click=lambda:add_selected()).tooltip(text('add')).props('no-caps')
            add_button.disable()
        results=ui.column().classes('w-full gap-2').props('aria-live=polite')
        async def fetch(p):
            current={'status':status.value,'due_from':due_from.value,'due_to':due_to.value,'due_from_fold':from_fold.value,'due_to_fold':to_fold.value,'group_owner':grouped.value,
                     'sort':sort.value,**{key:control.value for key,control in boolean.items()},
                     'owner_selected':{'id':owner.value,'name':owner.options.get(owner.value)} if owner.value else None}
            result=await api.disposition_page('eligibility',limit=p.size,offset=(p.page-1)*p.size,sort={'identity':'id','due_label':'due','owner_label':'owner','state_label':'status'}.get(p.sort,p.sort) or sort.value,
                descending=p.descending,owner=owner.value,status=status.value or None,group_owner=grouped.value,
                due_from=date_filter(due_from.value,from_fold.value),
                due_to=date_filter(due_to.value,to_fold.value),
                **{key:(control.value if control.value else 'all' if key=='active_job' else None) for key,control in boolean.items()})
            previous_owner=object()
            for row in result['items']:
                if row['redacted']:
                    row.update(identity=text('restricted'),state_label=text('restricted'),due_label='—',owner_label='—',protection_label='—',job_label='—',_group_start=False)
                    continue
                reasons=[]
                for key,count_key in [('vital','vital_count'),('security','security_count'),('held','hold_count')]:
                    if row[key]:reasons.append(text(key)+(f" ({row[count_key]})" if row[count_key] is not None else ''))
                row.update(identity=row['aggregation_number']+' · '+row['title'],
                    state_label=status_label(row['disposition_status']),
                    due_label=format_timestamp(row['calculated_disposition_at']) if row['calculated_disposition_at'] else text('no_date'),
                    owner_label=row.get('owner') or '—',rule_label=(text(row['rule_source'])+' · '+str(row.get('rule_source_label') or '')) if row['rule_source'] in ('aggregation','classification') else '—',
                    protection_label=' · '.join(reasons) or text('no_blockers'),
                    job_label=row.get('job_number') or '—',
                    admission_label=text('in_active_job') if row.get('job_id') else text('blocked') if row['blocked'] else text('closed_required') if not row['date_closed'] else text('ready'),
                    _group_start=bool(grouped.value and row['owning_org_unit_id']!=previous_owner))
                row['unavailable']=bool(row['blocked'] or row.get('job_id'))
                row['unavailable_reason']=' · '.join(([text('in_active_job')+': '+row['job_label']] if row.get('job_id') else [])+reasons)
                acceleration=row.get('acceleration')
                if acceleration:
                    language,zone=current_locale_context()
                    accelerated_at=datetime.fromisoformat(acceleration['occurred_at'].replace('Z','+00:00'))
                    row['acceleration_label']=text('accelerated_badge',date=format_local_date(
                        utc_instant_to_working(accelerated_at,zone).date(),language))
                    row['acceleration_actor']=acceleration.get('actor_name') or '—'
                    row['acceleration_reason']=acceleration.get('reason') or '—'
                else:
                    row['acceleration_label']=None
                previous_owner=row['owning_org_unit_id']
            result['_view']={'page':p.page,'size':p.size,'sort':p.sort,'descending':p.descending,'filters':current}
            return result
        def loaded(p,result):
            p.table.selected=[];add_button.disable();remember(result['_view'])
        def eligibility_column(*args, **kwargs):
            return {**column(*args, **kwargs), 'headerStyle': 'vertical-align: top'}
        page=PageTable(columns=[eligibility_column('identity','aggregation',True),eligibility_column('state_label','status',True),eligibility_column('due_label','normal_due',True),eligibility_column('owner_label','owner',True),eligibility_column('protection_label','blockers'),eligibility_column('job_label','active_job'),eligibility_column('actions')],fetch=fetch,active=alive,on_error=on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'),selection='multiple',on_loaded=loaded,initial=saved)
        restore_page(page,saved)
        # Standard NiceGUI table slots provide per-row selection and page-local
        # grouping. No CSS overrides or client-side full-collection grouping.
        page.table.add_slot('header-selection','<span />')
        page.table.add_slot('body','''<q-tr v-if="props.row._group_start"><q-td colspan="100%" class="font-semibold bg-blue-50"><span dir="auto">{{ props.row.owner_label }}</span></q-td></q-tr>
        <q-tr :props="props" :class="{ 'bg-amber-50': props.row.unavailable }"><q-td auto-width>
          <q-icon v-if="props.row.unavailable" name="lock" size="sm" class="text-amber-900" tabindex="0" role="img" aria-hidden="false" :aria-label="props.row.unavailable_reason"><q-tooltip>{{ props.row.unavailable_reason }}</q-tooltip></q-icon>
          <q-checkbox v-else v-model="props.selected" :disable="!props.row.selectable" :aria-label="props.row.identity" /></q-td>
        <q-td v-for="col in props.cols" :key="col.name" :props="props" class="whitespace-normal">
          <template v-if="col.name === 'state_label'">{{ props.row.state_label }}
            <div v-if="props.row.acceleration_label" class="mt-1"><q-badge outline color="primary" tabindex="0" class="whitespace-normal" :label="props.row.acceleration_label">
              <q-tooltip class="whitespace-pre-wrap max-w-sm"><div>'''+escape(text('accelerated_by'))+''' <span dir="auto">{{ props.row.acceleration_actor }}</span></div><div>'''+escape(text('acceleration_reason'))+''' <span dir="auto">{{ props.row.acceleration_reason }}</span></div></q-tooltip>
            </q-badge></div></template>
          <template v-else-if="col.name === 'due_label'">{{ props.row.due_label }}<div v-if="props.row.acceleration_label" class="text-xs">'''+escape(text('retention_wait_waived'))+'''</div><div v-else-if="props.row.days_overdue !== null && props.row.days_overdue !== undefined" class="text-xs">'''+escape(text('overdue'))+''': {{ props.row.days_overdue }}</div></template>
          <template v-else-if="col.name === 'owner_label'"><span dir="auto">{{ props.row.owner_label }}</span><div class="text-xs">{{ props.row.rule_label }}</div></template>
          <template v-else-if="col.name === 'protection_label'">{{ props.row.admission_label }}<div class="text-xs">{{ props.row.protection_label }}</div></template>
          <template v-else-if="col.name === 'actions'"><div class="row no-wrap gap-1">
           <q-btn v-if="!props.row.redacted && !props.row.destroyed" flat dense icon="open_in_new" aria-label="'''+escape(text('open'))+'''" @click="$parent.$emit('open-root',props.row.id)"><q-tooltip>'''+escape(text('open'))+'''</q-tooltip></q-btn>
           <q-btn v-if="!props.row.redacted" flat dense icon="info" aria-label="'''+escape(text('blockers'))+'''" @click="$parent.$emit('blockers',props.row.id)"><q-tooltip>'''+escape(text('blockers'))+'''</q-tooltip></q-btn></div></template>
          <template v-else-if="col.name === 'job_label' && props.row.job_id"><q-btn flat dense no-caps :label="props.row.job_label" @click="$parent.$emit('open-job',props.row.job_id)" /></template>
          <span v-else dir="auto">{{ col.value }}</span>
        </q-td></q-tr>''')
        page.table.on('selection',lambda:add_button.set_enabled(any(r.get('selectable') for r in page.table.selected)))
        page.table.on('open-root',lambda event:open_resource('aggregation',event.args))
        page.table.on('open-job',lambda event:open_job(event.args))
        async def show_blockers(event):
            row=next((r for r in page.table.rows if r['id']==event.args and not r['redacted']),None)
            if row:await blockers_dialog(api=api,root=row,active=alive,on_error=on_error,open_resource=open_resource)
        page.table.on('blockers',show_blockers)
        async def add_selected():
            labels={r['id']:r['identity'] for r in page.table.selected if r.get('selectable')}
            selected=[{'root_id':r['id'],'expected_version':r['version']} for r in page.table.selected if r.get('selectable') and not r.get('redacted')]
            if not selected:return
            async def choose(job_id):
                current=await api.disposition_page(f'jobs/{job_id}')
                if not alive():return
                async def added(result):
                    results.clear()
                    with results:
                        ui.label(text('results')).classes('font-semibold')
                        for item in result['items']:
                            ui.label(labels.get(item['root_id'],str(item['root_id']))+' · '+(text('added') if item['success'] else text(item['code']) if item.get('code') in KEYS else text('not_added'))).classes('text-positive' if item['success'] else 'text-negative').props('role=status')
                    await page.load()
                def build(dialog_active):
                    ui.label(current['job_number']).props('dir=auto')
                    for row in page.table.selected:
                        if row.get('selectable'):ui.label(row['identity']).props('dir=auto')
                    return lambda:{'items':selected}
                with host:
                    await command_dialog(api=api,context=context,active=alive,on_error=on_error,title='add',build=build,path=f'jobs/{job_id}/memberships',version=current['version'],after=added,reason_required=False)
            if target_job:await choose(target_job)
            else:await choose_job_dialog(api=api,context=context,bind_remote=bind_remote,active=alive,on_error=on_error,choose=choose,root_ids=[r['root_id'] for r in selected])
        context,_=await asyncio.gather(context_task,page.load())


async def choose_job_dialog(*, api, context, bind_remote, active, on_error, choose, root_ids=None):
    if not active():return
    with ui.dialog() as dialog, ui.card().classes('messaging-workspace w-[850px] max-w-full gap-3'):
        ui.label(text('select_job')).classes('text-xl font-semibold')
        search=ui.input(text('search')).props('outlined dense maxlength=200').classes('w-full')
        def alive():return active() and dialog.value and not dialog._deleted
        async def fetch(p):
            result=await api.disposition_page('jobs',query=search.value,lifecycle='active',root_ids=root_ids,limit=p.size,offset=(p.page-1)*p.size)
            for row in result['items']:
                row['type_label']=text(row['job_type'])
                row['selection_reason']=text(row['selection_error']) if row.get('selection_error') in KEYS else ''
                row['selection_owner']=row.get('owner') if row.get('selection_error')=='disposition_owning_unit_mismatch' else None
            return result
        page=PageTable(columns=[column('job_number'),column('type_label','job_type'),column('actions')],fetch=fetch,active=alive,on_error=on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
        page.table.add_slot('body-cell-actions','''<q-td :props="props"><span class="inline-flex" :tabindex="props.row.selection_error ? 0 : -1"><q-btn flat dense icon="playlist_add" aria-label="'''+escape(text('select_job'))+'''"  :disable="!!props.row.selection_error" @click="$parent.$emit('choose',props.row.id)" /><q-tooltip>'''+escape(text('select_job'))+'''<template v-if="props.row.selection_reason"> · {{ props.row.selection_reason }}</template></q-tooltip></span><div v-if="props.row.selection_reason" class="text-xs text-amber-900">{{ props.row.selection_reason }}<div v-if="props.row.selection_owner">'''+escape(text('owner'))+''': <bdi>{{ props.row.selection_owner }}</bdi></div></div></q-td>''')
        async def use_job(identity):
            if not alive():return
            row=next((r for r in page.table.rows if r['id']==identity),None)
            if row and row.get('selection_error'):return
            dialog.close()
            await choose(identity)
        async def selected(event):await use_job(event.args)
        async def created(result):await use_job(result['id'])
        async def create():
            if not alive():return
            suggestion=None
            if root_ids:
                try:suggestion=await api.disposition_page('suggested-owner',root_ids=root_ids)
                except ApiError as error:
                    if alive():ui.notify(failure(error,on_error),type='negative')
                    return
            if not alive():return
            with dialog:
                await create_dialog(api=api,context=context,bind_remote=bind_remote,
                    active=alive,on_error=on_error,after=created,owner_suggestion=suggestion)
        page.table.on('choose',selected)
        search.on('keydown.enter',lambda:page.load(reset=True))
        with ui.row().classes('w-full justify-end gap-2'):
            ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
            ui.button(text('create'),icon='add',on_click=create).tooltip(text('create')).props('no-caps')
    dialog.open();await page.load()


async def job_screen(*, api, identity, container, active, on_error, bind_remote, open_job,
                     open_eligibility, open_resource, format_timestamp, event_label, preview=None, task_id=None, register_dirty=None, browse_resource=None, open_task=None, open_tasks=None, saved=None, remember=lambda value:None):
    with container, ui.card().classes('detail-surface messaging-workspace w-full p-5 gap-4') as host:
        def alive():return active() and not host._deleted
        status=ui.label(text('loading')).props('role=status')
        try:
            workspace=await api.disposition_page(f'jobs/{identity}/workspace',**({'task_id':task_id} if task_id else {}))
            job=workspace['job'];context={'roles':workspace['management_roles']}
        except ApiError as error:
            if alive():status.text=failure(error,on_error)
            return
        if not alive():return
        status.text=''
        task_view=task_id is not None
        view=dict(saved or {})
        member_saved=view.get('members') or {}
        review=None
        async def reopen():
            if task_view and open_task:await open_task(identity,task_id)
            else:await open_job(identity)
        async def refresh():
            if review and review.dirty():ui.notify(text('unsaved_warning'),type='warning');return
            await reopen()
        async def add_members():
            if review and review.dirty():ui.notify(text('unsaved_warning'),type='warning');return
            await open_eligibility(identity)
        with ui.row().classes('w-full items-center justify-between gap-3'):
            with ui.row().classes('items-center gap-3'):
                ui.label(job['job_number']).classes('text-xl font-semibold').props('dir=auto')
                ui.badge(text(job['lifecycle_state'])).props('outline')
            ui.button(text('refresh'),icon='refresh',on_click=refresh).tooltip(text('refresh')).props('outline no-caps')
        current_task=workspace.get('task') or {}
        display_stage=current_task.get('workflow_stage',job.get('workflow_stage')) if task_view else job.get('workflow_stage')
        if task_view:
            ui.label(text('stage')+' · '+(text(display_stage) if display_stage in KEYS else text(job['lifecycle_state']))).classes('text-2xl font-semibold').props('role=status')
        else:
            ui.label(text('workspace_details')).classes('text-2xl font-semibold')
        assigned=(current_task.get('direct_assignee') or current_task.get('role_queue')) if task_view else job.get('assignee')
        ui.label(text('assignee')+' · '+(assigned or text('unassigned'))).props('dir=auto').classes('text-slate-600')
        with ui.expansion(text('workspace_details'),icon='info',value=not task_view).classes('w-full'):
            with ui.grid().classes('w-full gap-3 grid-cols-1 md:grid-cols-2'):
                for label,value in [('job_type',text(job['job_type'])),('lifecycle',text(job['lifecycle_state'])),
                                    ('status',status_label(job['disposition_status'])),('stage',text(job['workflow_stage']) if job.get('workflow_stage') in KEYS else '—'),
                                    ('owner',job.get('owner') or '—'),('assignee',job.get('assignee') or text('unassigned')),('current_round',str(job.get('current_review_round',0))),('destruction_number',job.get('destruction_number') or '—'),
                                    ('claimant',(workspace.get('task') or {}).get('claimant') or '—'),('action_required',' · '.join(text(k) for k,v in job.get('action_required',{}).items() if v) or '—')]:
                    with ui.column().classes('detail-field gap-1'):
                        ui.label(text(label)).classes('detail-field-label');ui.label(value).classes('detail-field-value').props('dir=auto')
        async def reload(result):
            if result.get('_saved_work'):
                job['version']=result['job_version']
                await members.load()
                if alive():await history.load()
            else:await reopen()
        async def assign():
            if review and review.dirty():ui.notify(text('unsaved_warning'),type='warning');return
            def build(dialog_active):
                selected={'id':job['assigned_user_id'],'name':job['assignee']} if job['assigned_user_id'] else None
                person=selector(api=api,bind_remote=bind_remote,kind='assignees',label='assignee',active=dialog_active,job_type=lambda:job['job_type'],selected=selected,job_id=identity)
                return lambda:{'assigned_user_id':person.value}
            await command_dialog(api=api,context=context,active=alive,on_error=on_error,title='assign',build=build,path=f'jobs/{identity}/assignment',version=job['version'],after=reload)
        async def change_owner():
            if review and review.dirty():ui.notify(text('unsaved_warning'),type='warning');return
            def build(dialog_active):
                owner=selector(api=api,bind_remote=bind_remote,kind='owners',label='owner',active=dialog_active,selected={'id':job['owning_org_unit_id'],'name':job['owner']})
                return lambda:{'owning_org_unit_id':owner.value} if owner.value else None
            await command_dialog(api=api,context=context,active=alive,on_error=on_error,title='change_owner',build=build,path=f'jobs/{identity}/owning-unit',version=job['version'],after=reload)
        first_section='current_task' if task_view else 'workspace_details'
        sections=[first_section,'members','documents']
        if not task_view:sections.append('history')
        initial_section=view.get('section') if view.get('section') in sections else first_section
        with ui.tabs(value=initial_section).props('no-caps').classes('w-full') as navigation:
            for section in sections:ui.tab(section,label=text({'members':'workspace_members','history':'workspace_history'}.get(section,section))).props('no-caps')
        panels={}
        with ui.tab_panels(navigation,value=initial_section,keep_alive=True).classes('w-full'):
            for section in sections:
                with ui.tab_panel(section).classes('p-0'):
                    panels[section]=ui.column().classes('w-full gap-4')
        if 'history' not in panels:
            panels['history']=ui.column().classes('hidden')
        def section_active(section):return alive() and navigation.value==section
        with panels[first_section]:
            if not task_view and job['lifecycle_state']=='active' and context['roles']:
                with ui.row().classes('w-full gap-3'):
                    if job.get('assignment_editable'):ui.button(text('assign'),icon='person',on_click=assign).tooltip(text('assign')).props('outline no-caps')
                    if job['owner_editable']:ui.button(text('change_owner'),icon='corporate_fare',on_click=change_owner).tooltip(text('change_owner')).props('outline no-caps')
                    if job['membership_editable']:ui.button(text('add'),icon='playlist_add',on_click=add_members).tooltip(text('add')).props('no-caps')
            review=None
            if job['job_type']=='destruction':
                from .review import ReviewForm,workflow_panel
                if not task_view:workflow_panel(job,api=api,active=alive,on_error=on_error,format_timestamp=format_timestamp,physical=workspace.get('physical'),destruction=workspace.get('destruction'),completion=workspace.get('completion'),expanded=True)
                review_workspace=workspace if task_view else {**workspace,'task':None,'roles':[],'actions':[]}
                review=ReviewForm(api=api,workspace=review_workspace,active=alive,on_error=on_error,bind_remote=bind_remote,after=reload,format_timestamp=format_timestamp,open_resource=open_resource,preview=preview,browse_resource=browse_resource,history_host=panels['history'],documents_host=panels['documents'],history_active=lambda:section_active('history'),on_submitted=open_tasks if task_view else None)
                if not task_view:review.host.set_visibility(False)
                if register_dirty and task_view:register_dirty(review.dirty)
                async def related_view():
                    if review.dirty():ui.notify(text('unsaved_warning'),type='warning');return
                    if task_view:await open_job(identity)
                    elif open_task:await open_task(identity,workspace['task']['id'])
                if task_view or workspace.get('task') and open_task:
                    ui.button(text('workspace_details' if task_view else 'current_task'),icon='open_in_new',on_click=related_view).tooltip(text('workspace_details' if task_view else 'current_task')).props('outline no-caps')
            from .recovery import controls as recovery_controls,resolve_unit
            if not task_view:recovery_controls(api=api,job=job,value=workspace.get('recovery'),active=alive,on_error=on_error,after=reload,can_mutate=lambda:not review or not review.dirty())
        with panels['members']:
            ui.separator();ui.label(text('workspace_members')).classes('text-lg font-semibold')
            with ui.row().classes('w-full gap-3 items-end'):
                member_query=ui.input(text('search'),value=member_saved.get('query','')).props('outlined dense maxlength=200').classes('grow')
                member_state=ui.select({'':text('any'),**{k:text(k) for k in ('active','removed','completed_history','terminated_history')}},label=text('membership'),value=member_saved.get('state','')).props('outlined dense')
            async def fetch_members(p):
                result=await api.disposition_page(f'jobs/{identity}/memberships',limit=p.size,offset=(p.page-1)*p.size,query=member_query.value,state=member_state.value or None,sort=p.sort or 'id',descending=p.descending if p.sort else True)
                for row in result['items']:
                    row['last_viewed']=row['id']==view.get('opened_member') and not row['redacted']
                    row['classification_label']=' · '.join(v for v in (row.get('classification_code'),row.get('classification_title')) if v) or '—'
                    rule=row.get('effective_rule') or {}
                    row['rule_label']=' · '.join(str(v) for v in (text('current_period_years')+': '+str(rule['current_period_years']) if rule.get('current_period_years') is not None else None,text('intermediate_period_years')+': '+str(rule['intermediate_period_years']) if rule.get('intermediate_period_years') is not None else None,text(ACTIONS[rule['final_disposition']]) if rule.get('final_disposition') in ACTIONS else None) if v is not None) or '—'
                    row['local_label']=text('local_override') if rule.get('rule_source')=='aggregation' else ' · '.join(v for v in (text('classification'),row.get('rule_source_code'),row.get('rule_source_title')) if v) if rule else '—'
                    row['medium_label']=text(row['medium']) if row.get('medium') in KEYS else '—'
                    row['identity']=text('restricted') if row['redacted'] else text('retained_unit',id=row['root_aggregation_id']) if row.get('destroyed') else row['aggregation_number']+' · '+row['title']
                    row['membership_label']=text(row['membership_state'])
                    row['status_label']=status_label(row['disposition_status']) if not row['redacted'] else '—'
                    row['removal_label']=text('removal_proposed') if row.get('removal_proposed') and row['membership_state']=='active' else ''
                    row['notice']=text(row['removal_required_reason']) if row['membership_state']=='active' and row.get('removal_required_reason') in KEYS else ''
                    row['added_label']=format_timestamp(row['added_at']);row['removed_label']=format_timestamp(row.get('removed_at')) if row.get('removed_at') else '—'
                    row['partial_label']=text('partially_destroyed') if row.get('partially_destroyed') else ''
                    row['blocked']=row['membership_state']=='active' and any(row.get(k) for k in ('vital','security','held','relationships_block_final'))
                    row['blocker_label']=' · '.join(text(k) for k in ('vital','security','held') if row.get(k))
                    if row.get('relationships_block_final'):row['blocker_label']+=' · '+text('final_blocked')
                    row['needs_claim']='claim' in workspace.get('actions',[]) and row['membership_state']=='active' and not row['redacted']
                    row['can_propose']=bool(review and 'propose' in review.actions and row['membership_state']=='active' and not row['redacted'])
                    row['can_remove']=job['membership_editable'] and row['membership_state']=='active' and not row['redacted']
                return result
            def remember_members(p,result):
                view.update(section=navigation.value,job_id=identity,task_id=task_id,
                  members={'page':p.page,'size':p.size,'sort':p.sort,'descending':p.descending,
                    'query':member_query.value,'state':member_state.value})
                remember(dict(view))
            members=PageTable(columns=[column('identity','aggregation',True),column('owning_org_unit_name','owner',True),column('classification_label','classification',True),column('rule_label','rule'),column('local_label','local_override'),column('medium_label','medium'),column('proposal_count','proposals'),column('membership_label','membership',True),column('status_label','status',True),column('added_label','added_at'),column('removed_label','removed_at'),column('actions')],fetch=fetch_members,active=lambda:section_active('members'),on_error=on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'),initial=member_saved,on_loaded=remember_members)
            members.table.add_slot('body-cell-identity', '''<q-td :props="props" :class="props.row.last_viewed ? 'bg-blue-50' : ''">
              <span :id="'disposition-member-' + props.row.id" tabindex="-1">{{ props.row.identity }}</span>
              <div v-if="props.row.last_viewed" class="text-primary text-weight-medium"><q-icon name="visibility"/> '''+escape(text('last_viewed'))+'''</div></q-td>''')
            members.table.add_slot('body-cell-status_label','''<q-td :props="props">{{ props.row.status_label }}<div v-if="props.row.partial_label" class="text-amber-900 whitespace-normal">{{ props.row.partial_label }}</div><div class="text-amber-900 whitespace-normal">{{ props.row.notice }}</div><div v-if="props.row.removal_label" class="text-amber-900 whitespace-normal"><q-icon name="remove_circle_outline"/> {{ props.row.removal_label }}</div><div v-if="props.row.blocked" class="text-amber-900 whitespace-normal">{{ props.row.blocker_label }}</div></q-td>''')
            members.table.add_slot('body-cell-actions','''<q-td :props="props"><div class="row no-wrap gap-1">
              <q-btn v-if="!props.row.redacted && !props.row.destroyed" flat dense icon="open_in_new" aria-label="'''+escape(text('open'))+'''" @click="$parent.$emit('open-root',props.row.id)"><q-tooltip>'''+escape(text('open'))+'''</q-tooltip></q-btn>
              <q-btn v-if="!props.row.redacted && props.row.membership_state === 'active'" flat dense icon="info" aria-label="'''+escape(text('blockers'))+'''" @click="$parent.$emit('blockers',props.row.id)"><q-tooltip>'''+escape(text('blockers'))+'''</q-tooltip></q-btn>
              <q-btn v-if="!props.row.redacted" flat dense icon="rule" aria-label="'''+escape(text('proposals'))+'''" @click="$parent.$emit('show-proposals',props.row.id)"><q-tooltip>'''+escape(text('proposals'))+'''</q-tooltip></q-btn>
              <span v-if="props.row.can_propose || props.row.needs_claim" class="inline-flex" :tabindex="props.row.needs_claim ? 0 : -1"><q-btn :disable="props.row.needs_claim" flat dense icon="playlist_add" aria-label="'''+escape(text('propose'))+'''" @click="$parent.$emit('propose',props.row.id)"/><q-tooltip><template v-if="props.row.needs_claim">'''+escape(text('claim_before_proposals'))+'''</template><template v-else>'''+escape(text('propose'))+'''</template></q-tooltip></span>
              <q-btn v-if="props.row.destroyed && !props.row.redacted" flat dense icon="inventory_2" aria-label="'''+escape(text('retained_record'))+'''" @click="$parent.$emit('retained-unit',props.row.id)"><q-tooltip>'''+escape(text('retained_record'))+'''</q-tooltip></q-btn>
              <q-btn v-if="props.row.can_recover" flat dense icon="restore" aria-label="'''+escape(text('recover_unit'))+'''" @click="$parent.$emit('recover-unit',props.row.id)"><q-tooltip>'''+escape(text('recover_unit'))+'''</q-tooltip></q-btn>
              <q-btn v-if="props.row.can_remove" flat dense color="negative" icon="remove_circle_outline" aria-label="'''+escape(text('remove'))+'''" @click="$parent.$emit('remove-member',props.row.id)"><q-tooltip>'''+escape(text('remove'))+'''</q-tooltip></q-btn>
              </div></q-td>''')
            async def open_member(event):
                row=next((r for r in members.table.rows if r['id']==event.args),None)
                if row and not row['redacted']:
                    view['opened_member']=row['id'];remember_members(members,{})
                    await open_resource('aggregation',row['root_aggregation_id'])
            members.table.on('open-root',open_member)
            async def propose(event):
                row=next((r for r in members.table.rows if r['id']==event.args and r.get('can_propose')),None)
                if row:await review.edit(root=row)
            members.table.on('propose',propose)
            async def show_proposals(event):
                row=next((r for r in members.table.rows if r['id']==event.args and not r['redacted']),None)
                if row and review:await review.show_proposals(row)
            members.table.on('show-proposals',show_proposals)
            member_query.on('keydown.enter',lambda:members.load(reset=True));member_state.on_value_change(lambda:members.load(reset=True))
            async def protection(event):
                row=next((r for r in members.table.rows if r['id']==event.args),None)
                if row and not row['redacted']:await blockers_dialog(api=api,root={**row,'id':row['root_aggregation_id']},active=alive,on_error=on_error,open_resource=open_resource)
            members.table.on('blockers',protection)
            async def remove_member(event):
                row=next((r for r in members.table.rows if r['id']==event.args and r['can_remove']),None)
                if not row:return
                if review and review.dirty():ui.notify(text('unsaved_warning'),type='warning');return
                def build(dialog_active):
                    ui.label(row['identity']).props('dir=auto')
                    return lambda:{'root_version':row['root_version']}
                await command_dialog(api=api,context=context,active=alive,on_error=on_error,title='remove',confirm='confirm_remove',build=build,path=f"memberships/{row['id']}/remove",version=row['version'],after=reload)
            members.table.on('remove-member',remove_member)
            async def recover_unit(event):
                row=next((r for r in members.table.rows if r['id']==event.args and r.get('can_recover')),None)
                if row:await resolve_unit(api=api,job=job,row=row,roles=(workspace.get('recovery') or {}).get('roles',[]),active=alive,on_error=on_error,after=reload)
            members.table.on('recover-unit',recover_unit)
            async def retained(event):
                row=next((r for r in members.table.rows if r['id']==event.args and r.get('destroyed') and not r['redacted']),None)
                if row:
                    from .destruction import retained_unit
                    await retained_unit(api=api,root_id=row['root_aggregation_id'],active=alive,on_error=on_error,format_timestamp=format_timestamp)
            members.table.on('retained-unit',retained)

        from .artifacts import documents_panel
        with panels['documents']:
            documents=documents_panel(api=api,job=job,active=lambda:section_active('documents'),on_error=on_error,after=reload,open_resource=open_resource,preview=preview,format_timestamp=format_timestamp,column=column,can_mutate=lambda:not review or not review.dirty())
        with panels['history']:
            ui.separator();ui.label(text('history')).classes('text-lg font-semibold')
            async def fetch_history(p):
                result=await api.disposition_page(f'jobs/{identity}/history',limit=p.size,offset=(p.page-1)*p.size)
                for row in result['items']:
                    row['operation_label']=event_label(row['operation']);row['time_label']=format_timestamp(row['occurred_at'])
                    row['actor_label']=row.get('actor_name') or '—';row['reason_label']=row.get('reason') or '—'
                return result
            history=PageTable(columns=[column('time_label','occurred'),column('operation_label','operation'),column('actor_label','actor'),column('reason_label','reason'),column('actions')],fetch=fetch_history,active=lambda:section_active('history'),on_error=on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
            from .history import details_action
            details_action(history,format_timestamp)
        # Supporting pages are read on entry, not on the initial task path.
        # Re-entering refreshes data without discarding unsaved task work.
        async def selected_section(event):
            if not alive():return
            view.update(section=event.value,job_id=identity,task_id=task_id);remember(dict(view))
            loader={'members':members.load,'documents':documents,'history':history.load}.get(event.value)
            if loader:await loader()
            if event.value=='history' and review:await review.refresh_history()
        navigation.on_value_change(selected_section)
        if initial_section!=first_section:
            await selected_section(type('SectionEvent',(),{'value':initial_section})())
            if initial_section=='members' and any(r.get('last_viewed') for r in members.table.rows) and alive():
                ui.timer(.1,lambda:ui.run_javascript("document.getElementById('disposition-member-"+str(int(view['opened_member']))+"')?.scrollIntoView({block:'center'});") if section_active('members') else None,once=True)
        if review:
            if task_view:
                task=workspace.get('task') or {}
                if task.get('task_state','open') in ('open','claimed') and task.get('workflow_stage',job['workflow_stage'])==job['workflow_stage']:
                    await review.load()
                else:
                    review.host.clear()
                    with review.host:ui.label(text('no_current_task')).props('role=status')
            else:
                review.history_sections()
                from .email import controls as email_controls
                email_controls(review,host=panels['documents'])
                from .external import request_controls
                request_controls(review,host=panels['documents'])



async def accelerate_dialog(*, api, root, active, on_error, after):
    try:
        context,facts=await asyncio.gather(api.disposition_page('context'),api.disposition_page(f"aggregations/{root['id']}/eligibility"))
    except ApiError as error:
        if active():ui.notify(failure(error,on_error),type='negative')
        return
    if not active():return
    def build(dialog_active):
        ui.label(root['aggregation_number']+' · '+root['title']).props('dir=auto')
        ui.label(status_label(facts['eligible_status']))
        ui.label(text('accelerate_scope')).classes('text-sm')
        return lambda:{}
    await command_dialog(api=api,context=context,active=active,on_error=on_error,title='accelerate',build=build,
                         path=f"aggregations/{root['id']}/accelerate",version=facts['version'],after=after)
