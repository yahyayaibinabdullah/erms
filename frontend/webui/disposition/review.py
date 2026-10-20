"""Destruction review forms with explicit atomic Save and optimistic versions.

Draft changes belong only to this mounted task. Mutations retain an exact-payload
retry UUID. No operational, reference or cross-identity result cache is added.
"""
import asyncio
import json
from html import escape
from uuid import uuid4
from nicegui import ui
from ..api_client import ApiError
from ..remote_select import RemoteSelect
from ..resource_relationships import PageTable
from .messages import text,KEYS
from .screens import column,failure

PROPOSAL_TYPES=('remove_from_job','make_vital','blocking_security','add_to_holds','create_aggregation_relationship','remove_aggregation_relationship','remove_record_relationship','local_retention_override')


def workflow_panel(job):
    from .process import process_diagram
    process_diagram(job)


class ReviewForm:
    def __init__(self,*,api,workspace,active,on_error,bind_remote,after,format_timestamp,open_resource,preview=None):
        self.api,self.view,self.active,self.on_error=api,workspace,active,on_error
        self.bind_remote,self.after,self.format_timestamp=bind_remote,after,format_timestamp
        self.open_resource=open_resource
        self.preview=preview
        self.job=workspace['job'];self.task=workspace['task'];self.actions=set(workspace['actions'])
        self.pending=[];self.pending_meta={};self.retry={};self.busy=False;self.proposal_filter=None;self.proposal_round=None
        self.work=None;self.note=None;self.overall=None
        self.roles={r['id']:r['name'] for r in workspace['roles']}
        self.host=ui.column().classes('w-full gap-4')
        with self.host:
            ui.label(text('current_task')).classes('text-lg font-semibold')
            self.feedback=ui.label('').props('role=alert').classes('text-negative')
            if not self.task:
                ui.label(text('no_current_task')).props('role=status');return
            form_key={'certificate_generation':'certificate_download','physical_destruction':'physical_destruction','digital_destruction':'digital_destruction','external_approval_pending':'external_form','file_administrator_review':'form_file_review','unit_manager_review':'form_unit_review','records_manager_review':'form_manager_review','officer_correction':'correction','manager_correction':'correction','manager_preparation':'form_manager_review'}.get(self.job['workflow_stage'],'preparation')
            ui.label(text(form_key)).classes('font-semibold')
            hint='disposition_physical_release_pending' if self.task['task_type'] in ('physical_destruction','digital_destruction') else 'external_hint' if self.task['task_type']=='external_approval' else 'correction_hint' if 'correction' in self.job['workflow_stage'] else 'manager_hint' if 'approve' in self.actions else 'prepare_hint' if 'submit' in self.actions else 'review_hint'
            if self.task['task_type']=='digital_destruction':hint='disposition_digital_confirmation_required' if (workspace.get('destruction') or {}).get('released') else 'disposition_digital_release_pending'
            if self.task['task_type']=='digital_destruction' and ((workspace.get('destruction') or {}).get('progress') or {}).get('state')=='succeeded':hint='digital_done_completion_pending'
            if self.task['task_type']=='certificate_download':hint='certificate_download_hint'
            ui.label(text(hint)).classes('text-sm text-slate-600')
            for key in ('direct_assignee','role_queue','claimant'):
                ui.label(text(key)+' · '+(self.task.get(key) or '—')).props('dir=auto')
            self.role=ui.select(self.roles,label=text('acting_task_role'),value=next(iter(self.roles),None)).props('outlined dense').classes('w-full')
            self.role.set_visibility(bool(self.roles))
            if 'claim' in self.actions:ui.button(text('claim'),icon='assignment_ind',on_click=lambda:self.queue_action('claim')).props('no-caps')
            if 'reassign' in self.actions:ui.button(text('reassign'),icon='person_add',on_click=self.reassign).props('outline no-caps')
            if 'release' in self.actions:ui.button(text('release'),icon='undo',on_click=lambda:self.queue_action('release')).props('outline no-caps')
            self.body=ui.column().classes('w-full gap-4')

    def alive(self):return self.active() and not self.host._deleted

    def dirty(self):
        return self.busy or self.has_changes()

    def has_changes(self):
        return bool(self.pending) or self.note is not None and self.work is not None and (str(self.note.value or '')!=str((self.work.get('own_notes') or {}).get('review_notes') or '') or self.overall is not None and str(self.overall.value or '')!=str(self.work.get('overall_reason') or ''))

    def error(self,error):
        if self.alive():
            self.feedback.text=failure(error,self.on_error);ui.notify(self.feedback.text,type='negative')

    async def queue_action(self,action):
        from .screens import command_dialog
        if self.dirty():ui.notify(text('unsaved_warning'),type='warning');return
        await command_dialog(api=self.api,context={'roles':list({r['id']:r for r in self.view['roles']+self.view.get('task_management_roles',[])}.values())},active=self.alive,on_error=self.on_error,title=action,build=lambda active:lambda:{},path=f"tasks/{self.task['id']}/{action}",version=self.task['version'],after=self.after)

    async def load(self):
        from .external import request_controls,task_form
        request_controls(self)
        from .physical import controls as physical_controls,task_form as physical_task_form
        physical_controls(self)
        from .destruction import controls as destruction_controls
        destruction_controls(self)
        from .email import controls as email_controls
        email_controls(self)
        from .completion import controls as completion_controls
        completion_controls(self)
        if not self.task or not self.roles:
            with self.host:
                self.history_sections()
                await self.proposals_panel()
            return
        if self.task.get('task_type')=='certificate_download':
            self.history_sections()
            return
        if self.task.get('task_type')=='digital_destruction':return
        if self.task.get('task_type')=='physical_destruction':
            await physical_task_form(self)
            return
        if self.task.get('task_type')=='external_approval':
            await task_form(self)
            return
        try:work=await self.api.disposition_page(f"tasks/{self.task['id']}/review-work")
        except ApiError as error:self.error(error);return
        if not self.alive():return
        self.work=work
        with self.body:
            if work.get('submission_reason'):
                ui.label(text('overall_reason')).classes('font-semibold');ui.label(work['submission_reason']).props('dir=auto').classes('whitespace-pre-wrap')
            if 'save' in self.actions:
                self.proposal_host=ui.column().classes('w-full gap-3')
                ui.label(text('review_notes')).classes('font-semibold')
                self.note=ui.textarea(text('review_notes'),value=(work.get('own_notes') or {}).get('review_notes','')).props('outlined autogrow').classes('w-full')
                if 'submit' in self.actions or self.job['review_route']=='records_manager_only':
                    self.overall=ui.textarea(text('overall_reason'),value=work.get('overall_reason') or '').props('outlined autogrow').classes('w-full')
                ui.label(text('save_hint')).classes('text-sm text-slate-600')
                self.pending_label=ui.label('').props('role=status')
                self.pending_host=ui.column().classes('w-full gap-2')
                self.decision=ui.textarea(text('decision_reason')).props('outlined autogrow').classes('w-full') if 'reject' in self.actions else None
                self.buttons=[]
                with ui.row().classes('w-full gap-2 flex-wrap'):
                    for action in ('save','submit','complete_review','reject','approve'):
                        if action in self.actions:
                            label='approve_generate_request' if action=='approve' and self.job['review_route']=='records_manager_only' else action
                            self.buttons.append(ui.button(text(label),icon={'save':'save','submit':'send','complete_review':'done','reject':'assignment_return','approve':'verified'}[action],on_click=lambda _,a=action:self.perform(a)).props('no-caps'+(' outline' if action=='reject' else '')))
            self.history_sections()
            await self.proposals_panel(host=self.proposal_host if 'save' in self.actions else None)

    async def send(self,path,payload,version):
        payload={**payload,'acting_role_id':self.role.value}
        signature=json.dumps([path,payload,version],sort_keys=True)
        identity=self.retry.setdefault(signature,str(uuid4()))
        return await self.api.disposition_command(path,{**payload,'command_id':identity,'acting_role_id':self.role.value},version=version,reason=text('save'))

    async def persist(self):
        if not self.has_changes():return
        payload={'task_version':self.work['task_version'],'changes':self.pending,'review_notes':self.note.value or '',
                 'note_version':(self.work.get('own_notes') or {}).get('version',0)}
        if self.overall is not None:payload['overall_reason']=self.overall.value or ''
        result=await self.send(f"tasks/{self.task['id']}/review-work",payload,self.work['job_version'])
        if not self.alive():return result
        self.work.update(job_version=result['job_version'],task_version=result['task_version'],overall_reason=self.overall.value if self.overall is not None else self.work.get('overall_reason'),own_notes={'version':result['note_version'],'review_notes':self.note.value or ''})
        self.job['version']=result['job_version'];self.task['version']=result['task_version']
        self.pending.clear();self.pending_meta.clear();self.render_pending()
        return result

    async def perform(self,action):
        if not self.alive() or self.busy or action not in self.actions:return
        if action in ('submit','approve') and self.overall is not None and not str(self.overall.value or '').strip():
            ui.notify(text('disposition_submission_reason_required'),type='warning');self.overall.run_method('focus');return
        controls=self.buttons+[c for c in (self.note,self.overall,self.decision,self.role) if c is not None]
        self.busy=True;self.feedback.text=''
        for control in controls:control.disable()
        saved=False
        try:
            if action=='approve':
                with ui.dialog() as dialog,ui.card().classes('messaging-workspace max-w-full gap-4'):
                    ui.label(text('approval_confirm'))
                    with ui.row():
                        ui.button(text('cancel'),on_click=lambda:dialog.submit(False)).props('flat no-caps')
                        ui.button(text('continue'),on_click=lambda:dialog.submit(True)).props('no-caps')
                if not await dialog or not self.alive():return
            saved=await self.persist() is not None
            if not self.alive():return
            payload={'task_version':self.work['task_version']}
            if action=='save':
                await asyncio.gather(self.proposals.load(),*( [self.notes.load()] if hasattr(self,'notes') else []))
                if not self.alive():return
                ui.notify(text('saved'),type='positive');await self.after({'_saved_work':True,'job_version':self.work['job_version']});return
            if action=='submit':payload['overall_reason']=self.overall.value;endpoint='submit-review'
            elif action in ('complete_review','reject'):
                payload.update(decision='rejected' if action=='reject' else 'approved',decision_reason=(self.decision.value or '') if self.decision else '');endpoint='review-decision'
            else:
                preview=await self.api.disposition_page(f"tasks/{self.task['id']}/approval-preview",acting_role_id=self.role.value)
                if not self.alive():return
                if preview['job_version']!=self.work['job_version'] or preview['task_version']!=self.work['task_version']:
                    raise ApiError(409,{'code':'disposition_stale_version'})
                payload.update(membership_token=preview['membership_token'],proposals_token=preview['proposals_token'],overall_reason=self.overall.value if self.overall is not None else None);endpoint='approve-proposals'
            result=await self.send(f"tasks/{self.task['id']}/{endpoint}",payload,self.work['job_version'])
            if not self.alive():return
            pending=result.get('request_status')=='pending' or result.get('report_status')=='pending'
            ui.notify(text('request_pending' if result.get('request_status')=='pending' else 'report_pending' if pending else 'saved'),type='warning' if pending else 'positive')
            await self.after(result)
        except ApiError as error:
            if not self.alive():return
            if isinstance(error.detail,dict) and error.detail.get('approval_committed'):
                ui.notify(text('report_pending'),type='warning');await self.after(error.detail)
            else:
                self.error(error)
                if saved:
                    ui.notify(text('decision_failed_saved'),type='warning')
                    await asyncio.gather(self.proposals.load(),*( [self.notes.load()] if hasattr(self,'notes') else []))
                    if self.alive():await self.after({'_saved_work':True,'job_version':self.work['job_version']})
        finally:
            self.busy=False
            if self.alive():
                for control in controls:control.enable()

    def remote(self,kind,label,*,target=False,root=None,multiple=False,selected=None,active=None):
        control=RemoteSelect({},label=text(label),with_input=True,multiple=multiple,value=[] if multiple else None).props('outlined dense clearable').classes('w-full')
        base=f"tasks/{self.task['id']}/"+('proposal-targets/' if target else 'review-candidates/')+kind
        async def request(**params):return await self.api.disposition_page(base,acting_role_id=self.role.value,**({'root_id':root} if target else {}),**params)
        async def load(query):return await request(query=query)
        async def hydrate(identity):
            response=await request(selected=identity)
            if not response['items']:raise ApiError(404,{'code':'disposition_resource_access_required'})
            return response['items'][0]
        self.bind_remote(control,'aggregations',('code','name'),('code','name'),page_loader=load,selected_loader=hydrate,min_query_length=2,active=active or self.alive)
        if selected:
            control.options={r['id']:r.get('name') or r.get('code') or str(r['id']) for r in selected}
            control.value=[r['id'] for r in selected] if multiple else selected[0]['id'];control.update()
        return control

    async def proposals_panel(self,root_id=None,host=None,active=None):
        with host or self.host:
            ui.separator();ui.label(text('proposals')).classes('text-lg font-semibold')
            async def fetch(p):
                result=await self.api.disposition_page(f"jobs/{self.job['id']}/proposals",limit=p.size,offset=(p.page-1)*p.size,review_round=self.proposal_round,root_id=root_id)
                for row in result['items']:
                    if row['redacted']:row.update(target_label=text('restricted'),type_label='—',state_label='—');continue
                    a=row['current_values'].get('record') or row['current_values']
                    row['target_label']=(a.get('record_number') or a.get('aggregation_number') or str(row['target_aggregation_id']))+' · '+(a.get('title') or '')
                    row['editor_time_label']=self.format_timestamp(row['last_revised_at']) if row.get('last_revised_at') else '—'
                    row['stage_label']=text(row['proposer_stage'])
                    row['type_label']=text(row['proposal_type']);row['state_label']=text(row['proposal_state']);row['time_label']=self.format_timestamp(row['proposed_at'])
                    row['editable']='propose' in self.actions and self.work is not None and row['review_round']==self.work['review_round'] and row['proposal_state']=='active' and row['in_current_membership']
                return result
            page=PageTable(columns=[column('target_label','target'),column('type_label','proposal_type'),column('state_label','proposal_state'),column('proposer_name','proposer'),column('proposer_role_name','acting_task_role'),column('editor_name','last_editor'),column('editor_time_label','occurred'),column('stage_label','stage'),column('review_round'),column('time_label','occurred'),column('reason'),column('actions')],fetch=fetch,active=active or self.alive,on_error=self.on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
            page.table.add_slot('body-cell-actions','''<q-td :props="props"><q-btn v-if="!props.row.redacted" flat dense icon="info" aria-label="'''+escape(text('details'))+'''" @click="$parent.$emit('detail',props.row.id)"/><q-btn v-if="props.row.editable" flat dense icon="edit" aria-label="'''+escape(text('revise'))+'''" @click="$parent.$emit('revise',props.row.id)"/><q-btn v-if="props.row.editable" flat dense icon="undo" aria-label="'''+escape(text('withdraw'))+'''" @click="$parent.$emit('withdraw',props.row.id)"/></q-td>''')
            def row(event):return next((r for r in page.table.rows if r['id']==event.args),None)
            page.table.on('detail',lambda event:self.details(row(event)))
            page.table.on('revise',lambda event:self.edit(existing=row(event)))
            page.table.on('withdraw',lambda event:self.withdraw(row(event)))
            if root_id is None:self.proposals=page
            await page.load()

    async def notes_panel(self,host=None,active=None):
        with host or self.host:
            ui.separator();ui.label(text('review_notes')).classes('text-lg font-semibold')
            async def fetch(p):
                result=await self.api.disposition_page(f"jobs/{self.job['id']}/review-notes",limit=p.size,offset=(p.page-1)*p.size)
                for row in result['items']:
                    if row.get('redacted'):row.update(review_notes=text('restricted'));continue
                    row['stage_label']=text(row['workflow_stage']);row['time_label']=self.format_timestamp(row['date_updated'])
                return result
            page=PageTable(columns=[column('review_round'),column('stage_label','stage'),column('author_name','actor'),column('role_name','acting_task_role'),column('review_notes'),column('time_label','occurred'),column('actions')],fetch=fetch,active=active or self.alive,on_error=self.on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
            page.table.add_slot('body-cell-actions','''<q-td :props="props"><q-btn v-if="!props.row.redacted" flat dense icon="history" aria-label="'''+escape(text('revision_history'))+'''" @click="$parent.$emit('note-history',props.row.id)"/></q-td>''')
            page.table.on('note-history',lambda event:self.history('note',event.args))
            self.notes=page
            return page

    def queued(self,change,summary=None):
        if self.busy:return
        if change.get('proposal_id'):
            self.pending[:]=[c for c in self.pending if c.get('proposal_id')!=change['proposal_id']]
        self.pending.append(change);self.pending_meta[id(change)]=summary or {};self.render_pending()
        ui.notify(text('draft_added'),type='info')

    def render_pending(self):
        self.pending_label.text=text('pending_changes')+' · '+str(len(self.pending)) if self.pending else ''
        self.pending_host.clear()
        with self.pending_host:
            for change in self.pending:
                with ui.card().classes('w-full gap-2 p-3'):
                    ui.label(text(change.get('proposal_type') or ('withdraw' if change['action']=='withdraw' else 'revise')))
                    for key,value in self.pending_meta.get(id(change),{}).items():ui.label(text(key)+' · '+str(value or '—')).props('dir=auto')
                    if change.get('reason'):ui.label(text('reason')+' · '+change['reason']).props('dir=auto')
                    def discard(item=change):self.pending.remove(item);self.render_pending()
                    ui.button(text('cancel'),icon='close',on_click=discard).props('flat dense no-caps')

    async def withdraw(self,row):
        if self.busy or not row or not row.get('editable'):return
        with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[600px] max-w-full gap-4'):
            ui.label(text('withdraw'));reason=ui.textarea(text('reason')).props('outlined autogrow').classes('w-full')
            def accept():self.queued(dict(action='withdraw',proposal_id=row['id'],expected_version=row['version'],reason=reason.value or None));dialog.close()
            ui.button(text('withdraw'),on_click=accept).props('no-caps');ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
        dialog.open()

    async def details(self,row):
        if not row or row.get('redacted'):return
        with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[900px] max-w-full gap-4'):
            ui.label(text(row['proposal_type'])).classes('text-xl font-semibold')
            for label,value in [('proposer',row.get('proposer_name')),('role',row.get('proposer_role_name')),('stage',text(row['proposer_stage'])),('review_round',row['review_round']),('occurred',self.format_timestamp(row['proposed_at'])),('last_editor',row.get('editor_name')),('reason',row.get('reason'))]:
                ui.label(text(label)+' · '+str(value or '—')).props('dir=auto')
            facts=row['current_values'];proposed=row['proposed_values']
            def line(key,value):ui.label(text(key)+' · '+str(value if value is not None else '—')).props('dir=auto').classes('whitespace-pre-wrap')
            def rule(value):
                value=value or {}
                for key in ('current_period_years','intermediate_period_years','instructions'):line(key,value.get(key))
                actions={'destruction':'destruction','transfer_to_external_archive':'permanent_transfer','selective_preservation':'selective_transfer','retain_as_local_archives':'local_archives'}
                line('final_disposition',text(actions[value['final_disposition']]) if value.get('final_disposition') in actions else '—')
            ui.label(text('current_values')).classes('font-semibold')
            line('aggregation',(facts.get('aggregation_number') or '')+' · '+(facts.get('title') or ''))
            if facts.get('record'):line('record',facts['record']['record_number']+' · '+facts['record']['title'])
            line('vital',text('yes' if facts.get('is_vital') else 'no'));line('security_level_id',row.get('current_security_name'))
            if facts.get('relationship'):
                line('relationship_type_id',row.get('relationship_type_name'))
                line('target',(row.get('relationship_source_label') or '—')+' → '+(row.get('relationship_target_label') or '—'))
            if row['proposal_type']=='local_retention_override':
                ui.label(text('local_override')).classes('font-semibold');rule(facts.get('local_retention'))
                ui.label(text('classification')).classes('font-semibold');rule(facts.get('classification_rule'))
            ui.label(text('proposed_values')).classes('font-semibold')
            typ=row['proposal_type']
            if typ=='local_retention_override':rule(proposed)
            elif typ=='make_vital':line('vital',text('yes'))
            elif typ=='blocking_security':line('security_level_id',(facts.get('proposed_security') or {}).get('name'))
            elif typ=='add_to_holds':
                for hold in facts.get('holds',[]):line('hold_ids',hold['code']+' · '+hold['name'])
            elif typ=='create_aggregation_relationship':
                related=facts.get('related') or {};line('related_aggregation_id',(related.get('aggregation_number') or '')+' · '+(related.get('title') or ''))
                line('direction',text(proposed['direction']));line('relationship_type_id',row.get('relationship_type_name'))
            else:ui.label(text(typ))
            ui.label(text('execution_result')).classes('font-semibold');line('proposal_state',text(row['proposal_state']))
            if row.get('executed_at'):line('occurred',self.format_timestamp(row['executed_at']))
            ui.button(text('revision_history'),icon='history',on_click=lambda:self.history('proposal',row['id'])).props('outline no-caps')
            ui.button(text('close'),on_click=dialog.close).props('flat no-caps')
        dialog.open()

    async def edit(self,root=None,existing=None):
        if self.busy or 'propose' not in self.actions or existing and not existing.get('editable'):return
        if existing:
            pending=next((c for c in self.pending if c.get('proposal_id')==existing['id']),None)
            if pending and pending['action']=='revise':existing={**existing,**{k:pending[k] for k in ('proposed_values','reason')}}
        root_id=existing['governing_root_id'] if existing else root['root_aggregation_id']
        with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[800px] max-w-full gap-4'):
            def alive():return self.alive() and dialog.value and not dialog._deleted
            ui.label(text('revise' if existing else 'propose')).classes('text-xl font-semibold')
            kind=ui.select({k:text(k) for k in PROPOSAL_TYPES},value=existing['proposal_type'] if existing else 'make_vital',label=text('proposal_type')).props('outlined dense').classes('w-full')
            if existing:kind.disable()
            fields=ui.column().classes('w-full gap-3');values={};target={};generation=[0]
            feedback=ui.label('').props('role=alert').classes('text-negative')
            async def build():
                generation[0]+=1;token=generation[0];fields.clear();values.clear();target.clear()
                typ=kind.value;initial=existing['proposed_values'] if existing else {}
                selected_id=existing.get('target_record_id') or existing['target_aggregation_id'] if existing else root_id
                with fields:
                    if typ in ('remove_from_job','local_retention_override'):
                        response=await self.api.disposition_page(f"tasks/{self.task['id']}/proposal-targets/aggregations",root_id=root_id,acting_role_id=self.role.value,selected=root_id)
                        if not alive() or token!=generation[0]:return
                        target.update(response['items'][0]);ui.label(target['code']+' · '+target['name']).props('dir=auto')
                    else:
                        target_kind='records' if typ=='remove_record_relationship' else 'aggregations'
                        selected=[]
                        if existing or target_kind=='aggregations':
                            response=await self.api.disposition_page(f"tasks/{self.task['id']}/proposal-targets/{target_kind}",root_id=root_id,acting_role_id=self.role.value,selected=selected_id)
                            if not alive() or token!=generation[0]:return
                            selected=response['items'];target.update(selected[0] if selected else {})
                        control=self.remote(target_kind,'target',target=True,root=root_id,selected=selected,active=alive)
                        async def changed():
                            target.clear()
                            if not control.value or control._deleted:return
                            selected_id=control.value
                            result=await self.api.disposition_page(f"tasks/{self.task['id']}/proposal-targets/{target_kind}",root_id=root_id,acting_role_id=self.role.value,selected=control.value)
                            if alive() and token==generation[0] and not control._deleted and control.value==selected_id and result['items']:
                                target.update(result['items'][0])
                                if 'links' in values:await values['links'].load(reset=True)
                        if existing:control.disable()
                        control.on_value_change(changed)
                    if typ=='blocking_security':
                        values['security']=self.remote('security_levels','security_level_id',selected=[{'id':initial['security_level_id'],'name':(existing.get('current_values',{}).get('proposed_security') or {}).get('name') or str(initial['security_level_id'])}] if initial else None,active=alive)
                    elif typ=='add_to_holds':
                        values['holds']=self.remote('holds','hold_ids',multiple=True,selected=(existing.get('current_values',{}).get('holds') or []) if existing else None,active=alive)
                        if existing and not values['holds'].value:
                            # Hydrate only the selected IDs, never the complete holds collection.
                            rows=await asyncio.gather(*(self.api.disposition_page(f"tasks/{self.task['id']}/review-candidates/holds",acting_role_id=self.role.value,selected=i) for i in initial['hold_ids']))
                            if not alive():return
                            selected=[r['items'][0] for r in rows if r['items']]
                            values['holds'].options={r['id']:r['code']+' · '+r['name'] for r in selected};values['holds'].value=initial['hold_ids'];values['holds'].update()
                    elif typ=='create_aggregation_relationship':
                        values['direction']=ui.select({v:text(v) for v in ('outgoing','incoming')},value=initial.get('direction','outgoing'),label=text('direction')).props('outlined dense').classes('w-full')
                        values['related']=self.remote('aggregations','related_aggregation_id',active=alive)
                        values['type']=self.remote('relationship_types','relationship_type_id',active=alive)
                        if existing:
                            for key,remote_key,id_key in [('related','aggregations','related_aggregation_id'),('type','relationship_types','relationship_type_id')]:
                                result=await self.api.disposition_page(f"tasks/{self.task['id']}/review-candidates/{remote_key}",acting_role_id=self.role.value,selected=initial[id_key])
                                if not alive():return
                                values[key].options={r['id']:r['code']+' · '+r['name'] for r in result['items']};values[key].value=initial[id_key];values[key].update()
                    elif typ in ('remove_aggregation_relationship','remove_record_relationship'):
                        async def fetch(p):
                            if not target:return {'items':[],'total':0}
                            singular='record' if typ=='remove_record_relationship' else 'aggregation'
                            result=await self.api.request('GET',f"/api/v1/relationships/{singular}/{target['id']}",params={'limit':p.size,'offset':(p.page-1)*p.size})
                            for row in result['items']:
                                related=row['related'];row['target_label']=text('restricted') if related['redacted'] else related['number']+' · '+related['title']
                            return result
                        page=PageTable(columns=[column('label','relationship_type_id'),column('target_label','target')],fetch=fetch,active=alive,on_error=self.on_error,empty='empty',selection='single',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
                        values['links']=page;await page.load()
                        if existing:
                            singular='record' if typ=='remove_record_relationship' else 'aggregation'
                            response=await self.api.request('GET',f"/api/v1/relationships/{singular}/{target['id']}",params={'selected_id':initial['relationship_id'],'limit':1,'offset':0})
                            if not alive():return
                            chosen=[r for r in response['items'] if not r['related']['redacted']]
                            page.table.selected=chosen
                            if chosen:ui.label(text('relationship_id')+' · '+chosen[0]['label']+' · '+chosen[0]['related']['number']+' · '+chosen[0]['related']['title']).props('dir=auto')
                    elif typ=='local_retention_override':
                        for key in ('current_period_years','intermediate_period_years'):
                            values[key]=ui.number(text(key),value=initial.get(key,0),min=0,step=1,precision=0).props('outlined dense').classes('w-full')
                        actions={'destruction':'destruction','transfer_to_external_archive':'permanent_transfer','selective_preservation':'selective_transfer','retain_as_local_archives':'local_archives'}
                        values['final_disposition']=ui.select({k:text(v) for k,v in actions.items()},label=text('final_disposition'),value=initial.get('final_disposition','destruction')).props('outlined dense').classes('w-full')
                        values['instructions']=ui.textarea(text('instructions'),value=initial.get('instructions') or '').props('outlined autogrow').classes('w-full')
                    values['reason']=ui.textarea(text('reason'),value=existing.get('reason') or '' if existing else '').props('outlined autogrow').classes('w-full')
            async def accept():
                if not alive():return
                if not target:feedback.text=text('required');ui.notify(feedback.text,type='warning');return
                typ=kind.value;proposed={};reason=values['reason'].value or None
                if typ=='remove_from_job' and not str(reason or '').strip():feedback.text=text('required');ui.notify(feedback.text,type='warning');return
                if typ=='blocking_security':proposed={'security_level_id':values['security'].value}
                elif typ=='add_to_holds':proposed={'hold_ids':values['holds'].value}
                elif typ=='create_aggregation_relationship':proposed={'direction':values['direction'].value,'related_aggregation_id':values['related'].value,'relationship_type_id':values['type'].value}
                elif typ.startswith('remove_') and typ!='remove_from_job':
                    selected=values['links'].table.selected
                    if not selected or selected[0]['related']['redacted']:feedback.text=text('required');return
                    proposed={'relationship_id':selected[0]['id']}
                elif typ=='local_retention_override':
                    if any(values[k].value is None or values[k].value<0 or int(values[k].value)!=values[k].value for k in ('current_period_years','intermediate_period_years')):feedback.text=text('required');return
                    proposed={k:int(values[k].value) for k in ('current_period_years','intermediate_period_years')};proposed.update(final_disposition=values['final_disposition'].value,instructions=values['instructions'].value or None)
                if any(v is None or v==[] for v in proposed.values()) and typ!='local_retention_override':feedback.text=text('required');return
                change=dict(action='revise' if existing else 'create',target_version=target['version'],proposed_values=proposed,reason=reason)
                if existing:change.update(proposal_id=existing['id'],expected_version=existing['version'])
                else:change.update(governing_root_id=root_id,target_aggregation_id=target['aggregation_id'],target_record_id=target['id'] if typ=='remove_record_relationship' else None,proposal_type=typ)
                summary={'target':target['code']+' · '+target['name']}
                if typ=='blocking_security':summary['security_level_id']=values['security'].options.get(values['security'].value)
                elif typ=='add_to_holds':summary['hold_ids']=' · '.join(values['holds'].options.get(i,str(i)) for i in values['holds'].value)
                elif typ=='create_aggregation_relationship':summary.update(direction=text(values['direction'].value),related_aggregation_id=values['related'].options.get(values['related'].value),relationship_type_id=values['type'].options.get(values['type'].value))
                elif typ=='local_retention_override':
                    summary.update({k:v for k,v in proposed.items() if k!='final_disposition'})
                    labels={'destruction':'destruction','transfer_to_external_archive':'permanent_transfer','selective_preservation':'selective_transfer','retain_as_local_archives':'local_archives'}
                    summary['final_disposition']=text(labels[proposed['final_disposition']])
                self.queued(change,summary);dialog.close()
            with ui.row().classes('w-full gap-2 justify-end'):
                ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
                ui.button(text('continue'),on_click=accept).props('no-caps')
            kind.on_value_change(build)
        dialog.open()
        try:await build()
        except ApiError as error:
            if alive():feedback.text=failure(error,self.on_error)

    async def rounds_panel(self,host=None,active=None):
        with host or self.host:
            ui.separator();ui.label(text('round_history')).classes('text-lg font-semibold')
            managers=[r for r in self.view.get('management_roles',[]) if r.get('profile_code')=='INFO_GOV_MGR']
            async def fetch(p):
                result=await self.api.disposition_page(f"jobs/{self.job['id']}/review-rounds",summary=True,limit=p.size,offset=(p.page-1)*p.size)
                for row in result['items']:
                    row['time_label']=self.format_timestamp(row['started_at']) if not row.get('redacted') else '—'
                    row['can_retry']=bool(managers) and row.get('approved',False)
                return result
            page=PageTable(columns=[column('round_number','review_round'),column('time_label','occurred'),column('submission_reason','overall_reason'),column('invalidation_reason','reason'),column('root_count'),column('actions')],fetch=fetch,active=active or self.alive,on_error=self.on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
            page.table.add_slot('body-cell-actions','''<q-td :props="props"><q-btn v-if="!props.row.redacted" flat dense icon="history" aria-label="'''+escape(text('proposals'))+'''" @click="$parent.$emit('round',props.row.id)"/><q-btn v-if="props.row.can_retry" flat dense icon="description" aria-label="'''+escape(text('retry_report'))+'''" @click="$parent.$emit('report',props.row.id)"/></q-td>''')
            async def show(event):
                row=next((r for r in page.table.rows if r['id']==event.args and not r.get('redacted')),None)
                if row:self.proposal_round=row['round_number'];await self.proposals.load(reset=True)
            async def report(event):
                row=next((r for r in page.table.rows if r['id']==event.args and r.get('can_retry')),None)
                if not row:return
                with ui.dialog() as dialog,ui.card().classes('messaging-workspace max-w-full gap-4'):
                    ui.label(text('retry_report'))
                    role=ui.select({r['id']:r['name'] for r in managers},label=text('acting_task_role'),value=managers[0]['id']).props('outlined dense')
                    feedback=ui.label('').props('role=alert').classes('text-negative')
                    identity=str(uuid4())
                    async def generate():
                        button.disable()
                        try:result=await self.api.disposition_command(f"jobs/{self.job['id']}/review-rounds/{row['id']}/execution-report",{'command_id':identity,'acting_role_id':role.value},reason=text('retry_report'))
                        except ApiError as error:
                            if self.alive() and dialog.value:feedback.text=failure(error,self.on_error);ui.notify(feedback.text,type='negative');button.enable()
                            return
                        if not self.alive() or not dialog.value:return
                        dialog.close();ui.notify(text('report_pending' if result.get('report_status')=='pending' else 'report_ready'),type='warning' if result.get('report_status')=='pending' else 'positive');await self.after(result)
                    button=ui.button(text('retry_report'),on_click=generate).props('no-caps')
                    ui.button(text('close'),on_click=dialog.close).props('flat no-caps')
                dialog.open()
            page.table.on('round',show);page.table.on('report',report)
            return page

    async def history(self,kind,identity):
        from .history import revision_history
        await revision_history(api=self.api,job_id=self.job['id'],kind=kind,identity=identity,active=self.alive,on_error=self.on_error,format_timestamp=self.format_timestamp)

    async def reassign(self):
        if self.dirty():ui.notify(text('unsaved_warning'),type='warning');return
        from .task_assignment import reassign_task
        roles=list({r['id']:r for r in self.view['roles']+self.view.get('task_management_roles',[])}.values())
        await reassign_task(api=self.api,task=self.task,roles=roles,bind_remote=self.bind_remote,active=self.alive,on_error=self.on_error,after=self.after)

    async def decisions_panel(self,host=None,active=None):
        with host or self.host:
            ui.separator();ui.label(text('review_decisions')).classes('text-lg font-semibold')
            async def fetch(p):
                result=await self.api.disposition_page(f"jobs/{self.job['id']}/review-decisions",summary=True,limit=p.size,offset=(p.page-1)*p.size)
                for row in result['items']:
                    if row.get('redacted'):row['stage_label']=text('restricted');continue
                    row['stage_label']=text(row['review_stage']);row['decision_label']=text(row['decision']);row['time_label']=self.format_timestamp(row['decided_at'])
                return result
            page=PageTable(columns=[column('stage_label','stage'),column('actor_name','actor'),column('role_name','acting_task_role'),column('decision_label','review_decisions'),column('reason'),column('time_label','occurred')],fetch=fetch,active=active or self.alive,on_error=self.on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
            return page

    async def show_proposals(self,row):
        with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[1200px] max-w-full gap-4'):
            ui.label(row['identity']).classes('font-semibold').props('dir=auto')
            host=ui.column().classes('w-full gap-3')
            ui.button(text('close'),on_click=dialog.close).props('flat no-caps')
        dialog.open()
        await self.proposals_panel(root_id=row['root_aggregation_id'],host=host,active=lambda:self.alive() and dialog.value and not dialog._deleted)

    def history_sections(self):
        """Retained page controls, with fresh server data on every expansion."""
        with self.host:
            from .external import decisions_panel
            from .email import attempts_panel
            async def email_attempts(**kwargs):return await attempts_panel(self,**kwargs)
            async def external_decisions(**kwargs):return await decisions_panel(self,**kwargs)
            for label,method in [('review_notes',self.notes_panel),('round_history',self.rounds_panel),('review_decisions',self.decisions_panel),('external_decisions',external_decisions),('email_attempts',email_attempts)]:
                with ui.expansion(text(label),icon='history').classes('w-full') as expansion:
                    host=ui.column().classes('w-full gap-3');state={'page':None}
                def alive(expansion=expansion):return self.alive() and expansion.value and not expansion._deleted
                async def opened(event,method=method,host=host,state=state,alive=alive):
                    if not event.value or not alive():return
                    if state['page'] is None:state['page']=await method(host=host,active=alive)
                    await state['page'].load()
                expansion.on_value_change(opened)
