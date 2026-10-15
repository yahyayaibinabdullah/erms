"""Action-internal request/preparation snapshots using actual membership facts.

Approval/routing/finalization gates belong to their action services. These
helpers never approve, remove, destroy or expose a new HTTP operation.
"""
from collections import defaultdict

from . import documents
from .template_engine import invalid
from .template_contract import PHYSICAL_COUNTS

NOT_SPECIFIED='غير محدد / Not specified'


def capture(c,job_id):
    documents.require_access(c,job_id)
    roots=c.execute('''SELECT m.root_aggregation_id AS id,e.rule_snapshot FROM disposition_job_memberships m
      CROSS JOIN LATERAL disposition_private.eligibility(m.root_aggregation_id) e
      WHERE m.job_id=%s AND m.membership_state='active' ORDER BY m.root_aggregation_id''',(job_id,)).fetchall()
    aggregations=c.execute('''SELECT a.id,a.parent_aggregation_id,a.aggregation_number,a.title,a.medium,
      root.id AS root_id,cl.id AS classification_id,cl.code AS classification_code,cl.title AS classification_title,
      o.name AS owner,aggregation_effective_assigned_location(a.id) AS assigned_location,
      aggregation_effective_current_location(a.id) AS current_location,current_user_can_view_aggregation(a.id) AS visible
      FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) unit(id)
      JOIN aggregations a ON a.id=unit.id JOIN aggregations root ON root.id=m.root_aggregation_id
      JOIN classifications cl ON cl.id=root.classification_id JOIN org_units o ON o.id=a.owning_org_unit_id
      WHERE m.job_id=%s AND m.membership_state='active' ORDER BY a.id''',(job_id,)).fetchall()
    records=c.execute('''SELECT r.id,r.aggregation_id,r.medium,current_user_can_view_record(r.id) AS visible
      FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) unit(id)
      JOIN records r ON r.aggregation_id=unit.id WHERE m.job_id=%s AND m.membership_state='active' ORDER BY r.id''',(job_id,)).fetchall()
    if not all(x['visible'] for x in aggregations+records):invalid('disposition_resource_access_required',403)
    return {'roots':roots,'aggregations':aggregations,'records':records}


def counts(aggregations,records,roots=0):
    return {'roots':roots,'descendant_aggregations':len(aggregations)-roots,'records':len(records),
      **{medium:sum(x['medium']==medium for x in aggregations+records) for medium in ('physical','digital','mixed')}}


def request_groups(source):
    groups={}
    for root in source['roots']:
        aggs=[a for a in source['aggregations'] if a['root_id']==root['id']]
        root_row=next(a for a in aggs if a['id']==root['id']);rule=root['rule_snapshot']
        local=rule['rule_source']=='aggregation'
        key=(root_row['classification_id'],local,rule['current_period_years'],rule['intermediate_period_years'],rule['final_disposition'])
        if key not in groups:
            groups[key]={'group.classification_code':root_row['classification_code'],'group.classification_title':root_row['classification_title'],
              'group.rule_source':'قاعدة حفظ محلية / Local retention override' if local else 'قاعدة التصنيف / Classification retention rule',
              'group.final_disposition':rule['final_disposition'],'group.current_years':rule['current_period_years'],
              'group.intermediate_years':rule['intermediate_period_years'],**{'group.'+k:0 for k in counts([],[])}}
        ids={a['id'] for a in aggs};records=[r for r in source['records'] if r['aggregation_id'] in ids]
        for k,v in counts(aggs,records,1).items():groups[key]['group.'+k]+=v
    return [groups[k] for k in sorted(groups)]


def physical_counts(aggregations,records):
    return {**{medium+'_aggregations':sum(a['medium']==medium for a in aggregations) for medium in ('physical','mixed')},
      **{medium+'_records':sum(r['medium']==medium for r in records) for medium in ('physical','mixed')}}


def physical_rows(source):
    aggs=source['aggregations'];records=source['records'];rows=[]
    for a in sorted(aggs,key=lambda a:(a['classification_code'],a['classification_id'],a['aggregation_number'],a['id'])):
        if a['medium'] not in ('physical','mixed'):continue
        descendants=set();pending=[a['id']]
        while pending:
            parent=pending.pop();children=[x['id'] for x in aggs if x['parent_aggregation_id']==parent and x['id'] not in descendants]
            descendants.update(children);pending.extend(children)
        # Records directly in the listed aggregation are its descendants too.
        detail=physical_counts([x for x in aggs if x['id'] in descendants],
          [r for r in records if r['aggregation_id'] in descendants|{a['id']}])
        rows.append({'aggregation.classification_code':a['classification_code'],'aggregation.classification_title':a['classification_title'],
          'aggregation.identifier':a['aggregation_number'],'aggregation.title':a['title'],'aggregation.owner':a['owner'],
          'aggregation.assigned_location':a['assigned_location'] or NOT_SPECIFIED,
          'aggregation.current_location':a['current_location'] or NOT_SPECIFIED,
          **{'aggregation.descendants.'+k:v for k,v in detail.items()}})
    # Count direct members once; never sum overlapping per-row descendant counts.
    totals=physical_counts(aggs,records);class_totals=[]
    by_id={a['id']:a for a in aggs}
    for classification_id in sorted({a['classification_id'] for a in aggs}):
        group_aggs=[a for a in aggs if a['classification_id']==classification_id]
        code=group_aggs[0]['classification_code']+' · '+group_aggs[0]['classification_title']
        group_records=[r for r in records if by_id[r['aggregation_id']]['classification_id']==classification_id]
        values=physical_counts(group_aggs,group_records)
        if any(values.values()):class_totals.append(code+': '+'; '.join(PHYSICAL_COUNTS[k][0]+' / '+PHYSICAL_COUNTS[k][1]+': '+str(v) for k,v in values.items()))
    return rows,totals,'; '.join(class_totals) or NOT_SPECIFIED


def job_fields(c,job_id,generated_at):
    job=c.execute('''SELECT j.*,o.name AS owner,u.name AS officer FROM disposition_jobs j
      JOIN org_units o ON o.id=j.owning_org_unit_id LEFT JOIN users u ON u.id=j.assigned_user_id WHERE j.id=%s''',(job_id,)).fetchone()
    if not job['officer']:invalid('disposition_assignment_required',409)
    return {'job.id':job_id,'job.number':job['job_number'],'job.type':job['job_type'],
      'job.owner':job['owner'],'job.officer':job['officer'],'job.created_at':job['date_created'].isoformat(),'generated_at':generated_at}


def request_snapshot(c,job_id,*,authority_name,review_summaries,review_round,form_version,generated_at):
    source=capture(c,job_id)
    if not source['roots']:invalid('disposition_document_snapshot_invalid')
    return {'source':source,'fields':{**job_fields(c,job_id,generated_at),'authority.name':authority_name,
      **{'counts.'+k:v for k,v in counts(source['aggregations'],source['records'],len(source['roots'])).items()},
      **{'review.'+k:v for k,v in review_summaries.items()},'review.round':review_round,'form.version':form_version,
      'membership.checksum':documents.checksum(source)},'groups':request_groups(source)}


def preparation_snapshot(c,job_id,*,report_version,generated_at):
    source=capture(c,job_id);rows,totals,classes=physical_rows(source)
    return {'source':source,'fields':{**job_fields(c,job_id,generated_at),'report.version':report_version,
      'membership.checksum':documents.checksum(source),'classification.totals':classes,
      **{'totals.'+k:v for k,v in totals.items()}},'aggregations':rows}
