"""Structured proposal disclosures with lazy, bounded revision history."""
import asyncio
import json
from nicegui import ui,context
from ..api_client import ApiError
from ..resource_relationships import text as page_text,language
from ..event_labels import event_label
from .messages import text
from .proposal_presenter import proposed_change,ACTIONS


def field(label,value):
    with ui.column().classes('detail-field min-w-0 gap-1'):
        ui.label(text(label)).classes('detail-field-label')
        ui.label(str(value) if value is not None and value!='' else '—').props('dir=auto').classes('detail-field-value whitespace-pre-wrap break-words')


def fields(items):
    with ui.grid().classes('w-full grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3'):
        for label,value in items:field(label,value)


def rule(value):
    value=value or {}
    for key in ('current_period_years','intermediate_period_years','instructions'):field(key,value.get(key))
    field('final_disposition',text(ACTIONS[value['final_disposition']]) if value.get('final_disposition') in ACTIONS else '—')


def comparison(row):
    facts=row['current_values'];values=row['proposed_values'];kind=row['proposal_type']
    # Creation/hold proposals do not snapshot an absent relationship/hold.
    # Show only recorded before-values, never infer an earlier membership state.
    paired=kind in ('make_vital','blocking_security','local_retention_override','remove_aggregation_relationship','remove_record_relationship')
    with ui.grid().classes('w-full grid-cols-1 sm:grid-cols-2 gap-4'):
        if paired:
            with ui.column().classes('w-full min-w-0 gap-3 rounded-lg bg-slate-50 p-4'):
                ui.label(text('current_values')).classes('font-semibold')
                if kind=='make_vital':field('vital',text('yes' if facts.get('is_vital') else 'no'))
                elif kind=='blocking_security':field('security_level_id',row.get('current_security_name'))
                elif kind=='local_retention_override':rule(facts.get('local_retention') or facts.get('classification_rule'))
                else:
                    field('relationship_type_id',row.get('relationship_type_name'))
                    field('relationship_from',row.get('relationship_source_label'))
                    field('relationship_to',row.get('relationship_target_label'))
        with ui.column().classes('w-full min-w-0 gap-3 rounded-lg bg-blue-50 p-4'+(' sm:col-span-2' if not paired else '')):
            ui.label(text('proposed_values')).classes('font-semibold')
            if kind=='local_retention_override':rule(values)
            elif kind=='make_vital':field('vital',text('yes'))
            elif kind=='blocking_security':field('security_level_id',row.get('proposed_security_name') or (facts.get('proposed_security') or {}).get('name'))
            elif kind=='add_to_holds':
                for hold in facts.get('holds') or []:field('hold_ids',hold['code']+' · '+hold['name'])
            else:ui.label(proposed_change(row)).props('dir=auto').classes('whitespace-pre-wrap break-words')
            if kind=='create_aggregation_relationship':
                field('direction',text(values['direction']))


def information(row,format_timestamp):
    revised=row.get('last_revised_at')
    with ui.expansion(text('proposal_information'),icon='info',value=False).classes('w-full'):
        fields([('proposer',row.get('proposer_name')),('acting_task_role',row.get('proposer_role_name')),
                ('stage',text(row['proposer_stage'])),('review_round',row['review_round']),
                ('proposed_at',format_timestamp(row['proposed_at'])),
                ('last_editor',' · '.join(v for v in (row.get('editor_name'),row.get('editor_role_name')) if v) if revised else text('not_revised')),
                *([('revised_at',format_timestamp(revised))] if revised else [])])
        if row.get('redacted'):return
        facts=row['current_values']
        ui.separator();ui.label(text('proposal_context')).classes('font-semibold')
        fields([('aggregation',' · '.join(v for v in (facts.get('aggregation_number'),facts.get('title')) if v)),
                ('vital',text('yes' if facts.get('is_vital') else 'no')),('security_level_id',row.get('current_security_name'))])
        if row['proposal_type']=='local_retention_override':
            for heading,key in [('local_override','local_retention'),('classification','classification_rule')]:
                ui.label(text(heading)).classes('font-semibold')
                with ui.grid().classes('w-full grid-cols-1 sm:grid-cols-2 gap-3'):rule(facts.get(key))


def revision_changes(row,format_timestamp):
    """Business-value differences; audit attribution remains in recorded information."""
    from .history_presenter import FIELDS,facts
    metadata=row.get('metadata') or {}
    if metadata.get('redacted'):return []
    before=row.get('before_state') or metadata.get('before');after=row.get('after_state') or metadata.get('after')
    if not isinstance(before,dict) or not isinstance(after,dict):return []
    refs=row.get('display_references') or {}
    def value(key,item):
        if item is None or item=='' or item==[]:return text('history_not_set')
        rendered=facts({key:item},refs,format_timestamp)
        return rendered[0][1] if rendered else text('history_unavailable')
    changes=[]
    pairs=[(before.get('proposed_values') or {},after.get('proposed_values') or {})]
    pairs.append(({k:before.get(k) for k in ('reason','withdrawal_reason','proposal_state')},{k:after.get(k) for k in ('reason','withdrawal_reason','proposal_state')}))
    for old,new in pairs:
        for key in sorted(old.keys()|new.keys()):
            if key in FIELDS and old.get(key)!=new.get(key):changes.append((text(FIELDS[key]),value(key,old.get(key)),value(key,new.get(key))))
    return changes


class ProposalRevisions:
    """Per-dialog pages, no cache; refresh on tab entry and ignore abandoned reads."""
    def __init__(self,review,identity,active):
        self.review,self.identity,self.active=review,identity,active
        self.client=context.client;self.page=1;self.size=25;self.revision=0
        self.status=ui.label('').props('role=status').classes('text-sm text-slate-600')
        self.entries=ui.column().classes('w-full gap-2')
        with ui.row().classes('w-full items-center justify-end gap-3 flex-wrap'):
            self.size_control=ui.select([10,25,50],value=25,label=page_text('page_size')).props('outlined dense').classes('w-40')
            self.count=ui.label('').classes('text-sm text-slate-500')
            self.previous=ui.button(page_text('previous'),icon='chevron_right' if language()=='ar' else 'chevron_left',on_click=lambda:self.move(-1)).props('flat dense no-caps')
            self.next=ui.button(page_text('next'),icon='chevron_left' if language()=='ar' else 'chevron_right',on_click=lambda:self.move(1)).props('flat dense no-caps')
        self.previous.disable();self.next.disable();self.size_control.on_value_change(self.resize)

    async def move(self,delta):
        self.page=max(1,self.page+delta);await self.load()

    async def resize(self,event):
        self.size=int(event.value);self.page=1;await self.load()

    async def load(self):
        with self.client:
            if not self.active() or self.entries._deleted:return
            self.revision+=1;revision=self.revision
            self.status.text=text('loading')
            try:
                result=await self.review.api.disposition_page(f"jobs/{self.review.job['id']}/review-history/proposal/{self.identity}",limit=self.size,offset=(self.page-1)*self.size)
            except asyncio.CancelledError:return
            except ApiError as error:
                if revision==self.revision and self.active() and not self.entries._deleted:
                    self.entries.clear();self.status.text=self.review.on_error(error);self.count.text='';self.previous.disable();self.next.disable()
                return
            if revision!=self.revision or not self.active() or self.entries._deleted:return
            last=max(1,(result['total']+self.size-1)//self.size)
            if self.page>last:self.page=last;await self.load();return
            self.entries.clear()
            with self.entries:
                for row in result['items']:self.entry(row)
            self.status.text='' if result['total'] else text('empty')
            self.count.text=page_text('page_count',first=(self.page-1)*self.size+1 if result['total'] else 0,last=min(self.page*self.size,result['total']),total=result['total'])
            self.previous.set_enabled(self.page>1);self.next.set_enabled(self.page<last)

    def entry(self,row):
        caption=' · '.join(v for v in (self.review.format_timestamp(row['occurred_at']),row.get('actor_name')) if v)
        with ui.expansion(event_label(row['operation'],event=row),caption=caption,icon='history',value=False).classes('w-full rounded-lg border border-slate-200') as entry:
            content=ui.column().classes('w-full min-w-0 gap-3 p-3')
        built=False
        def opened(event):
            nonlocal built
            if not event.value or built or not self.active():return
            built=True
            with content:
                metadata=row.get('metadata') or {}
                after=row.get('after_state') or metadata.get('after') or {}
                reason=after.get('withdrawal_reason') or after.get('reason') or row.get('reason')
                if reason and not metadata.get('redacted'):field('proposal_reason',reason)
                from .history import readable_event_fields
                changes=revision_changes(row,self.review.format_timestamp)
                if changes:
                    for label,before,after in changes:
                        ui.label(label).classes('font-semibold')
                        fields([('revision_before',before),('revision_after',after)])
                    with ui.expansion(text('recorded_information'),icon='info',value=False).classes('w-full'):
                        if row.get('reason') and row['reason']!=reason:field('reason',row['reason'])
                        readable_event_fields(row,self.review.format_timestamp)
                else:readable_event_fields(row,self.review.format_timestamp)
                if row.get('can_view_technical_details'):
                    with ui.expansion(text('history_technical'),icon='code',value=False).classes('w-full'):
                        ui.code(json.dumps({k:v for k,v in row.items() if k not in ('display_references','can_view_technical_details')},ensure_ascii=False,indent=2,default=str),language='json').classes('w-full')
        entry.on_value_change(opened)


async def show(review,row):
    if not row or row.get('redacted') and not row.get('partial'):return
    partial=row.get('partial')
    facts=row.get('current_values') or {}
    target=row.get('target_summary') if partial else facts.get('record') or facts
    identity=' · '.join(str(v) for v in (target.get('number') or target.get('record_number') or target.get('aggregation_number'),target.get('title')) if v)
    with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-full p-0 gap-0 flex-nowrap').style('width: 760px; max-width: calc(100vw - 32px); max-height: calc(100dvh - 48px)'):
        with ui.column().classes('w-full p-5 gap-2 shrink-0'):
            with ui.row().classes('w-full items-center justify-between gap-2'):
                ui.label(text(row['proposal_type'])).classes('text-xl font-semibold')
                ui.badge(text(row['proposal_state'])).props('outline')
            ui.label(identity).props('dir=auto').classes('font-medium whitespace-pre-wrap break-words')
        with ui.tabs(value='details').props('no-caps').classes('w-full shrink-0') as tabs:
            ui.tab('details',label=text('proposal_details_tab')).props('no-caps')
            if not partial:ui.tab('history',label=text('revision_history')).props('no-caps')
        def alive():return review.alive() and dialog.value and not dialog._deleted
        with ui.tab_panels(tabs,value='details',keep_alive=True).classes('w-full min-h-0 overflow-y-auto'):
            with ui.tab_panel('details').classes('w-full p-5 gap-4'):
                if partial:
                    ui.label(text('restricted_proposal_details')).props('role=status').classes('text-amber-900')
                    ui.label(text('restricted_text')).classes('text-sm text-slate-600')
                else:
                    comparison(row)
                    field('proposal_reason',row.get('reason'))
                    if row['proposal_state']=='withdrawn':field('withdrawal_comment',row.get('withdrawal_reason'))
                    if row.get('executed_at') or row['proposal_state'] in ('executed','failed'):
                        ui.label(text('execution_result')).classes('font-semibold')
                        field('proposal_state',text(row['proposal_state']))
                        if row.get('executed_at'):field('history_executed_at',review.format_timestamp(row['executed_at']))
                information(row,review.format_timestamp)
            if not partial:
                with ui.tab_panel('history').classes('w-full p-5 gap-3'):
                    history=ProposalRevisions(review,row['id'],lambda:alive() and tabs.value=='history')
        async def selected(event):
            if not partial and event.value=='history' and alive():await history.load()
        tabs.on_value_change(selected)
        ui.separator()
        with ui.row().classes('w-full justify-end p-3 shrink-0'):
            ui.button(text('close'),on_click=dialog.close).props('flat no-caps')
    dialog.open()
