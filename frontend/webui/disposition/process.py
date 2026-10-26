"""Compact, read-only workflow progress using standard NiceGUI components."""
from nicegui import ui
from .messages import text
from ..api_client import ApiError


def process_stages(job, *, physical=None, destruction=None, completion=None):
    """Project the saved route and current stage, not an audit-history timeline.

    Correction resets progress to preparation; earlier rounds are disclosed below.
    Physical work is included only once the workspace confirms applicability.
    A physical-only completion must not imply that digital work occurred.
    """
    route=job['review_route'];stage=job.get('workflow_stage')
    lifecycle=job.get('lifecycle_state','active')
    preparation='manager_preparation' if route=='records_manager_only' else 'officer_preparation'
    if stage in ('officer_correction','manager_correction'):preparation=stage
    entries=[('job_created',False),(preparation,False),
             ('file_administrator_review',route!='standard' or bool(job.get('file_administrator_skipped'))),
             ('unit_manager_review',route!='standard'),
             ('records_manager_review',route=='records_manager_only'),
             ('external_approval_pending',False)]
    if (physical or {}).get('physical_required') or stage=='physical_destruction':
        entries.append(('physical_destruction',False))
    physical_only_complete=lifecycle=='completed' and bool((physical or {}).get('confirmation')) and not (destruction or {}).get('progress') and not (completion or {}).get('certificate')
    if not physical_only_complete:
        entries.extend([('digital_destruction',False),('certificate_generation',False)])
    entries.append(('completed',False))
    current=next((i for i,(key,_) in enumerate(entries) if key==stage),None)
    if lifecycle=='completed':current=len(entries)-1
    result=[]
    for index,(key,skipped) in enumerate(entries):
        state='skipped' if skipped else 'tracker_upcoming'
        if not skipped:
            if lifecycle=='completed' or current is not None and index<current or key=='job_created':state='completed'
            elif index==current:state='terminated' if lifecycle=='terminated' else 'tracker_current'
        result.append({'key':key,'state':state})
    return result


def process_diagram(job, *, expanded=False, api=None, active=lambda:True, on_error=str, format_timestamp=str, **context):
    with ui.expansion(text('workflow'),icon='format_list_numbered',value=expanded).classes('w-full'):
        ui.label(text('review_route')+' · '+text(job['review_route'])).classes('text-sm text-slate-600')
        saved=job.get('current_review_round') or 0
        preparing=job.get('workflow_stage') in ('officer_preparation','manager_preparation','officer_correction','manager_correction')
        number=max(1,saved+1 if job.get('workflow_stage') in ('officer_correction','manager_correction') else saved)
        ui.badge(text('tracker_preparing_round' if preparing else 'tracker_round',number=number)).props('outline')
        notice=ui.column().classes('w-full gap-1')
        with ui.column().classes('w-full gap-1'):
            for step in process_stages(job,**context):
                state=step['state']
                icon,color={'completed':('check_circle','positive'),'tracker_current':('radio_button_checked','primary'),
                            'tracker_upcoming':('radio_button_unchecked','grey-6'),'skipped':('skip_next','grey-6'),
                            'terminated':('stop_circle','warning')}[state]
                with ui.grid(columns='auto minmax(0, 1fr) auto').classes('w-full items-center gap-2 p-1 rounded'+(' bg-blue-50' if state=='tracker_current' else '')):
                    ui.icon(icon,color=color,size='sm').props('aria-hidden=true')
                    ui.label(text('tracker_completion' if step['key']=='completed' else step['key'])).classes('text-sm '+('font-semibold' if state=='tracker_current' else 'text-slate-500' if state in ('tracker_upcoming','skipped') else ''))
                    ui.badge(text(state),color=color).props('outline')
        if api and saved:
            previous_rounds(job,api,notice,active,on_error,format_timestamp)


def previous_rounds(job,api,notice,active,on_error,format_timestamp):
    """Page-local data, reloaded on navigation/mutation; no shared history cache."""
    with ui.expansion(text('tracker_previous'),icon='history',value=False).classes('w-full') as expansion:
        content=ui.column().classes('w-full gap-3')
        feedback=ui.label('').props('role=status')
        more=ui.button(text('tracker_more'),icon='expand_more').tooltip(text('tracker_more')).props('flat no-caps')
        more.set_visibility(False)
    from .screens import failure
    state={'busy':False,'offset':0,'more':False,'loaded':False}
    def alive():return active() and not content.is_deleted
    def entry(stage,outcome,actor,time,reason=None):
        with ui.column().classes('w-full gap-1 py-2'):
            with ui.grid(columns='minmax(0, 1fr) auto').classes('w-full items-center gap-2'):
                ui.label(text(stage)).classes('font-semibold')
                ui.badge(text(outcome),color='orange-9' if outcome=='rejected' else 'positive').props('outline')
            ui.label(' · '.join(v for v in (actor,format_timestamp(time) if time else None) if v)).props('dir=auto').classes('text-sm text-slate-600')
            if reason:ui.label(text('reason')+' · '+reason).props('dir=auto').classes('whitespace-pre-wrap')
    async def load(initial=False):
        if not alive() or state['busy']:return
        state['busy']=True;more.disable()
        with content:feedback.text=text('loading')
        try:
            result=await api.disposition_page(f"jobs/{job['id']}/workflow-progress",limit=1 if initial else 25,offset=state['offset'])
            if not alive():return
            with content:
                for row in result['items']:
                    if row.get('redacted'):
                        ui.label(text('history_unavailable'));continue
                    ui.label(text('tracker_round',number=row['round_number'])).classes('text-lg font-semibold')
                    if job['review_route']!='records_manager_only':
                        entry('officer_preparation','tracker_submitted',row.get('actor_name'),row['started_at'],row.get('submission_reason'))
                    for decision in row['decisions']:
                        entry(decision['review_stage'],decision['decision'],decision.get('actor_name'),decision['decided_at'],decision.get('reason'))
                    if row.get('invalidated_at'):
                        ui.label(text('tracker_invalidated')+' · '+format_timestamp(row['invalidated_at']))
                        ui.label(row['invalidation_reason']).props('dir=auto')
                    ui.separator()
                if initial and result['items'] and not result['items'][0].get('redacted'):
                    latest=result['items'][0]
                    rejected=next((d for d in reversed(latest['decisions']) if d['decision']=='rejected'),None)
                    with notice:
                        if rejected:
                            ui.label(text('tracker_returned',stage=text(rejected['review_stage']),number=latest['round_number'])).classes('text-amber-800 font-semibold')
                            ui.label(' · '.join(v for v in (rejected.get('actor_name'),format_timestamp(rejected['decided_at'])) if v)).props('dir=auto')
                            ui.label(rejected.get('reason') or '').props('dir=auto').classes('whitespace-pre-wrap')
                        elif latest.get('invalidated_at'):
                            ui.label(text('tracker_invalidated')).classes('text-amber-800')
                            ui.label(format_timestamp(latest['invalidated_at']))
                            ui.label(latest['invalidation_reason']).props('dir=auto')
                state['offset']+=len(result['items']);state['more']=result['has_more'];state['loaded']=True
                feedback.text='' if state['offset'] else text('tracker_no_previous')
                more.text=text('tracker_more');more.set_visibility(state['more'])
        except ApiError as error:
            if alive():
                with content:feedback.text=failure(error,on_error);more.text=text('refresh');more.set_visibility(True)
        finally:
            state['busy']=False
            if alive():more.enable()
    more.on_click(lambda:load(initial=not state['loaded']))
    expansion.on_value_change(lambda e:load(initial=True) if e.value and not state['loaded'] else None)
    ui.timer(.01,lambda:load(initial=True),once=True)
