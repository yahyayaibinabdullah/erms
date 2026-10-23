"""Human-readable audit facts. Internal identifiers never become display names."""
from .messages import text, KEYS, status_label

REFERENCES = {
 'root_aggregation_id':'aggregation','root_id':'aggregation','governing_root_id':'aggregation',
 'aggregation_id':'aggregation','target_aggregation_id':'aggregation','source_aggregation_id':'aggregation','related_aggregation_id':'aggregation','parent_aggregation_id':'aggregation',
 'record_id':'record','target_record_id':'record','source_record_id':'record','related_record_id':'record','previous_record_id':'record',
 'job_id':'job','recovery_job_id':'job','disposition_job_id':'job','owning_org_unit_id':'owner',
 'acting_role_id':'role','proposer_role_id':'role','destination_role_id':'role',
 'security_level_id':'security','old_security_level_id':'security','new_security_level_id':'security',
 'classification_id':'classification','defined_by_classification_id':'classification','hold_id':'hold','hold_ids':'hold','role_ids':'role','routing_org_unit_id':'owner','relationship_type_id':'relationship_type','document_id':'document','previous_document_id':'document','certificate_document_id':'document',
}
for field in ('assigned','added_by','removed_by','proposer','approving','executor','claimed_by','direct_assignee','destination','submitted_by','decided_by','confirmed_by','created_by','author','completed_by','terminated_by','released_by','reassigned_by','last_revised_by','withdrawn_by','executed_by'):
    REFERENCES[field+'_user_id']='user'

# Use existing contextual vocabulary where its meaning is identical.
FIELDS = {
 'job_number':'job_number','job_type':'job_type','lifecycle_state':'lifecycle','workflow_stage':'stage',
 'disposition_status':'status','old_status':'before_values','new_status':'after_values',
 'membership_state':'history_membership_state','task_state':'task_state','review_round':'current_round','round_number':'current_round',
 'proposal_type':'proposal_type','proposal_state':'history_proposal_state','decision':'authority_decision',
 'review_notes':'review_notes','current_review_round':'current_round','proposer_stage':'stage','last_revised_stage':'stage','termination_reason':'reason','withdrawal_reason':'reason','task_type':'task_type','claimed_at':'history_added_at','released_at':'history_removed_at','reassigned_at':'history_added_at',
 'reason':'reason','removal_reason':'reason','overall_reason':'reason','decision_reason':'reason',
 'reason_used':'reason','notes':'review_notes','note':'review_notes','note_text':'review_notes','text':'review_notes',
 'title':'history_title','aggregation_number':'aggregation','record_number':'retained_record',
 'owner':'owner','owner_name':'owner','assignee':'assignee','assignee_name':'assignee',
 'proposer_name':'history_proposer','proposer_role':'role','approving_user_name':'history_approver',
 'acting_role_name':'role','executor_name':'retained_executor',
 'added_at':'history_added_at','removed_at':'history_removed_at','submitted_at':'history_submitted_at',
 'decided_at':'history_decided_at','executed_at':'history_executed_at','completed_at':'history_completed_at','confirmed_at':'history_confirmed_at',
 'date_closed':'history_closed_at','calculated_disposition_at':'normal_due',
 'is_vital':'vital','vital':'vital','security':'security','held':'history_held','relationships':'history_relationships',
 'removal_required':'history_removal_required','removal_required_reason':'reason',
 'evidence_type':'document_type','document_type':'document_type','document_state':'history_document_state',
 'evidence_version':'version','previous_evidence_version':'history_previous_evidence_version',
 'recipient':'email_recipient','recipient_email':'email_recipient','subject':'history_subject','delivery_state':'history_delivery_state',
 'outcome':'history_outcome','state':'history_outcome','error_code':'history_error','code':'history_error',
 'completed_units':'history_completed_units','total_units':'history_total_units','failed_units':'history_failed_units',
 'remaining_units':'history_remaining_units','removed_units':'history_removed_units','job_completed':'history_job_completed',
 'successful':'history_successful','digital_certificate':'history_digital_certificate',
 'certificate_reference':'history_certificate_reference','destruction_number':'destruction_number',
 'review_route':'history_review_route','medium':'history_medium','final_disposition':'status',
 'current_retention_years':'history_current_years','intermediate_retention_years':'history_intermediate_years',
 'direction':'direction','forward_name':'relationship_type_id','reverse_name':'relationship_type_id',
}
REFERENCE_LABELS = {'aggregation':'aggregation','record':'retained_record','job':'job_number','owner':'owner','role':'role','user':'actor','security':'security','classification':'classification','hold':'held','relationship_type':'relationship_type_id','document':'documents'}
for field,kind in REFERENCES.items():FIELDS[field]=REFERENCE_LABELS[kind]
FIELDS.update({'assigned_user_id':'assignee','added_by_user_id':'history_added_by','removed_by_user_id':'history_removed_by','proposer_user_id':'history_proposer','approving_user_id':'history_approver','executor_user_id':'retained_executor','claimed_by_user_id':'claimant','direct_assignee_user_id':'assignee'})
GROUPS={'current_values':'before_values','proposed_values':'after_values','approval_execution':'history_approval',
 'job_snapshot':'workspace_details','outcomes':'history_outcome','post_membership':'members','post_rules':'history_retention',
 'rule':'history_retention','rule_snapshot':'history_retention','physical_scope':'history_physical_scope','effect':'history_outcome',
 'proposals':'proposals','effects':'history_outcome','membership_snapshot':'members','execution_message':'history_outcome','request_facts':'history_request','relationship':'relationship_type_id'}
ENUM_FIELDS={'job_type','lifecycle_state','workflow_stage','membership_state','task_state','proposal_type','proposal_state','decision','evidence_type','document_type','document_state','delivery_state','outcome','state','review_route','medium','direction','final_disposition','task_type','proposer_stage','last_revised_stage'}


ENUM_ALIASES={'available':'history_available','generating':'history_generating','succeeded':'history_succeeded','queued':'history_queued','running':'history_running','pending':'history_pending','endorsed':'history_endorsed','sent':'history_sent','cancelled':'history_cancelled','released':'history_released','retain_as_local_archives':'local_archives','selective_preservation':'selective_transfer','transfer_to_external_archive':'permanent_transfer'}

def facts(value, references, format_timestamp, prefix=''):
    result=[]
    if isinstance(value,list):
        for item in value:result.extend(facts(item,references,format_timestamp,prefix))
    elif isinstance(value,dict):
        for field,item in value.items():
            if item is None or item=='' or item==[] or item=={}:continue
            if field in GROUPS:
                result.extend(facts(item,references,format_timestamp,prefix+text(GROUPS[field])+' · '));continue
            label=FIELDS.get(field)
            if not label:continue
            if field in REFERENCES:
                rendered='; '.join(references.get(f'{REFERENCES[field]}:{identity}') or text('history_unavailable') for identity in (item if isinstance(item,list) else [item]))
            elif isinstance(item,bool):rendered=text('yes' if item else 'no')
            elif field in ('disposition_status','old_status','new_status') and isinstance(item,int):rendered=status_label(item)
            elif field.endswith('_at') or field=='date_closed':
                rendered=format_timestamp(item)
            elif field in ENUM_FIELDS or field in ('error_code','code'):
                key=ENUM_ALIASES.get(item,item) if isinstance(item,str) else None
                rendered=text(key) if key in KEYS else text('history_unavailable')
            elif isinstance(item,(dict,list)):continue
            else:rendered=str(item)
            result.append((prefix+text(label),rendered))
    return list(dict.fromkeys(result))


def sections(row,format_timestamp):
    metadata=row.get('metadata') or {}
    if metadata.get('redacted'):return []
    refs=row.get('display_references') or {}
    before=row.get('before_state') if row.get('before_state') is not None else metadata.get('before')
    after=row.get('after_state') if row.get('after_state') is not None else metadata.get('after')
    result=[]
    if isinstance(before,dict) and isinstance(after,dict):
        changed={k for k in before.keys()|after.keys() if before.get(k)!=after.get(k)}
        for heading,value in [('before_values',before),('after_values',after)]:
            items=facts({k:v for k,v in value.items() if k in changed},refs,format_timestamp)
            # A cleared meaningful field is a change, not a literal JSON null.
            for field in changed:
                if field in FIELDS and value.get(field) is None:
                    items.append((text(FIELDS[field]),text('history_not_set')))
            if items:result.append((heading,items))
    else:
        items=facts(after or before,refs,format_timestamp)
        if items:result.append(('history_details',items))
    items=facts({k:v for k,v in metadata.items() if k not in ('before','after')},refs,format_timestamp)
    if items:result.insert(0,('history_details',items))
    return result
