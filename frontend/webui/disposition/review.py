"""Destruction reviews with immediate proposal persistence and explicit comment Save.

Unconfirmed editor input and unsaved comments belong only to this mounted task. Mutations retain an exact-payload
retry UUID. No operational, reference or cross-identity result cache is added.
"""
import asyncio
import json
from html import escape
from uuid import uuid4
from types import SimpleNamespace
from nicegui import ui
from ..api_client import ApiError
from ..remote_select import RemoteSelect
from ..relationship_select import relationship_select
from ..resource_relationships import PageTable, language
from .acting_role import automatic_role
from .handoff import notify_completion,task_finished
from .messages import REVIEW_SETUP_ERRORS, text,KEYS
from .screens import column,failure

PROPOSAL_TYPES=('remove_from_job','make_vital','blocking_security','add_to_holds','create_aggregation_relationship','remove_aggregation_relationship','remove_record_relationship','local_retention_override')


def workflow_panel(job, **context):
    from .process import process_diagram
    process_diagram(job, **context)


class ReviewForm:
    def __init__(self,*,api,workspace,active,on_error,bind_remote,after,format_timestamp,open_resource,preview=None,browse_resource=None,history_host=None,documents_host=None,documents_active=None,history_active=None,on_submitted=None,on_approved=None,footer_host=None,task_active=None):
        # Historical callback name: all completed task stages now use this inbox return.
        self.on_submitted=on_submitted
        self.on_approved=on_approved
        self.api,self.view,self.active,self.on_error=api,workspace,active,on_error
        self.bind_remote,self.after,self.format_timestamp=bind_remote,after,format_timestamp
        self.open_resource=open_resource
        self.preview=preview
        self.browse_resource=browse_resource
        self.job=workspace['job'];self.task=workspace['task'];self.actions=set(workspace['actions'])
        self.review_blocked=any((self.job.get('review_setup') or {}).values())
        self.progress_buttons=[]
        self.pending_disclosures=[];self.proposal_pages=[];self.bulk_selections=[]
        self.retry={};self.busy=False;self.proposal_filter=None;self.proposal_round=None
        self.work=None;self.comments=None;self.saved_comments=''
        self.draft_controls=None;self.draft_buttons=[];self.footer_host=footer_host
        self.roles={r['id']:r['name'] for r in workspace['roles']}
        self.host=ui.column().classes('w-full gap-4')
        self.history_host=history_host or self.host
        self.documents_host=documents_host or self.host
        self.documents_active=documents_active or self.alive
        self.task_active=task_active or self.alive
        self.history_active=history_active or self.alive
        self.history_built=False
        self.history_refreshers=[]
        with self.host:
            ui.label(text('current_task')).classes('text-lg font-semibold')
            self.feedback=ui.label('').props('role=alert').classes('text-negative')
            if not self.task:
                ui.label(text('no_current_task')).props('role=status');return
            form_key={'certificate_generation':'certificate_final_task','physical_destruction':'physical_destruction','digital_destruction':'digital_destruction','external_approval_pending':'external_form','file_administrator_review':'form_file_review','unit_manager_review':'form_unit_review','records_manager_review':'form_manager_review','officer_correction':'correction','manager_correction':'correction','manager_preparation':'form_manager_review'}.get(self.job['workflow_stage'],'preparation')
            ui.label(text(form_key)).classes('font-semibold')
            hint='disposition_physical_required' if self.task['task_type'] in ('physical_destruction','digital_destruction') else 'external_hint' if self.task['task_type']=='external_approval' else 'correction_hint' if 'correction' in self.job['workflow_stage'] else 'manager_hint' if 'approve' in self.actions else 'preparation_ready_hint' if 'submit' in self.actions else 'review_hint'
            if self.task['task_type']=='digital_destruction':hint='disposition_digital_confirmation_required'
            if self.task['task_type']=='digital_destruction' and ((workspace.get('destruction') or {}).get('progress') or {}).get('state')=='succeeded':
                from .completion import status_message
                hint=status_message(workspace)
            if self.task['task_type']=='certificate_download':hint='certificate_finish_hint'
            ui.label(text(hint) if self.roles else text('no_current_task')).classes('text-sm text-slate-600').props('role=status')
            for key in ('direct_assignee','role_queue','claimant'):
                ui.label(text(key)+' · '+(self.task.get(key) or '—')).props('dir=auto')
            self.acting_role_id=automatic_role(self.roles)
            if 'claim' in self.actions:ui.label(text('claim_before_proposals')).classes('text-sm text-amber-900').props('role=status')
            if 'claim' in self.actions:ui.button(text('claim'),icon='assignment_ind',on_click=lambda:self.queue_action('claim')).tooltip(text('claim')).props('no-caps')
            if 'reassign' in self.actions:ui.button(text('reassign'),icon='person_add',on_click=self.reassign).tooltip(text('reassign')).props('outline no-caps')
            if 'release' in self.actions:ui.button(text('release'),icon='undo',on_click=lambda:self.queue_action('release')).tooltip(text('release')).props('outline no-caps')
            self.body=ui.column().classes('w-full gap-4')

    def alive(self):return self.active() and not self.host._deleted

    def dirty(self):
        return self.busy or self.has_changes()

    def needs_submission_comments(self):
        return 'submit' in self.actions or self.job['review_route']=='records_manager_only'

    def has_changes(self):
        return self.comments is not None and str(self.comments.value or '')!=self.saved_comments

    def comments_need_sync(self):
        if self.comments is None or self.work is None:return False
        value=str(self.comments.value or '')
        return value!=str((self.work.get('own_notes') or {}).get('review_notes') or '') or (
            self.needs_submission_comments() and value!=str(self.work.get('overall_reason') or ''))

    def error(self,error):
        if self.alive():
            self.feedback.text=failure(error,self.on_error);ui.notify(self.feedback.text,type='negative')
            if self.draft_controls:self.draft_controls.update()

    def comments_changed(self):
        if not self.alive():return
        if self.draft_controls:self.draft_controls.update()
        for host,root_id,active in list(self.pending_disclosures):
            if root_id is None and active():self.render_draft_disclosure(host,None)

    async def queue_action(self,action):
        from .screens import command_dialog
        if self.dirty():ui.notify(text('unsaved_warning'),type='warning');return
        await command_dialog(api=self.api,context={'roles':self.view['roles'] if action=='claim' else list({r['id']:r for r in self.view['roles']+self.view.get('task_management_roles',[])}.values())},active=self.alive,on_error=self.on_error,title=action,build=lambda active:lambda:{},path=f"tasks/{self.task['id']}/{action}",version=self.task['version'],after=self.after,reason_required=action!='claim',confirm='claim_explanation' if action=='claim' else None)

    async def load(self):
        from .external import request_controls,task_form
        if self.job['workflow_stage']=='external_approval_pending' or any((self.view.get('external') or {}).get(k) for k in ('can_generate','can_renew')):request_controls(self,host=self.documents_host)
        from .physical import controls as physical_controls,task_form as physical_task_form
        if self.job['workflow_stage']=='physical_destruction':physical_controls(self)
        from .destruction import controls as destruction_controls
        destruction_controls(self)
        from .email import controls as email_controls
        email_controls(self,host=self.documents_host)
        from .completion import controls as completion_controls
        if (self.job['workflow_stage'] in ('certificate_generation','completed') or self.job.get('lifecycle_state')=='completed'
                or self.job['workflow_stage']=='digital_destruction' and (self.view.get('completion') or {}).get('progress')):completion_controls(self)
        self.history_sections()
        if not self.task or not self.roles:return
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
            if work.get('return_context'):
                from .process import return_notice
                with ui.column().classes('w-full gap-1').props('role=status'):
                    return_notice(work['return_context'],self.format_timestamp)
            if work.get('submission_reason'):
                ui.label(text('submission_comments')).classes('font-semibold');ui.label(work['submission_reason']).props('dir=auto').classes('whitespace-pre-wrap')
            if self.job.get('current_review_round',0)>1 and self.job.get('workflow_stage') in ('file_administrator_review','unit_manager_review','records_manager_review'):
                from .process import previous_rounds
                previous_rounds(self.job,self.api,self.body,self.alive,self.on_error,self.format_timestamp,load_notice=False)
            if 'save' in self.actions:
                self.proposal_host=ui.column().classes('w-full gap-3')
                # Preserve both legacy draft texts in the single editor without
                # silently saving or marking an untouched form dirty.
                legacy_notes=str((work.get('own_notes') or {}).get('review_notes') or '')
                legacy_reason=str(work.get('overall_reason') or '') if self.needs_submission_comments() else ''
                parts=[]
                for value in (legacy_reason,legacy_notes):
                    if value.strip() and not any(value.strip()==part.strip() for part in parts):parts.append(value)
                self.saved_comments='\n\n'.join(parts)
                self.comments=ui.textarea(text('review_comments_optional'),value=self.saved_comments).props('outlined autogrow').classes('w-full')
                self.comments.on_value_change(self.comments_changed)
                ui.label(text('review_comments_optional_hint')).classes('text-sm text-slate-600')
                ui.label(text('immediate_proposals_hint')).classes('text-sm text-slate-600')
                self.buttons=[]
                with ui.row().classes('w-full gap-2 flex-wrap'):
                    for action in ('submit','complete_review','reject','approve'):
                        if action in self.actions:
                            label='approve_generate_request' if action=='approve' and self.job['review_route']=='records_manager_only' else action
                            self.buttons.append(ui.button(text(label),icon={'save':'save','submit':'send','complete_review':'done','reject':'assignment_return','approve':'verified'}[action],on_click=lambda _,a=action:self.perform(a)).tooltip(text(label)).props('no-caps'+(' outline' if action=='reject' else '')))
                            if action in ('submit','complete_review','approve'):
                                self.progress_buttons.append(self.buttons[-1]);self.buttons[-1].set_enabled(not self.review_blocked)
            self.history_sections()
            await self.proposals_panel(host=self.proposal_host if 'save' in self.actions else None)
        if 'save' in self.actions and self.alive():
            from .draft_controls import DraftControls
            self.draft_controls=DraftControls(self,self.footer_host or self.host)

    async def send(self,path,payload,version):
        payload={**payload,'acting_role_id':self.acting_role_id}
        signature=json.dumps([path,payload,version],sort_keys=True)
        identity=self.retry.setdefault(signature,str(uuid4()))
        return await self.api.disposition_command(path,{**payload,'command_id':identity,'acting_role_id':self.acting_role_id},version=version,reason=text('save'))

    async def persist(self):
        if not self.has_changes() and not self.comments_need_sync():return
        payload={'task_version':self.work['task_version'],'changes':[],'review_notes':self.comments.value or '',
                 'note_version':(self.work.get('own_notes') or {}).get('version',0)}
        if self.needs_submission_comments():payload['overall_reason']=self.comments.value or ''
        result=await self.send(f"tasks/{self.task['id']}/review-work",payload,self.work['job_version'])
        if not self.alive():return result
        self.work.update(job_version=result['job_version'],task_version=result['task_version'],overall_reason=self.comments.value if self.needs_submission_comments() else self.work.get('overall_reason'),own_notes={'version':result['note_version'],'review_notes':self.comments.value or ''})
        self.job['version']=result['job_version'];self.task['version']=result['task_version']
        self.saved_comments=str(self.comments.value or '')
        self.render_pending()
        return result

    async def save_proposals(self,changes,feedback,*,bulk=False):
        """Save one confirmed editor action atomically, without saving comments.

        Exact-payload retry identities survive transport errors. Version failures
        leave the editor open; they never silently overwrite another reviewer's work.
        No resource changes or workflow transitions happen here.
        """
        if not self.alive() or self.busy:return False
        self.busy=True;feedback.text='';self.feedback.text=''
        if self.draft_controls:self.draft_controls.update()
        committed=False
        try:
            result=await self.send(f"tasks/{self.task['id']}/review-work",
                {'task_version':self.work['task_version'],'changes':changes,**({'bulk':True} if bulk else {})},self.work['job_version'])
            committed=True
            if not self.alive():return True
            self.work.update(job_version=result['job_version'],task_version=result['task_version'])
            self.job['version']=result['job_version'];self.task['version']=result['task_version']
            for selection in self.bulk_selections:selection.clear()
            ui.notify(text('bulk_saved',count=len(changes)) if bulk else text('proposal_saved'),type='positive')
            self.proposal_pages[:]=[(page,active) for page,active in self.proposal_pages if active()]
            await asyncio.gather(*(page.load() for page,active in self.proposal_pages))
            if self.alive():await self.after({'_saved_work':True,'job_version':result['job_version']})
            return True
        except ApiError as error:
            if bulk and not committed:raise
            if self.alive():
                feedback.text=failure(error,self.on_error)
                self.error(error)
            # Once committed, never leave an Add button offering to repeat it.
            return committed
        finally:
            self.busy=False
            if self.alive() and self.draft_controls:self.draft_controls.update()

    async def perform(self,action):
        if not self.alive() or self.busy or action not in self.actions:return
        if self.review_blocked and action in ('submit','complete_review','approve'):return
        required=action=='reject'
        if required and not str(self.comments.value or '').strip():
            self.feedback.text=text('review_comments_required')
            ui.notify(self.feedback.text,type='warning');self.comments.run_method('focus');return
        controls=self.buttons+[c for c in (self.comments,) if c is not None]
        self.busy=True;self.feedback.text=''
        for control in controls:control.disable()
        if self.draft_controls:self.draft_controls.update()
        saved=False
        try:
            confirmation=None
            if action=='approve':
                confirmation=await self.api.disposition_approval_summary(self.task['id'],acting_role_id=self.acting_role_id,task_version=self.work['task_version'],changes=[],version=self.work['job_version'])
                if not self.alive():return
                if confirmation['job_version']!=self.work['job_version'] or confirmation['task_version']!=self.work['task_version']:
                    raise ApiError(409,{'code':'disposition_stale_version'})
                with ui.dialog() as dialog,ui.card().classes('messaging-workspace max-w-full gap-4'):
                    ui.label(text('approval_title')).classes('text-xl font-semibold')
                    counts=' · '.join(text('approval_type_count',kind=text(kind),count=count) for kind,count in confirmation['proposal_counts'].items() if count)
                    ui.label(text('approval_summary',count=confirmation['proposal_count'],counts=counts) if counts else text('approval_no_proposals')).classes('whitespace-normal')
                    next_step=confirmation['next_step']
                    ui.label(text('approval_next_empty',stage=text(confirmation['empty_return_stage'])) if next_step=='empty' else text('approval_next_request' if next_step=='request' else 'approval_next_conditional')).classes('whitespace-normal')
                    ui.label(text('approval_no_destruction')).classes('font-semibold')
                    with ui.row():
                        ui.button(text('cancel'),on_click=lambda:dialog.submit(False)).props('flat no-caps')
                        ui.button(text('approve_apply'),on_click=lambda:dialog.submit(True)).props('no-caps')
                if not await dialog or not self.alive():return
            saved=await self.persist() is not None
            if not self.alive():return
            payload={'task_version':self.work['task_version']}
            if action=='save':
                await asyncio.gather(self.proposals.load(),*( [self.notes.load()] if hasattr(self,'notes') else []))
                if not self.alive():return
                ui.notify(text('saved'),type='positive');await self.after({'_saved_work':True,'job_version':self.work['job_version']});return True
            if action=='submit':payload['overall_reason']=self.comments.value;endpoint='submit-review'
            elif action in ('complete_review','reject'):
                payload.update(decision='rejected' if action=='reject' else 'approved',decision_reason=self.comments.value or '');endpoint='review-decision'
            else:
                preview=await self.api.disposition_page(f"tasks/{self.task['id']}/approval-preview",acting_role_id=self.acting_role_id) if saved else confirmation
                if not self.alive():return
                if preview['job_version']!=self.work['job_version'] or preview['task_version']!=self.work['task_version']:
                    raise ApiError(409,{'code':'disposition_stale_version'})
                payload.update(membership_token=preview['membership_token'],proposals_token=preview['proposals_token'],overall_reason=self.comments.value if self.needs_submission_comments() else None);endpoint='approve-proposals'
            result=await self.send(f"tasks/{self.task['id']}/{endpoint}",payload,self.work['job_version'])
            if not self.alive():return
            pending=result.get('request_status')=='pending' or result.get('report_status')=='pending'
            if action in ('submit','complete_review','reject'):
                notify_completion(result,'submitted' if action=='submit' else 'review_completed')
            else:
                notify_completion(result,'request_pending' if result.get('request_status')=='pending' else 'report_pending' if pending else 'review_completed',type='warning' if pending else 'positive')
            if action=='approve' and self.on_approved:
                await self.on_approved(result)
            else:await task_finished(self,result)
        except ApiError as error:
            if not self.alive():return
            if isinstance(error.detail,dict) and error.detail.get('approval_committed'):
                ui.notify(text('report_pending'),type='warning')
                if self.on_approved:await self.on_approved(error.detail)
                else:await task_finished(self,error.detail)
            else:
                if isinstance(error.detail,dict) and error.detail.get('code') in REVIEW_SETUP_ERRORS:
                    self.job['review_setup']=dict(REVIEW_SETUP_ERRORS[error.detail['code']]);self.review_blocked=True
                self.error(error)
                if saved:
                    ui.notify(text('decision_failed_saved'),type='warning')
                    await asyncio.gather(self.proposals.load(),*( [self.notes.load()] if hasattr(self,'notes') else []))
                    if self.alive():await self.after({'_saved_work':True,'job_version':self.work['job_version']})
        finally:
            self.busy=False
            if self.alive():
                for control in controls:control.enable()
                for button in self.progress_buttons:button.set_enabled(not self.review_blocked)
                if self.draft_controls:self.draft_controls.update()

    def remote(self,kind,label,*,target=False,root=None,multiple=False,selected=None,active=None,direction=None):
        if not target and kind in ('security_levels','holds','relationship_types','aggregations'):
            control=relationship_select(text(label),{},remote=True,multiple=multiple,value=[] if multiple else None,icon={'security_levels':'shield','holds':'gavel','relationship_types':'link','aggregations':'folder'}[kind])
            control.add_slot('no-option','<q-item><q-item-section>'+escape(text('empty'))+'</q-item-section></q-item>')
            if kind in ('holds','aggregations'):ui.label(text('selector_hint')).classes('text-xs text-slate-500')
        else:
            control=RemoteSelect({},label=text(label),with_input=True,multiple=multiple,value=[] if multiple else None).props('outlined dense clearable').classes('w-full')
        base=f"tasks/{self.task['id']}/"+('proposal-targets/' if target else 'review-candidates/')+kind
        async def request(**params):return await self.api.disposition_page(base,acting_role_id=self.acting_role_id,**({'root_id':root} if target else {}),**({'direction':direction} if direction else {}),**params)
        async def load(query):return await request(query=query)
        async def hydrate(identity):
            response=await request(selected=identity)
            if not response['items']:raise ApiError(404,{'code':'disposition_resource_access_required'})
            return response['items'][0]
        self.bind_remote(control,{'security_levels':'security-levels','holds':'holds'}.get(kind,'aggregations'),('code','name'),('code','name'),page_loader=load,selected_loader=hydrate,min_query_length=0 if kind in ('security_levels','relationship_types') else 2,active=active or self.alive)
        if selected:
            control.options={r['id']:' · '.join(str(r[k]) for k in ('code','name') if r.get(k)) or str(r['id']) for r in selected}
            control.value=[r['id'] for r in selected] if multiple else selected[0]['id'];control.update()
        return control

    async def proposals_panel(self,root_id=None,host=None,active=None):
        from .proposal_presenter import proposed_change
        from .bulk import BulkSelection
        with host or self.host:
            ui.separator();ui.label(text('proposals')).classes('text-lg font-semibold')
            round_label=ui.label('').classes('text-sm text-slate-600')
            scope_active=active or self.task_active
            selection=None
            if 'propose' in self.actions:
                selection=BulkSelection(eligible=lambda row:'propose' in self.actions and row.get('editable',False),label=lambda row:row['target_label'],
                    active=scope_active,actions=[('bulk_withdraw_selected',lambda rows:self.bulk_proposals('withdraw',rows,scope_active))])
                self.bulk_selections[:]=[value for value in self.bulk_selections if not value.bar._deleted]
                self.bulk_selections.append(selection)
            async def fetch(p):
                result=await self.api.disposition_page(f"jobs/{self.job['id']}/proposals",limit=p.size,offset=(p.page-1)*p.size,review_round=self.proposal_round,root_id=root_id)
                for row in result['items']:
                    row['details_label']=text('proposal_metadata_details' if row.get('partial') else 'details')
                    row['details_available']=not row['redacted'] or bool(row.get('partial'))
                    row['change_label']=proposed_change(row)
                    row['proposer_label']=row.get('proposer_name') or '—'
                    row['reason_label']=text('restricted_text') if row['redacted'] and row.get('partial') else '—' if row['redacted'] else row.get('reason') or '—'
                    if row['redacted']:
                        target=row.get('target_summary')
                        row.update(target_label=target['number']+' · '+target['title'] if target else text('restricted_resource'),target_notice=text('restricted_proposal_details') if target else '',type_label='—',state_label='—',editable=False)
                        if row.get('partial'):
                            row.update(type_label=text(row['proposal_type']),state_label=text(row['proposal_state']),stage_label=text(row['proposer_stage']),time_label=self.format_timestamp(row['proposed_at']),editor_time_label=self.format_timestamp(row['last_revised_at']) if row.get('last_revised_at') else '—',reason=text('restricted_text'))
                        continue
                    a=row['current_values'].get('record') or row['current_values']
                    row['target_label']=(a.get('record_number') or a.get('aggregation_number') or str(row['target_aggregation_id']))+' · '+(a.get('title') or '')
                    row['editor_time_label']=self.format_timestamp(row['last_revised_at']) if row.get('last_revised_at') else '—'
                    row['stage_label']=text(row['proposer_stage'])
                    row['type_label']=text(row['proposal_type']);row['state_label']=text(row['proposal_state']);row['time_label']=self.format_timestamp(row['proposed_at'])
                    row['editable']='propose' in self.actions and self.work is not None and row['review_round']==self.work['review_round'] and row['proposal_state']=='active' and row['in_current_membership']
                return result
            def loaded(p,result):
                if selection:selection.loaded(p,result)
                rounds={r['review_round'] for r in result['items'] if r.get('review_round') is not None}
                number=next(iter(rounds)) if len(rounds)==1 else self.proposal_round if not rounds else None
                round_label.text=text('tracker_round',number=number) if number is not None else ''
                round_label.set_visibility(number is not None)
            page=PageTable(columns=[column('target_label','target'),column('change_label','proposed_change'),column('state_label','proposal_status'),column('proposer_label','proposed_by'),column('reason_label','proposal_reason'),column('actions')],fetch=fetch,active=scope_active,on_error=self.on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'),on_loaded=loaded,selection='multiple' if selection else None)
            if selection:selection.attach(page)
            page.table.add_slot('body-cell-target_label','''<q-td :props="props"><bdi>{{ props.row.target_label }}</bdi><div v-if="props.row.target_notice" class="text-sm text-slate-600">{{ props.row.target_notice }}</div></q-td>''')
            page.table.add_slot('body-cell-proposer_label','''<q-td :props="props"><span dir="auto">{{ props.row.proposer_label }}</span><div v-if="props.row.proposer_role_name" dir="auto" class="text-sm text-slate-600">{{ props.row.proposer_role_name }}</div></q-td>''')
            for name in ('change_label','reason_label'):
                page.table.add_slot('body-cell-'+name,'''<q-td :props="props"><span dir="auto" class="whitespace-pre-wrap">{{ props.value }}</span></q-td>''')
            page.table.add_slot('body-cell-actions','''<q-td :props="props"><div class="row no-wrap gap-1"><q-btn v-if="props.row.details_available" flat dense icon="info" :aria-label="props.row.details_label" @click="$parent.$emit('detail',props.row.id)"><q-tooltip>{{ props.row.details_label }}</q-tooltip></q-btn><q-btn v-if="props.row.editable" flat dense icon="edit" aria-label="'''+escape(text('revise'))+'''" @click="$parent.$emit('revise',props.row.id)"><q-tooltip>'''+escape(text('revise'))+'''</q-tooltip></q-btn><q-btn v-if="props.row.editable" flat dense icon="undo" aria-label="'''+escape(text('withdraw'))+'''" @click="$parent.$emit('withdraw',props.row.id)"><q-tooltip>'''+escape(text('withdraw'))+'''</q-tooltip></q-btn></div></q-td>''')
            def row(event):return next((r for r in page.table.rows if r['id']==event.args),None)
            page.table.on('detail',lambda event:self.details(row(event)))
            page.table.on('revise',lambda event:self.edit(existing=row(event)))
            page.table.on('withdraw',lambda event:self.withdraw(row(event)))
            if root_id is None:self.proposals=page
            self.proposal_pages[:]=[(prior,visible) for prior,visible in self.proposal_pages if visible()]
            self.proposal_pages.append((page,active or self.alive))
            await page.load()

    async def refresh_bulk(self):
        if not self.alive():return
        for selection in self.bulk_selections:selection.clear()
        # Keep unsaved comments in their editor while refreshing mutation versions.
        try:work=await self.api.disposition_page(f"tasks/{self.task['id']}/review-work")
        except ApiError as error:
            if error.status_code in (403,404) and self.alive():
                self.actions.discard('propose')
                for selection in self.bulk_selections:selection.sync()
            raise
        if not self.alive():return
        # Do not upgrade the comment editor's note version behind unsaved input.
        # Concurrent comment edits must still conflict on their original version.
        self.work.update({key:work[key] for key in ('job_version','task_version','task_state','review_round') if key in work})
        self.job['version']=work['job_version'];self.task['version']=work['task_version']
        if work.get('task_state') not in (None,'open','claimed'):self.actions.discard('propose')
        await asyncio.gather(*(page.load() for page,active in self.proposal_pages if active()))
        if self.alive():await self.after({'_saved_work':True,'job_version':work['job_version']})

    async def bulk_proposals(self,operation,rows,active=None):
        from .bulk import bulk_dialog
        if self.busy or 'propose' not in self.actions or not self.work:return
        active=active or self.alive
        async def execute(selected,reason,feedback):
            changes=([dict(action='withdraw',proposal_id=row['id'],expected_version=row['version'],reason=reason or None) for row in selected]
                     if operation=='withdraw' else
                     [dict(action='create',proposal_type='remove_from_job',governing_root_id=row['root_aggregation_id'],
                           target_aggregation_id=row['root_aggregation_id'],target_version=row['root_version'],
                           proposed_values={},reason=reason or None) for row in selected])
            return await self.save_proposals(changes,feedback,bulk=True)
        return await bulk_dialog(operation=operation,rows=rows,active=active,execute=execute,
                                 on_error=lambda error:failure(error,self.on_error),refresh=self.refresh_bulk)

    async def notes_panel(self,host=None,active=None):
        with host or self.host:
            ui.separator();ui.label(text('review_comments')).classes('text-lg font-semibold')
            async def fetch(p):
                result=await self.api.disposition_page(f"jobs/{self.job['id']}/review-notes",limit=p.size,offset=(p.page-1)*p.size)
                for row in result['items']:
                    if row.get('redacted'):row.update(review_notes=text('restricted'));continue
                    row['stage_label']=text(row['workflow_stage']);row['time_label']=self.format_timestamp(row['date_updated'])
                return result
            page=PageTable(columns=[column('review_round'),column('stage_label','stage'),column('author_name','actor'),column('role_name','acting_task_role'),column('review_notes','review_comments'),column('time_label','occurred'),column('actions')],fetch=fetch,active=active or self.alive,on_error=self.on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
            page.table.add_slot('body-cell-actions','''<q-td :props="props"><q-btn v-if="!props.row.redacted" flat dense icon="history" aria-label="'''+escape(text('revision_history'))+'''" @click="$parent.$emit('note-history',props.row.id)"><q-tooltip>'''+escape(text('revision_history'))+'''</q-tooltip></q-btn></q-td>''')
            page.table.on('note-history',lambda event:self.history('note',event.args))
            self.notes=page
            return page

    def render_pending(self):
        # Save concerns unsaved comments only; proposals are already persisted.
        for host,root_id,active in list(self.pending_disclosures):
            if active():self.render_draft_disclosure(host,root_id)
            else:self.pending_disclosures.remove((host,root_id,active))
        if self.draft_controls:self.draft_controls.update()

    def render_draft_disclosure(self,host,root_id):
        host.clear()
        with host:
            comments_changed=root_id is None and self.comments is not None and str(self.comments.value or '')!=self.saved_comments
            if comments_changed:
                ui.label(text('review_comments')).classes('font-semibold')
                ui.label(str(self.comments.value or '') or '—').props('dir=auto').classes('whitespace-pre-wrap')
            elif root_id is None:ui.label(text('no_unsaved_changes')).props('role=status')

    def register_draft_disclosure(self,dialog,host,root_id):
        active=lambda:self.alive() and dialog.value and not dialog._deleted
        disclosure=(host,root_id,active);self.pending_disclosures.append(disclosure)
        def closed(event):
            if not event.value and disclosure in self.pending_disclosures:self.pending_disclosures.remove(disclosure)
        dialog.on_value_change(closed)
        self.render_draft_disclosure(host,root_id)
        return active

    async def withdraw(self,row):
        if self.busy or not row or not row.get('editable'):return
        with ui.dialog() as dialog,ui.card().classes('messaging-workspace w-[600px] max-w-full gap-4'):
            ui.label(text('withdraw'));reason=ui.textarea(text('reason_optional')).props('outlined autogrow').classes('w-full')
            feedback=ui.label('').props('role=alert').classes('text-negative')
            async def accept():
                if await self.save_proposals([dict(action='withdraw',proposal_id=row['id'],expected_version=row['version'],reason=reason.value or None)],feedback):dialog.close()
            ui.button(text('withdraw'),on_click=accept).props('no-caps');ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
        dialog.open()

    async def details(self,row):
        from .proposal_details import show
        await show(self,row)

    async def edit(self,root=None,existing=None):
        if self.busy or 'propose' not in self.actions or existing and not existing.get('editable'):return
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
                        response=await self.api.disposition_page(f"tasks/{self.task['id']}/proposal-targets/aggregations",root_id=root_id,acting_role_id=self.acting_role_id,selected=root_id)
                        if not alive() or token!=generation[0]:return
                        target.update(response['items'][0]);ui.label(target['code']+' · '+target['name']).props('dir=auto')
                    else:
                        target_kind='records' if typ=='remove_record_relationship' else 'aggregations'
                        selected=[]
                        if existing or target_kind=='aggregations':
                            response=await self.api.disposition_page(f"tasks/{self.task['id']}/proposal-targets/{target_kind}",root_id=root_id,acting_role_id=self.acting_role_id,selected=selected_id)
                            if not alive() or token!=generation[0]:return
                            selected=response['items'];target.update(selected[0] if selected else {})
                        control=self.remote(target_kind,'target',target=True,root=root_id,selected=selected,active=alive)
                        async def changed():
                            target.clear()
                            if 'links' in values:values['links'].table.selected=[]
                            if not control.value or control._deleted:return
                            selected_id=control.value
                            result=await self.api.disposition_page(f"tasks/{self.task['id']}/proposal-targets/{target_kind}",root_id=root_id,acting_role_id=self.acting_role_id,selected=control.value)
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
                            rows=await asyncio.gather(*(self.api.disposition_page(f"tasks/{self.task['id']}/review-candidates/holds",acting_role_id=self.acting_role_id,selected=i) for i in initial['hold_ids']))
                            if not alive():return
                            selected=[r['items'][0] for r in rows if r['items']]
                            values['holds'].options={r['id']:r['code']+' · '+r['name'] for r in selected};values['holds'].value=initial['hold_ids'];values['holds'].update()
                    elif typ=='create_aggregation_relationship':
                        values['related']=self.remote('aggregations','related_aggregation_id',active=alive)
                        if self.browse_resource:
                            async def browse_related():
                                async def selected(item,browser_active):
                                    result=await self.api.disposition_page(f"tasks/{self.task['id']}/review-candidates/aggregations",acting_role_id=self.acting_role_id,selected=item['id'])
                                    if not alive() or token!=generation[0] or not browser_active():return
                                    if not result['items']:raise ApiError(404,{'code':'disposition_resource_access_required'})
                                    row=result['items'][0]
                                    values['related'].set_options({row['id']:row['code']+' · '+row['name']},value=row['id'])
                                await self.browse_resource(values['related'],on_select=selected,active=lambda:alive() and token==generation[0])
                            ui.button(text('browse'),icon='account_tree',on_click=browse_related).tooltip(text('browse')).props('outline no-caps')
                        values['direction']=ui.select({v:text(v) for v in ('outgoing','incoming')},value=initial.get('direction','outgoing'),label=text('direction')).props('outlined dense').classes('w-full')
                        type_host=ui.column().classes('w-full')
                        type_revision=[0]
                        async def refresh_type():
                            identity=values['type'].value if 'type' in values else initial.get('relationship_type_id')
                            previous_label=values['type'].options.get(identity,str(identity)) if 'type' in values else str(identity)
                            type_revision[0]+=1
                            revision=type_revision[0]
                            current=lambda:alive() and token==generation[0] and revision==type_revision[0]
                            type_host.clear()
                            with type_host:
                                control=self.remote('relationship_types','relationship_type_id',active=current,direction=values['direction'].value)
                                values['type']=control
                                if identity:control.set_options({identity:previous_label},value=identity)
                            if identity:
                                result=await self.api.disposition_page(f"tasks/{self.task['id']}/review-candidates/relationship_types",acting_role_id=self.acting_role_id,selected=identity,direction=values['direction'].value)
                                if current():control.set_options({r['id']:r['code']+' · '+r['name'] for r in result['items']},value=identity)
                        values['direction'].on_value_change(refresh_type)
                        await refresh_type()
                        if existing:
                            for key,remote_key,id_key in [('related','aggregations','related_aggregation_id')]:
                                result=await self.api.disposition_page(f"tasks/{self.task['id']}/review-candidates/{remote_key}",acting_role_id=self.acting_role_id,selected=initial[id_key])
                                if not alive():return
                                values[key].options={r['id']:r['code']+' · '+r['name'] for r in result['items']};values[key].value=initial[id_key];values[key].update()
                    elif typ in ('remove_aggregation_relationship','remove_record_relationship'):
                        singular='record' if typ=='remove_record_relationship' else 'aggregation'
                        async def read_links(**params):
                            return await self.api.disposition_page(f"tasks/{self.task['id']}/removal-candidates/{singular}",root_id=root_id,target_id=target['id'],acting_role_id=self.acting_role_id,exclude_proposal_id=existing['id'] if existing else None,language_tag=language(),**params)
                        async def fetch(p):
                            if not target:return {'items':[],'total':0}
                            result=await read_links(limit=p.size,offset=(p.page-1)*p.size)
                            for row in result['items']:
                                related=row['related'];row['target_label']=text('restricted_resource') if related['redacted'] else related['number']+' · '+related['title']
                                row['already_proposed']=row.get('already_proposed',False)
                                row['selectable']=not related['redacted'] and not row['already_proposed']
                                row['selection_label']=' · '.join(text(key) for key,flag in [('removal_already_proposed',row['already_proposed']),('removal_access_required',related['redacted'])] if flag)
                            return result
                        def sync_selection(*args,rows=None):
                            current={r['id']:r for r in (page.table.rows if rows is None else rows)}
                            selected=[current.get(r['id'],r) for r in page.table.selected]
                            page.table.selected=[r for r in selected if r.get('selectable',not r['related']['redacted'])]
                            eligible={identity for identity,r in current.items() if r['selectable']}
                            checked={r['id'] for r in page.table.selected}&eligible
                            state='true' if eligible and checked==eligible else 'null' if checked else 'false'
                            page.table.add_slot('header-selection',f'''<q-checkbox :model-value="{state}" :disable="{'false' if eligible else 'true'}" aria-label="{escape(text('select_available_relationships'))}" @update:model-value="$parent.$emit('select-available', $event)"><q-tooltip>{escape(text('select_available_relationships'))}</q-tooltip></q-checkbox>''')
                        page=PageTable(columns=[column('label','relationship_type_id'),column('target_label','target'),column('selection_label','removal_availability'),column('actions')],fetch=fetch,active=alive,on_error=self.on_error,empty='empty',selection='single' if existing else 'multiple',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'),on_loaded=lambda p,result:sync_selection(rows=result['items']))
                        page.table.add_slot('body-selection','''<span class="inline-flex" :tabindex="props.row.selectable ? -1 : 0"><q-checkbox :model-value="props.selected" :disable="!props.row.selectable" :aria-label="props.row.target_label" @update:model-value="props.selected = $event"/><q-tooltip v-if="props.row.selection_label">{{ props.row.selection_label }}</q-tooltip></span>''')
                        page.table.add_slot('body-cell-target_label','''<q-td :props="props"><bdi>{{ props.row.target_label }}</bdi></q-td>''')
                        page.table.add_slot('body-cell-actions','''<q-td :props="props"><q-btn v-if="props.row.existing_proposal_id" flat dense icon="info" aria-label="'''+escape(text('view_existing_proposal'))+'''" @click="$parent.$emit('existing-proposal',props.row.existing_proposal_id)"><q-tooltip>'''+escape(text('view_existing_proposal'))+'''</q-tooltip></q-btn></q-td>''')
                        def select_available(event):
                            available=[r for r in page.table.rows if r['selectable']]
                            ids={r['id'] for r in page.table.rows}
                            retained=[r for r in page.table.selected if r['id'] not in ids]
                            page.table.selected=retained+(available[:1] if existing else available) if event.args else retained
                            sync_selection()
                        async def existing_details(event):
                            if not alive():return
                            response=await self.api.disposition_page(f"jobs/{self.job['id']}/proposals",proposal_id=event.args,limit=1,offset=0)
                            if alive() and response['items']:await self.details(response['items'][0])
                        page.table.on('selection',sync_selection)
                        page.table.on('select-available',select_available)
                        page.table.on('existing-proposal',existing_details)
                        values['links']=page;await page.load()
                        if existing:
                            response=await read_links(selected_id=initial['relationship_id'],limit=1,offset=0)
                            if not alive():return
                            chosen=[r for r in response['items'] if r['selectable']]
                            page.table.selected=chosen;sync_selection()
                            if chosen:ui.label(text('relationship_id')+' · '+chosen[0]['label']+' · '+chosen[0]['related']['number']+' · '+chosen[0]['related']['title']).props('dir=auto')
                    elif typ=='local_retention_override':
                        for key in ('current_period_years','intermediate_period_years'):
                            values[key]=ui.number(text(key),value=initial.get(key,0),min=0,step=1,precision=0).props('outlined dense').classes('w-full')
                        actions={'destruction':'destruction','transfer_to_external_archive':'permanent_transfer','selective_preservation':'selective_transfer','retain_as_local_archives':'local_archives'}
                        values['final_disposition']=ui.select({k:text(v) for k,v in actions.items()},label=text('final_disposition'),value=initial.get('final_disposition','destruction')).props('outlined dense').classes('w-full')
                        values['instructions']=ui.textarea(text('instructions'),value=initial.get('instructions') or '').props('outlined autogrow').classes('w-full')
                    ui.label(text('immediate_proposals_hint')).classes('text-sm text-slate-600')
                    values['reason']=ui.textarea(text('reason_optional'),value=existing.get('reason') or '' if existing else '').props('outlined autogrow').classes('w-full')
            async def accept():
                if not alive() or self.busy:return
                if not target:feedback.text=text('required');ui.notify(feedback.text,type='warning');return
                typ=kind.value;proposed={};reason=values['reason'].value or None
                if typ=='blocking_security':proposed={'security_level_id':values['security'].value}
                elif typ=='add_to_holds':proposed={'hold_ids':values['holds'].value}
                elif typ=='create_aggregation_relationship':proposed={'direction':values['direction'].value,'related_aggregation_id':values['related'].value,'relationship_type_id':values['type'].value}
                elif typ.startswith('remove_') and typ!='remove_from_job':
                    selected=values['links'].table.selected
                    if not selected:feedback.text=text('select_available_relationships');return
                    if any(row['related']['redacted'] or not row.get('selectable',True) for row in selected):feedback.text=text('removal_unavailable');return
                    proposed={'relationship_id':selected[0]['id']}
                elif typ=='local_retention_override':
                    if any(values[k].value is None or values[k].value<0 or int(values[k].value)!=values[k].value for k in ('current_period_years','intermediate_period_years')):feedback.text=text('required');return
                    proposed={k:int(values[k].value) for k in ('current_period_years','intermediate_period_years')};proposed.update(final_disposition=values['final_disposition'].value,instructions=values['instructions'].value or None)
                if any(v is None or v==[] for v in proposed.values()) and typ!='local_retention_override':feedback.text=text('required');return
                change=dict(action='revise' if existing else 'create',target_version=target['version'],proposed_values=proposed,reason=reason)
                if existing:change.update(proposal_id=existing['id'],expected_version=existing['version'])
                else:change.update(governing_root_id=root_id,target_aggregation_id=target['aggregation_id'],target_record_id=target['id'] if typ=='remove_record_relationship' else None,proposal_type=typ)
                changes=[change]
                if typ in ('remove_aggregation_relationship','remove_record_relationship'):
                    # One proposal per exact link, all selected links saved atomically.
                    changes=[{**change,'proposed_values':{'relationship_id':row['id']}} for row in {row['id']:row for row in selected}.values()]
                if await self.save_proposals(changes,feedback):dialog.close()
            with ui.row().classes('w-full gap-2 justify-end'):
                ui.button(text('cancel'),on_click=dialog.close).props('flat no-caps')
                ui.button(text('update_proposal' if existing else 'add_proposal'),on_click=accept).props('no-caps')
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
            page=PageTable(columns=[column('round_number','review_round'),column('time_label','occurred'),column('submission_reason','submission_comments'),column('invalidation_reason','reason'),column('root_count'),column('actions')],fetch=fetch,active=active or self.alive,on_error=self.on_error,empty='empty',wrap_cells=True,empty_text=lambda:text('empty'),loading_text=lambda:text('loading'))
            page.table.add_slot('body-cell-actions','''<q-td :props="props"><q-btn v-if="!props.row.redacted" flat dense icon="history" aria-label="'''+escape(text('proposals'))+'''" @click="$parent.$emit('round',props.row.id)"><q-tooltip>'''+escape(text('proposals'))+'''</q-tooltip></q-btn><q-btn v-if="props.row.can_retry" flat dense icon="description" aria-label="'''+escape(text('retry_report'))+'''" @click="$parent.$emit('report',props.row.id)"><q-tooltip>'''+escape(text('retry_report'))+'''</q-tooltip></q-btn></q-td>''')
            async def show(event):
                row=next((r for r in page.table.rows if r['id']==event.args and not r.get('redacted')),None)
                if row:
                    for selection in self.bulk_selections:selection.clear()
                    self.proposal_round=row['round_number'];await self.proposals.load(reset=True)
            async def report(event):
                row=next((r for r in page.table.rows if r['id']==event.args and r.get('can_retry')),None)
                if not row:return
                with ui.dialog() as dialog,ui.card().classes('messaging-workspace max-w-full gap-4'):
                    ui.label(text('retry_report'))
                    role_id=automatic_role(managers)
                    feedback=ui.label('').props('role=alert').classes('text-negative')
                    identity=str(uuid4())
                    async def generate():
                        button.disable()
                        try:result=await self.api.disposition_command(f"jobs/{self.job['id']}/review-rounds/{row['id']}/execution-report",{'command_id':identity,'acting_role_id':role_id},reason=text('retry_report'))
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
        with ui.dialog() as dialog,ui.card().classes('messaging-workspace p-0 gap-0 flex-nowrap').style('width: 1050px; max-width: calc(100vw - 32px); max-height: calc(100dvh - 48px)'):
            with ui.column().classes('w-full p-5 pb-3 shrink-0'):
                ui.label(row['identity']).classes('font-semibold').props('dir=auto')
            with ui.column().classes('w-full px-5 gap-3 overflow-y-auto min-h-0'):
                drafts=ui.column().classes('w-full gap-3')
                host=ui.column().classes('w-full gap-3')
            with ui.column().classes('w-full p-5 pt-3 gap-2 shrink-0'):
                if self.draft_controls:
                    ui.label(text('comments_save_hint')).classes('text-xs text-slate-600')
                    self.draft_controls.dialog_actions(dialog)
                else:ui.button(text('close'),on_click=dialog.close).props('flat no-caps')
        dialog.open()
        active=self.register_draft_disclosure(dialog,drafts,row['root_aggregation_id'])
        await self.proposals_panel(root_id=row['root_aggregation_id'],host=host,active=active)

    def history_sections(self):
        """Retained page controls, with fresh server data on every expansion."""
        if self.history_built:return
        self.history_built=True
        with self.history_host:
            from .external import decisions_panel
            async def external_decisions(**kwargs):return await decisions_panel(self,**kwargs)
            for label,method in [('review_comments',self.notes_panel),('round_history',self.rounds_panel),('review_decisions',self.decisions_panel),('external_decisions',external_decisions)]:
                with ui.expansion(text(label),icon='history').classes('w-full') as expansion:
                    host=ui.column().classes('w-full gap-3');state={'page':None}
                def alive(expansion=expansion):return self.history_active() and expansion.value and not expansion._deleted
                async def opened(event,method=method,host=host,state=state,alive=alive):
                    if not event.value or not alive():return
                    if state['page'] is None:state['page']=await method(host=host,active=alive)
                    await state['page'].load()
                expansion.on_value_change(opened)
                async def refresh(opened=opened,alive=alive):
                    if alive():await opened(SimpleNamespace(value=True))
                self.history_refreshers.append(refresh)


    async def refresh_history(self):
        await asyncio.gather(*(refresh() for refresh in self.history_refreshers))
