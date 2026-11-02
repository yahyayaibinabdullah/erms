"""Bounded authorized history disclosures, sharing Wathiq page tables."""
import json
from html import escape
from nicegui import ui
from ..resource_relationships import PageTable
from ..event_labels import event_label
from .messages import text
from .screens import column


def readable_event_fields(row,format_timestamp):
    from .history_presenter import sections
    metadata=row.get('metadata') or {}
    blocker=row['operation'] in ('DISPOSITION_BLOCKERS_DETECTED','DISPOSITION_BLOCKERS_RESOLVED')
    if metadata.get('redacted'):
        ui.label(text('history_unavailable')).props('role=status')
    else:
        if blocker:ui.label(text('history_blockers_resolved' if row['operation'].endswith('RESOLVED') else 'history_blockers_detected'))
        for heading,items in sections(row,format_timestamp):
            ui.label(text(heading)).classes('font-semibold')
            with ui.grid().classes('w-full gap-3 grid-cols-1 md:grid-cols-2'):
                for label,value in items:
                    with ui.column().classes('detail-field gap-1'):
                        ui.label(label).classes('detail-field-label')
                        ui.label(value).classes('detail-field-value').props('dir=auto')
        if row.get('display_references'):
            ui.label(text('history_current_names')).classes('text-sm text-slate-500')


def event_details(row,format_timestamp):
    blocker=row['operation'] in ('DISPOSITION_BLOCKERS_DETECTED','DISPOSITION_BLOCKERS_RESOLVED')
    with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[900px] max-w-full gap-4'):
        ui.label(event_label(row['operation'],event=row)).classes('text-xl font-semibold')
        for key,value in [('history_detected_by' if blocker else 'actor',row.get('actor_name')),('history_detected_at' if blocker else 'occurred',format_timestamp(row['occurred_at']))]:
            if value:ui.label(text(key)+' · '+str(value)).props('dir=auto')
        if row.get('reason') and not blocker:ui.label(text('reason')+' · '+row['reason']).props('dir=auto')
        readable_event_fields(row,format_timestamp)
        if row.get('can_view_technical_details'):
            with ui.expansion(text('history_technical'),icon='code',value=False).classes('w-full'):
                ui.code(json.dumps({k:v for k,v in row.items() if k not in ('display_references','can_view_technical_details')},ensure_ascii=False,indent=2,default=str),language='json').classes('w-full')
        ui.button(text('close'),on_click=dialog.close).props('flat no-caps')
    dialog.open()


def details_action(page,format_timestamp,*,api=None,job_id=None,active=lambda:True,on_error=str):
    # Authored English/Arabic comments and mixed aggregation labels need their
    # own native direction, rather than inheriting the surrounding table's RTL.
    for field in ('reason_label','reason','subject_label'):
        if any(col['name']==field for col in page.table.columns):
            page.table.add_slot('body-cell-'+field,'<q-td :props="props"><span dir="auto" class="whitespace-pre-wrap">{{ props.value }}</span></q-td>')
    page.table.add_slot('body-cell-actions','''<q-td :props="props"><q-btn flat dense icon="history" aria-label="'''+escape(text('details'))+'''" @click="$parent.$emit('event-detail',props.row.id)"><q-tooltip>'''+escape(text('details'))+'''</q-tooltip></q-btn></q-td>''')
    async def opened(event):
        row=next((r for r in page.table.rows if r['id']==event.args),None)
        if not row or not active():return
        if api and row.get('history_group'):
            await action_details(row,format_timestamp,api=api,job_id=job_id,active=active,on_error=on_error)
        else:event_details(row,format_timestamp)
    page.table.on('event-detail',opened)


async def action_details(row,format_timestamp,*,api,job_id,active,on_error):
    """Load the full authorized action in server pages only on disclosure."""
    from .history_presenter import subject
    with ui.dialog() as dialog,ui.card().classes('messaging-workspace gap-4').style('width: 50vw; min-width: min(640px, calc(100vw - 32px)); max-width: calc(100vw - 32px)'):
        ui.label(event_label(row['operation'],event=row)).classes('text-xl font-semibold')
        for key,value in [('actor',row.get('actor_name')),('occurred',format_timestamp(row.get('action_occurred_at') or row['occurred_at'])),('reason',row.get('reason'))]:
            if value:ui.label(text(key)+' · '+str(value)).props('dir=auto').classes('whitespace-pre-wrap')
        ui.label(text('history_action_explanation')).classes('text-sm text-slate-600')
        with ui.expansion(text('history_action_changes',count=row['history_group']['event_count']),icon='history',value=False).classes('w-full') as expansion:
            host=ui.column().classes('w-full gap-3')
        def alive():return active() and dialog.value and not dialog._deleted and expansion.value
        state={'page':None}
        async def opened(event):
            if not event.value or not alive():return
            if state['page'] is None:
                with host:
                    async def fetch(p):
                        result=await api.disposition_page(f"jobs/{job_id}/history/{row['id']}/events",limit=p.size,offset=(p.page-1)*p.size)
                        for item in result['items']:
                            item.update(operation_label=event_label(item['operation'],event=item),time_label=format_timestamp(item['occurred_at']),subject_label=subject(item))
                        return result
                    page=PageTable(columns=[column('time_label','occurred'),column('operation_label','operation'),column('subject_label','history_affected_item'),column('actions')],fetch=fetch,active=alive,on_error=on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
                    details_action(page,format_timestamp,active=alive)
                    state['page']=page
            await state['page'].load()
        expansion.on_value_change(opened)
        ui.button(text('close'),on_click=dialog.close).props('flat no-caps')
    dialog.open()


async def revision_history(*,api,job_id,kind,identity,active,on_error,format_timestamp):
    with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[1000px] max-w-full gap-4'):
        ui.label(text('revision_history')).classes('text-xl font-semibold')
        def alive():return active() and dialog.value and not dialog._deleted
        async def fetch(p):
            result=await api.disposition_page(f'jobs/{job_id}/review-history/{kind}/{identity}',limit=p.size,offset=(p.page-1)*p.size)
            for row in result['items']:
                row['operation_label']=event_label(row['operation'],event=row);row['time_label']=format_timestamp(row['occurred_at'])
            return result
        page=PageTable(columns=[column('time_label','occurred'),column('operation_label','operation'),column('actor_name','actor'),column('reason'),column('actions')],fetch=fetch,active=alive,on_error=on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
        details_action(page,format_timestamp)
        ui.button(text('close'),on_click=dialog.close).props('flat no-caps')
    dialog.open();await page.load()
