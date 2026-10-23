"""Page-bounded, current authorized labels for immutable history references.

No cache. Only projected (not raw) events are inspected. Labels are current
localized names, not replacements for event-time snapshots or retained erasure.
"""
from ..entity_localization import localized_projection

REFERENCE_FIELDS = {
    'aggregation': ('root_aggregation_id','root_id','governing_root_id','aggregation_id','target_aggregation_id','source_aggregation_id','related_aggregation_id','parent_aggregation_id'),
    'record': ('previous_record_id','record_id','target_record_id','source_record_id','related_record_id'),
    'user': ('actor_user_id','assigned_user_id','added_by_user_id','removed_by_user_id','proposer_user_id','approving_user_id','executor_user_id','claimed_by_user_id','direct_assignee_user_id','destination_user_id','submitted_by_user_id','decided_by_user_id','confirmed_by_user_id','created_by_user_id','author_user_id','completed_by_user_id','terminated_by_user_id','released_by_user_id','reassigned_by_user_id','last_revised_by_user_id','withdrawn_by_user_id','executed_by_user_id'),
    'role': ('acting_role_id','proposer_role_id','destination_role_id','role_ids','last_revised_role_id'),
    'owner': ('owning_org_unit_id','routing_org_unit_id'),
    'job': ('job_id','recovery_job_id','disposition_job_id'),
    'security': ('security_level_id','old_security_level_id','new_security_level_id'),
    'hold': ('hold_id','hold_ids'),
    'relationship_type': ('relationship_type_id',),
    'document': ('document_id','certificate_document_id','previous_document_id'),
    'classification': ('classification_id','defined_by_classification_id'),
}
FIELD_KIND = {field:kind for kind,fields in REFERENCE_FIELDS.items() for field in fields}
QUERIES = {
    'aggregation': "SELECT id,aggregation_number AS code,title AS name FROM aggregations WHERE id=ANY(%s) AND current_user_can_view_aggregation(id) AND disposition_status<>10",
    'record': "SELECT id,record_number AS code,title AS name FROM records WHERE id=ANY(%s) AND current_user_can_view_record(id) AND disposition_status<>10",
    'user': 'SELECT id,name,translations FROM users WHERE id=ANY(%s)',
    'role': 'SELECT id,code,name,translations FROM roles WHERE id=ANY(%s)',
    'owner': 'SELECT id,code,name,translations FROM org_units WHERE id=ANY(%s)',
    'job': "SELECT id,job_number AS name FROM disposition_jobs WHERE id=ANY(%s) AND current_user_can_view_event_resource('disposition_job',id,NULL,NULL)",
    'security': 'SELECT id,code,name,translations FROM security_levels WHERE id=ANY(%s)',
    'relationship_type': 'SELECT id,code,forward_name AS name FROM relationship_types WHERE id=ANY(%s)',
    'document': "SELECT d.id,r.record_number AS code,r.title AS name FROM disposition_job_documents d JOIN records r ON r.id=d.record_id WHERE d.id=ANY(%s) AND current_user_can_view_record(r.id) AND current_user_can_view_event_resource('disposition_job_document',d.id,NULL,NULL)",
    'hold': 'SELECT id,code,name FROM holds WHERE id=ANY(%s) AND disposition_private.hold_visible(id)',
    'classification': 'SELECT id,code,title AS name,translations FROM classifications WHERE id=ANY(%s)',
}


def references(value):
    if isinstance(value,dict):
        for field,item in value.items():
            if field in FIELD_KIND and isinstance(item,int) and not isinstance(item,bool):
                yield FIELD_KIND[field],item
            if field in FIELD_KIND and isinstance(item,list):
                for identity in item:
                    if isinstance(identity,int) and not isinstance(identity,bool):yield FIELD_KIND[field],identity
            yield from references(item)
    elif isinstance(value,list):
        for item in value:yield from references(item)


def enrich(c, rows, language_tag='en'):
    allowed=c.execute("SELECT user_has_global_privilege(current_user_id(),'audit.view') allowed").fetchone()['allowed']
    requested={kind:set() for kind in QUERIES}
    visible=[row for row in rows if not (row.get('metadata') or {}).get('redacted')]
    for row in visible:
        for kind,identity in references(row):requested[kind].add(identity)
    labels={}
    for kind,ids in requested.items():
        if not ids:continue
        for value in c.execute(QUERIES[kind],(sorted(ids),)).fetchall():
            if kind=='classification':
                value['title']=value['name']
                value['name']=localized_projection(value,language_tag,'title')['title']
            elif 'translations' in value:
                value['name']=localized_projection(value,language_tag,'name')['name']
            labels[f"{kind}:{value['id']}"]=' · '.join(str(value[k]) for k in ('code','name') if value.get(k))
    for row in rows:
        row['can_view_technical_details']=bool(allowed)
        row['display_references']={f'{kind}:{identity}':labels.get(f'{kind}:{identity}') for kind,identity in references(row)} if row in visible else {}
        if row in visible and row.get('actor_user_id'):
            row['actor_name']=labels.get(f"user:{row['actor_user_id']}") or row.get('actor_name')
    return rows


def enrich_audit_page(c, rows, language_tag='en'):
    """Reuse disposition presentation in mixed global audit pages."""
    selected=[row for row in rows if str(row.get('entity_type','')).startswith('disposition_') or str(row.get('operation','')).startswith(('DISPOSITION_','DIGITAL_DESTRUCTION_'))]
    if selected:
        enrich(c,selected,language_tag)
        for row in selected:row['display_presentation']='disposition'
    return rows
