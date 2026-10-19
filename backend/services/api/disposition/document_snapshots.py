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
    aggregations=c.execute('''SELECT a.id,a.parent_aggregation_id,a.aggregation_number,a.title,a.medium,disposition_private.physical_item_remaining('aggregations',a.id) AS physical_remaining,
      root.id AS root_id,cl.id AS classification_id,cl.code AS classification_code,cl.title AS classification_title,
      o.name AS owner,aggregation_effective_assigned_location(a.id) AS assigned_location,
      aggregation_effective_current_location(a.id) AS current_location,current_user_can_view_aggregation(a.id) AS visible
      FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) unit(id)
      JOIN aggregations a ON a.id=unit.id JOIN aggregations root ON root.id=m.root_aggregation_id
      JOIN classifications cl ON cl.id=root.classification_id JOIN org_units o ON o.id=a.owning_org_unit_id
      WHERE m.job_id=%s AND m.membership_state='active' ORDER BY a.id''',(job_id,)).fetchall()
    records=c.execute('''SELECT r.id,r.aggregation_id,r.medium,disposition_private.physical_item_remaining('records',r.id) AS physical_remaining,current_user_can_view_record(r.id) AS visible
      FROM disposition_job_memberships m CROSS JOIN LATERAL disposition_private.unit_ids(m.root_aggregation_id) unit(id)
      JOIN records r ON r.aggregation_id=unit.id WHERE m.job_id=%s AND m.membership_state='active' ORDER BY r.id''',(job_id,)).fetchall()
    if not all(x['visible'] for x in aggregations+records):invalid('disposition_resource_access_required',403)
    return {'roots':roots,'aggregations':aggregations,'records':records}


def counts(aggregations,records,roots=0):
    return {'roots':roots,'descendant_aggregations':len(aggregations)-roots,'records':len(records),
      **{medium:sum(x['medium']==medium for x in aggregations+records) for medium in ('physical','digital','mixed')}}


def request_groups(source):
    groups={}
    by_root=defaultdict(list);by_aggregation=defaultdict(list)
    for a in source['aggregations']:by_root[a['root_id']].append(a)
    for r in source['records']:by_aggregation[r['aggregation_id']].append(r)
    for root in source['roots']:
        aggs=by_root[root['id']]
        root_row=next(a for a in aggs if a['id']==root['id']);rule=root['rule_snapshot']
        local=rule['rule_source']=='aggregation'
        key=(root_row['classification_id'],local,rule['current_period_years'],rule['intermediate_period_years'],rule['final_disposition'],rule.get('instructions') or '')
        if key not in groups:
            groups[key]={'group.classification_code':root_row['classification_code'],'group.classification_title':root_row['classification_title'],
              'group.rule_source':'قاعدة حفظ محلية / Local retention override' if local else 'قاعدة التصنيف / Classification retention rule',
              'group.final_disposition':rule['final_disposition'],'group.current_years':rule['current_period_years'],
              'group.intermediate_years':rule['intermediate_period_years'],**{'group.'+k:0 for k in counts([],[])}}
        records=[r for a in aggs for r in by_aggregation[a['id']]]
        for k,v in counts(aggs,records,1).items():groups[key]['group.'+k]+=v
    return [groups[k] for k in sorted(groups)]


def physical_counts(aggregations,records):
    return {**{medium+'_aggregations':sum(a['medium']==medium and a.get('physical_remaining',True) for a in aggregations) for medium in ('physical','mixed')},
      **{medium+'_records':sum(r['medium']==medium and r.get('physical_remaining',True) for r in records) for medium in ('physical','mixed')}}


def physical_rows(source):
    aggs=source['aggregations'];records=source['records'];rows=[]
    # Bottom-up subtree counts, indexed once; no recursion or repeated scans.
    by_id={a['id']:a for a in aggs};children=defaultdict(list)
    detail_by_id={a['id']:{k:0 for k in PHYSICAL_COUNTS} for a in aggs}
    for a in aggs:children[a['parent_aggregation_id']].append(a['id'])
    for r in records:
        if r['medium'] in ('physical','mixed') and r.get('physical_remaining',True):detail_by_id[r['aggregation_id']][r['medium']+'_records']+=1
    pending=[a['id'] for a in aggs if a['parent_aggregation_id'] not in by_id];ordered=[]
    while pending:
        current=pending.pop();ordered.append(current);pending.extend(children[current])
    for current in reversed(ordered):
        a=by_id[current];parent=a['parent_aggregation_id']
        if parent in by_id:
            for k,v in detail_by_id[current].items():detail_by_id[parent][k]+=v
            if a['medium'] in ('physical','mixed') and a.get('physical_remaining',True):detail_by_id[parent][a['medium']+'_aggregations']+=1
    for a in sorted(aggs,key=lambda a:(a['classification_code'],a['classification_id'],a['aggregation_number'],a['id'])):
        if a['medium'] not in ('physical','mixed') or not a.get('physical_remaining',True):continue
        detail=detail_by_id[a['id']]
        rows.append({'aggregation.classification_code':a['classification_code'],'aggregation.classification_title':a['classification_title'],
          'aggregation.identifier':a['aggregation_number'],'aggregation.title':a['title'],'aggregation.owner':a['owner'],
          'aggregation.assigned_location':a['assigned_location'] or NOT_SPECIFIED,
          'aggregation.current_location':a['current_location'] or NOT_SPECIFIED,
          **{'aggregation.descendants.'+k:v for k,v in detail.items()}})
    # Count direct members once; never sum overlapping per-row descendant counts.
    totals=physical_counts(aggs,records);class_totals=[]
    grouped=defaultdict(lambda:{k:0 for k in PHYSICAL_COUNTS});labels={}
    for a in aggs:
        cid=a['classification_id'];labels[cid]=a['classification_code']+' · '+a['classification_title']
        if a['medium'] in ('physical','mixed') and a.get('physical_remaining',True):grouped[cid][a['medium']+'_aggregations']+=1
    for r in records:
        if r['medium'] in ('physical','mixed') and r.get('physical_remaining',True):grouped[by_id[r['aggregation_id']]['classification_id']][r['medium']+'_records']+=1
    for cid in sorted(grouped):
        values=grouped[cid]
        class_totals.append(labels[cid]+': '+'; '.join(PHYSICAL_COUNTS[k][0]+' / '+PHYSICAL_COUNTS[k][1]+': '+str(v) for k,v in values.items()))
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
