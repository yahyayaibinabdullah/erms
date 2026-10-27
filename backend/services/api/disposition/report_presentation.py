"""Readable report presentation from immutable execution results and scoped entities."""
from . import document_snapshots as ds
from .template_engine import invalid

ACTIONS = {
    'make_vital': 'تعيين ملف حيوي / Mark as vital',
    'blocking_security': 'رفع مستوى السرية المانع للتصرف / Upgrade blocking security level',
    'add_to_holds': 'إضافة إلى تعليقات قانونية / Add to legal holds',
    'create_aggregation_relationship': 'إنشاء علاقة بين الملفات / Create aggregation relationship',
    'remove_aggregation_relationship': 'إزالة علاقة بين الملفات / Remove aggregation relationship',
    'remove_record_relationship': 'إزالة علاقة بين الوثائق / Remove record relationship',
    'local_retention_override': 'تعديل قاعدة الحفظ المحلية / Change local retention rule',
}


def aggregation_rows(c, data, timezone, language):
    affected={p['governing_root_id'] for p in data['results']}
    affected.update(effect['governing_root_id'] for p in data['results'] for effect in p['effect']['effects']
                    if effect['effect_type'] in ('unit_removed','cascading_unit_removed'))
    roots=[m['root_id'] for m in data['reviewed_membership'] if m['root_id'] in affected]
    rows=c.execute('''SELECT a.id,a.aggregation_number,a.title,a.medium,
        cl.code AS classification_code,aggregation_effective_assigned_location(a.id) AS assigned_location,
        current_user_can_view_aggregation(a.id) AS visible,
        count(r.id)::integer AS records,
        min(extract(year FROM r.date_originated AT TIME ZONE %s))::integer AS from_year,
        max(extract(year FROM r.date_originated AT TIME ZONE %s))::integer AS to_year,
        bool_and(current_user_can_view_aggregation(child.id) AND
            (r.id IS NULL OR current_user_can_view_record(r.id))) AS contents_visible
        FROM aggregations a JOIN classifications cl ON cl.id=a.classification_id
        CROSS JOIN LATERAL disposition_private.unit_ids(a.id) unit(id)
        JOIN aggregations child ON child.id=unit.id LEFT JOIN records r ON r.aggregation_id=unit.id
        WHERE a.id=ANY(%s) GROUP BY a.id,cl.code ORDER BY cl.code,a.aggregation_number,a.id''',
        (timezone,timezone,roots)).fetchall() if roots else []
    if len(rows)!=len(roots) or any(not r['visible'] or not r['contents_visible'] for r in rows):
        invalid('disposition_resource_access_required',403)
    return [{'aggregation.serial_number':i,'aggregation.number':r['aggregation_number'],
        'aggregation.title':r['title'],'aggregation.classification_code':r['classification_code'],
        'aggregation.from_year':r['from_year'] if r['from_year'] is not None else ds.unspecified(language),
        'aggregation.to_year':r['to_year'] if r['to_year'] is not None else ds.unspecified(language),
        'aggregation.records':r['records'],
        'aggregation.assigned_location':(r['assigned_location'] or ds.unspecified(language)) if r['medium'] in ('physical','mixed') else ds.wording('لا ينطبق / Not applicable',language)} for i,r in enumerate(rows,1)]


def enrich(c, row, snapshot, settings):
    data=row['approval_execution'];language=ds.request_language(c,settings,row['id'])
    def word(value):return ds.wording(value,language)
    fields=snapshot['fields']
    fields['execution.count']=len(data['results'])
    fields['organization.name']=ds.request_organization(c,row['job_id'],settings,language)['organization.name']
    snapshot['aggregations']=aggregation_rows(c,data,settings['DEFAULT_WORKING_TIMEZONE'],language)
    # Bounded IDs come only from this execution snapshot, never a tenant catalogue.
    aggregation_ids=set();record_ids=set();type_ids=set();level_ids=set();hold_ids=set();user_ids={data['approving_user_id'],data['job_snapshot']['assigned_user_id']};role_ids={data['acting_role_id']}
    for p in data['results']:
        aggregation_ids.add(p['target_aggregation_id']);aggregation_ids.add(p['governing_root_id'])
        aggregation_ids.update(e['governing_root_id'] for e in p['effect']['effects'])
        if p['target_record_id']:record_ids.add(p['target_record_id'])
        rel=p['current_values'].get('relationship') or {}
        if rel:
            (record_ids if p['target_record_id'] else aggregation_ids).update((rel['source_id'],rel['target_id']))
            type_ids.add(rel['relationship_type_id'])
        values=p['proposed_values']
        if values.get('related_aggregation_id'):aggregation_ids.add(values['related_aggregation_id'])
        if values.get('relationship_type_id'):type_ids.add(values['relationship_type_id'])
        if values.get('security_level_id'):level_ids.add(values['security_level_id'])
        hold_ids.update(values.get('hold_ids',[]))
        user_ids.add(p['proposer_user_id']);role_ids.add(p['proposer_role_id'])
    def entities(table,ids,columns):
        return {r['id']:r for r in c.execute(f'SELECT {columns} FROM {table} WHERE id=ANY(%s)',(sorted(i for i in ids if i is not None),)).fetchall()} if ids else {}
    aggs=entities('aggregations',aggregation_ids,'id,aggregation_number,title')
    records=entities('records',record_ids,'id,record_number,title')
    users=entities('users',user_ids,'id,name,translations')
    roles=entities('roles',role_ids,'id,name,translations')
    types=entities('relationship_types',type_ids,'id,forward_name,translations')
    levels=entities('security_levels',level_ids,'id,name,translations')
    holds=entities('holds',hold_ids,'id,name')
    def name(items,identity,fallback):return ds.bilingual(items.get(identity) or {'name':fallback},language=language)
    def resource(items,identity,number):
        item=items.get(identity)
        return item[number]+' · '+item['title'] if item else word('عنصر غير متاح / Unavailable resource')
    owner=c.execute('SELECT translations FROM org_units WHERE id=%s',(data['job_snapshot']['owning_org_unit_id'],)).fetchone()
    fields['job.owner']=ds.bilingual({'name':data['job_snapshot']['owner_name'],'translations':owner['translations'] if owner else {}},language=language)
    fields['job.officer']=name(users,data['job_snapshot']['assigned_user_id'],data['job_snapshot']['assignee_name'])
    fields['execution.manager']=name(users,data['approving_user_id'],data['approving_user_name'])+' · '+name(roles,data['acting_role_id'],data['acting_role_name'])
    for i,(proposal,result) in enumerate(zip(data['results'],snapshot['proposals']),1):
        result['proposal.serial_number']=i
        action=word(ACTIONS.get(proposal['proposal_type'],'تنفيذ المقترح / Execute proposal'))
        result['proposal.action']=action
        result['proposal.result']=word('تم التنفيذ / Executed')
        result['proposal.executor']=fields['execution.manager']
        result['proposal.proposer']=name(users,proposal['proposer_user_id'],proposal['proposer_name'])+' · '+name(roles,proposal['proposer_role_id'],proposal['proposer_role'])
        effect=proposal['effect'];reason_source=word('سبب المقترح / Proposal reason') if effect['reason_source']=='proposal' else word('سبب إرسال المراجعة / Review submission reason')
        result['proposal.reason']=effect['reason_used']+' · '+reason_source
        removed={e['governing_root_id'] for e in effect['effects'] if e['effect_type'] in ('unit_removed','cascading_unit_removed')}
        result['proposal.removed_units']='; '.join(resource(aggs,i,'aggregation_number') for i in sorted(removed)) or word('لا توجد / None')
        relationship=proposal['current_values'].get('relationship') or {}
        if relationship:
            items,number=(records,'record_number') if proposal['target_record_id'] else (aggs,'aggregation_number')
            result['proposal.change']=resource(items,relationship['source_id'],number)+' — '+ds.bilingual(types.get(relationship['relationship_type_id']) or {'forward_name':word('علاقة / Relationship')},field='forward_name',language=language)+' · '+word('إلى / To')+' · '+resource(items,relationship['target_id'],number)
        else:
            values=proposal['proposed_values'];kind=proposal['proposal_type']
            if kind=='blocking_security':
                change=name(levels,values['security_level_id'],word('مستوى السرية / Security level'))
            elif kind=='add_to_holds':
                change='; '.join(name(holds,h,word('تعليق قانوني / Legal hold')) for h in values['hold_ids'])
            elif kind=='create_aggregation_relationship':
                source,target=proposal['target_aggregation_id'],values['related_aggregation_id']
                if values['direction']=='incoming':source,target=target,source
                change=resource(aggs,source,'aggregation_number')+' — '+ds.bilingual(types[values['relationship_type_id']],field='forward_name',language=language)+' · '+word('إلى / To')+' · '+resource(aggs,target,'aggregation_number')
            elif kind=='local_retention_override':
                dispositions={'destruction':'الإتلاف / Destruction','selective_preservation':'الحفظ الانتقائي / Selective preservation','permanent_preservation':'الحفظ الدائم / Permanent preservation','permanent_transfer':'النقل الدائم / Permanent transfer'}
                change=(word('مدة الحفظ الجاري / Current period')+': '+str(values['current_period_years'])+' · '+word('مدة الحفظ الوسيط / Intermediate period')+': '+str(values['intermediate_period_years'])+' · '+word(dispositions.get(values['final_disposition'],'التصرف النهائي / Final disposition')))
                if values.get('instructions'):change+=' · '+values['instructions']
            else:change=action+' · '+result['proposal.target']
            result['proposal.change']=change
    # Storage verifies exact equality with the immutable approved execution.
    snapshot['source']=data
    return snapshot
