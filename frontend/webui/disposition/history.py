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


def details_action(page,format_timestamp):
    page.table.add_slot('body-cell-actions','''<q-td :props="props"><q-btn flat dense icon="history" aria-label="'''+escape(text('details'))+'''" @click="$parent.$emit('event-detail',props.row.id)"><q-tooltip>'''+escape(text('details'))+'''</q-tooltip></q-btn></q-td>''')
    def opened(event):
        row=next((r for r in page.table.rows if r['id']==event.args),None)
        if row:event_details(row,format_timestamp)
    page.table.on('event-detail',opened)


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
