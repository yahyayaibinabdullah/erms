"""Bounded authorized history disclosures, sharing Wathiq page tables."""
import json
from html import escape
from nicegui import ui
from ..resource_relationships import PageTable
from ..event_labels import event_label
from .messages import text
from .screens import column


def event_details(row,format_timestamp):
    with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[900px] max-w-full gap-4'):
        ui.label(event_label(row['operation'])).classes('text-xl font-semibold')
        for key,value in [('actor',row.get('actor_name')),('occurred',format_timestamp(row['occurred_at'])),('reason',row.get('reason'))]:
            ui.label(text(key)+' · '+str(value or '—')).props('dir=auto')
        for key,source in [('before_values','before_state'),('after_values','after_state')]:
            ui.label(text(key)).classes('font-semibold')
            value=row.get(source)
            if value is None:value=(row.get('metadata') or {}).get('before' if source=='before_state' else 'after')
            ui.code(json.dumps(value,ensure_ascii=False,indent=2,default=str),language='json').classes('w-full')
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
                row['operation_label']=event_label(row['operation']);row['time_label']=format_timestamp(row['occurred_at'])
            return result
        page=PageTable(columns=[column('time_label','occurred'),column('operation_label','operation'),column('actor_name','actor'),column('reason'),column('actions')],fetch=fetch,active=alive,on_error=on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
        details_action(page,format_timestamp)
        ui.button(text('close'),on_click=dialog.close).props('flat no-caps')
    dialog.open();await page.load()
