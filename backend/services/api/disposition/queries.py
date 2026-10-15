"""Bounded live disposition projections; no operational result cache.

All authorization is evaluated on the request connection. Hidden roots retain
only a page-local envelope; hidden blockers never expose resource/hold IDs.
These reads are advisory; membership commands independently lock and recheck.
"""
from fastapi import HTTPException
from . import blockers, observations


def require_manager(c):
    if not c.execute('SELECT disposition_private.can_manage() allowed').fetchone()['allowed']:
        raise HTTPException(403, detail={'code': 'insufficient_privilege'})


def context(c):
    require_manager(c)
    return {'roles': c.execute('''SELECT DISTINCT r.id,r.name,profile.code AS profile_code FROM roles r JOIN profiles profile ON profile.id=r.profile_id
      JOIN user_role_assignments a ON a.role_id=r.id
      JOIN profile_privileges pp ON pp.profile_id=r.profile_id
      JOIN privileges p ON p.id=pp.privilege_id
      WHERE a.user_id=current_user_id() AND r.is_information_governance
      AND role_effectively_active(r.id) AND a.valid_from<=CURRENT_TIMESTAMP
      AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
      AND p.code='disposition.jobs.manage' ORDER BY r.id''').fetchall()}


ELIGIBILITY = '''WITH facts AS (
 SELECT a.id,a.aggregation_number,a.title,a.version,a.date_closed,a.disposition_status,
 a.owning_org_unit_id,o.name AS owner,e.calculated_disposition_at,e.database_now,
 CASE WHEN e.calculated_disposition_at IS NOT NULL THEN greatest(0,floor(extract(epoch FROM (e.database_now-e.calculated_disposition_at))/86400)::integer) END AS days_overdue,
 e.rule_snapshot->>'final_disposition' AS final_disposition,
 e.rule_snapshot->>'rule_source' AS rule_source,
 CASE WHEN e.rule_snapshot->>'rule_source'='aggregation' THEN a.aggregation_number ELSE
 (SELECT code FROM classifications WHERE id=(e.rule_snapshot->>'defined_by_classification_id')::bigint) END AS rule_source_label,
 m.job_id,j.job_number,current_user_can_view_aggregation(a.id) AS visible,
 COALESCE(b.vital,false) AS vital,COALESCE(b.security,false) AS security,
 COALESCE(b.held,false) AS held,COALESCE(b.vital_count,0) AS vital_count,
 COALESCE(b.security_count,0) AS security_count,COALESCE(b.hold_count,0) AS hold_count,
 COALESCE(b.hidden,false) AS hidden_blockers
 FROM aggregations a LEFT JOIN org_units o ON o.id=a.owning_org_unit_id
 CROSS JOIN LATERAL disposition_private.eligibility(a.id) e
 LEFT JOIN disposition_job_memberships m ON m.root_aggregation_id=a.id AND m.membership_state='active'
 LEFT JOIN disposition_jobs j ON j.id=m.job_id
 LEFT JOIN LATERAL (SELECT bool_or(is_vital) vital,bool_or(security_blocked) security,
 bool_or(cardinality(hold_ids)>0) held,count(*) FILTER(WHERE is_vital) vital_count,
 count(*) FILTER(WHERE security_blocked) security_count,count(*) FILTER(WHERE cardinality(hold_ids)>0) hold_count,
 bool_or(NOT CASE WHEN resource_kind='aggregation' THEN current_user_can_view_aggregation(resource_id)
 ELSE current_user_can_view_record(resource_id) END) hidden
 FROM disposition_private.protection_blockers(a.id)) b ON true
 WHERE a.parent_aggregation_id IS NULL AND a.disposition_status BETWEEN 2 AND 5)
'''


def eligibility(c, *, limit, offset, sort='due', descending=False, owner=None,
                status=None, vital=None, security=None, held=None, due_from=None,
                due_to=None, group_owner=False):
    require_manager(c)
    sorts = {'due': 'calculated_disposition_at', 'owner': 'owner', 'status': 'disposition_status',
             'type': 'final_disposition', 'vital': 'vital', 'security': 'security', 'held': 'held', 'id': 'id'}
    if sort not in sorts:
        raise HTTPException(422, detail='invalid sort')
    clauses, values = [], []
    for field, value in [('owning_org_unit_id', owner), ('disposition_status', status),
                         ('vital', vital), ('security', security), ('held', held)]:
        if value is not None:
            clauses.append(f'{field}=%s'); values.append(value)
    for operator, value in [('>=', due_from), ('<=', due_to)]:
        if value is not None:
            clauses.append(f'calculated_disposition_at{operator}%s'); values.append(value)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    total = c.execute(ELIGIBILITY + 'SELECT count(*) total FROM facts' + where, values).fetchone()['total']
    order = ('owner ASC NULLS LAST,owning_org_unit_id ASC,' if group_owner else '') + sorts[sort] + (' DESC' if descending else ' ASC') + ' NULLS LAST,id ASC'
    rows = c.execute(ELIGIBILITY + 'SELECT * FROM facts' + where + ' ORDER BY ' + order + ' LIMIT %s OFFSET %s', [*values, limit, offset]).fetchall()
    for index, row in enumerate(rows):
        row['redacted'] = not row.pop('visible')
        row['blocked'] = row['vital'] or row['security'] or row['held']
        row['selectable'] = not row['redacted'] and not row['blocked'] and row['job_id'] is None and row['date_closed'] is not None
        if row['hidden_blockers']:
            for key in ('vital_count', 'security_count', 'hold_count'): row[key] = None
        if row['redacted']:
            # No stable inaccessible identifier, title, owner, due or job details.
            row = {key: None for key in row}
            row.update(id=f'redacted-{offset+index}',redacted=True,selectable=False)
            rows[index] = row
    return {'items': rows, 'total': total}


def jobs(c, *, limit, offset, query='', lifecycle=None, sort='id', descending=True):
    require_manager(c)
    orders = {'id': 'j.id','job_number':'j.job_number','job_type':'j.job_type','lifecycle_state':'j.lifecycle_state','date_created':'j.date_created'}
    if sort not in orders: raise HTTPException(422, detail='invalid sort')
    where, values = ['j.job_number ILIKE %s'], ['%'+query.strip()+'%']
    if lifecycle: where.append('j.lifecycle_state=%s'); values.append(lifecycle)
    source = ' FROM disposition_jobs j LEFT JOIN users u ON u.id=j.assigned_user_id LEFT JOIN org_units o ON o.id=j.owning_org_unit_id WHERE '+' AND '.join(where)
    total=c.execute('SELECT count(*) total'+source, values).fetchone()['total']
    rows=c.execute('SELECT j.*,u.name AS assignee,o.name AS owner'+source+' ORDER BY '+orders[sort]+(' DESC' if descending else ' ASC')+',j.id LIMIT %s OFFSET %s',[*values,limit,offset]).fetchall()
    return {'items':rows,'total':total}


def job(c, identity):
    require_manager(c)
    row=c.execute('''SELECT j.*,u.name AS assignee,o.name AS owner FROM disposition_jobs j
     LEFT JOIN users u ON u.id=j.assigned_user_id LEFT JOIN org_units o ON o.id=j.owning_org_unit_id WHERE j.id=%s''',(identity,)).fetchone()
    if not row: raise HTTPException(404, detail='job not found')
    row['owner_editable']=row['lifecycle_state']=='active' and row['job_type']=='destruction' and not row['current_review_round'] and not c.execute("SELECT 1 FROM disposition_job_memberships WHERE job_id=%s AND membership_state='active' UNION ALL SELECT 1 FROM disposition_review_rounds WHERE job_id=%s UNION ALL SELECT 1 FROM event_history WHERE entity_type='disposition_job' AND entity_id=%s AND operation='REVIEW_SUBMIT' LIMIT 1",(identity,identity,identity)).fetchone()
    row['membership_editable']=row['lifecycle_state']=='active' and (row['job_type']!='destruction' or row['workflow_stage'] in ('officer_preparation','officer_correction','manager_preparation','manager_correction'))
    return row


def members(c, identity, *, limit, offset):
    job(c,identity)
    total=c.execute('SELECT count(*) total FROM disposition_job_memberships WHERE job_id=%s',(identity,)).fetchone()['total']
    rows=c.execute('''SELECT m.*,a.version AS root_version,a.aggregation_number,a.title,a.disposition_status,
      current_user_can_view_aggregation(a.id) AS visible,
      EXISTS(SELECT 1 FROM disposition_private.protection_blockers(a.id) WHERE is_vital) AS vital,
      EXISTS(SELECT 1 FROM disposition_private.protection_blockers(a.id) WHERE security_blocked) AS security,
      EXISTS(SELECT 1 FROM disposition_private.protection_blockers(a.id) WHERE cardinality(hold_ids)>0) AS held,
      EXISTS(SELECT 1 FROM disposition_private.relationship_scope(a.id) WHERE blocks_final) AS relationships_block_final
      FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id
      WHERE m.job_id=%s ORDER BY m.id DESC LIMIT %s OFFSET %s''',(identity,limit,offset)).fetchall()
    for r in rows:
        if r['membership_state']=='active':observations.detect(c,identity,r['root_aggregation_id'])
        r['redacted']=not r.pop('visible')
        if r['redacted']:
            for field in ('root_aggregation_id','root_version','aggregation_number','title','disposition_status','removal_reason','removal_required_reason','vital','security','held','relationships_block_final'): r[field]=None
    return {'items':rows,'total':total}


def history(c, identity, *, limit, offset):
    job(c,identity)
    # Join by event ID before projection: filtering a redacted entity_id would
    # accidentally hide the immutable redacted event envelope itself.
    source=''' FROM event_history raw JOIN authorized_event_history e ON e.id=raw.id
      WHERE (raw.entity_type='disposition_job' AND raw.entity_id=%s)
      OR (raw.entity_type='disposition_job_membership' AND raw.entity_id IN
        (SELECT id FROM disposition_job_memberships WHERE job_id=%s))
      OR (raw.entity_type='disposition_job_document' AND raw.entity_id IN
        (SELECT id FROM disposition_job_documents WHERE job_id=%s))'''
    total=c.execute('SELECT count(*) total'+source,(identity,identity,identity)).fetchone()['total']
    return {'total':total,'items':c.execute('SELECT e.*'+source+' ORDER BY e.occurred_at DESC,e.id DESC LIMIT %s OFFSET %s',(identity,identity,identity,limit,offset)).fetchall()}


def selector(c, kind, *, query='', selected=None, job_type='destruction'):
    require_manager(c)
    if selected is None and len(query.strip())<2: return {'items':[]}
    if kind=='owners':
        rows=c.execute('''SELECT id,name FROM org_units WHERE ((%s::bigint IS NOT NULL AND id=%s) OR (%s::bigint IS NULL AND (name ILIKE %s OR code ILIKE %s)))
          ORDER BY name,id LIMIT 25''',(selected,selected,selected,'%'+query.strip()+'%','%'+query.strip()+'%')).fetchall()
    elif kind=='assignees':
        rows=c.execute('''SELECT u.id,u.name FROM users u WHERE u.status='active' AND u.account_type='person'
          AND ((%s::bigint IS NOT NULL AND u.id=%s) OR (%s::bigint IS NULL AND (u.name ILIKE %s OR u.email ILIKE %s)))
          AND EXISTS(SELECT 1 FROM user_role_assignments a JOIN roles r ON r.id=a.role_id
          JOIN profiles profile ON profile.id=r.profile_id JOIN profile_privileges pp ON pp.profile_id=profile.id
          JOIN privileges p ON p.id=pp.privilege_id WHERE a.user_id=u.id AND r.is_information_governance
          AND role_effectively_active(r.id) AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
          AND p.code='disposition.jobs.manage' AND (%s<>'destruction' OR profile.code='INFO_GOV_OFFICER'))
          ORDER BY u.name,u.id LIMIT 25''',(selected,selected,selected,'%'+query.strip()+'%','%'+query.strip()+'%',job_type)).fetchall()
    else: raise HTTPException(404,detail='selector not found')
    return {'items':rows}
