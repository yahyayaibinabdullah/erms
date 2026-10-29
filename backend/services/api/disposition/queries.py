"""Bounded live disposition projections; no operational result cache.

All authorization is evaluated on the request connection. Hidden roots retain
only a page-local envelope; hidden blockers never expose resource/hold IDs.
These reads are advisory; membership commands independently lock and recheck.
"""
from fastapi import HTTPException
from ..entity_localization import localized_projection
from . import blockers, observations
from .acceleration import current_accelerations


def require_manager(c):
    if not c.execute('SELECT disposition_private.can_manage() allowed').fetchone()['allowed']:
        raise HTTPException(403, detail={'code': 'insufficient_privilege'})


def context(c, language_tag='en'):
    require_manager(c)
    route=c.execute("SELECT value#>>'{}' route FROM application_settings WHERE key='DISPOSITION_DESTRUCTION_REVIEW_ROUTE'").fetchone()
    person=c.execute('SELECT id,name,translations FROM users WHERE id=current_user_id()').fetchone()
    if person:
        person['name']=localized_projection(person,language_tag,'name')['name']
        person.pop('translations')
    return {'current_user': person, 'destruction_review_route':route['route'] if route else None, 'roles': c.execute('''SELECT DISTINCT r.id,r.name,profile.code AS profile_code FROM roles r JOIN profiles profile ON profile.id=r.profile_id
      JOIN user_role_assignments a ON a.role_id=r.id
      JOIN profile_privileges pp ON pp.profile_id=r.profile_id
      JOIN privileges p ON p.id=pp.privilege_id
      WHERE a.user_id=current_user_id() AND r.is_information_governance
      AND role_effectively_active(r.id) AND a.valid_from<=CURRENT_TIMESTAMP
      AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
      AND p.code='disposition.jobs.manage' ORDER BY r.id''').fetchall()}


ELIGIBILITY = '''WITH facts AS (
 SELECT a.id,a.aggregation_number,a.title,a.version,a.date_closed,a.disposition_status,
 a.owning_org_unit_id,o.name AS owner,o.translations AS owner_translations,e.calculated_disposition_at,e.database_now,
 CASE WHEN e.calculated_disposition_at IS NOT NULL THEN greatest(0,floor(extract(epoch FROM (e.database_now-e.calculated_disposition_at))/86400)::integer) END AS days_overdue,
 e.rule_snapshot->>'final_disposition' AS final_disposition,
 e.rule_snapshot->>'rule_source' AS rule_source,
 CASE WHEN e.rule_snapshot->>'rule_source'='aggregation' THEN a.aggregation_number ELSE
 (SELECT code FROM classifications WHERE id=(e.rule_snapshot->>'defined_by_classification_id')::bigint) END AS rule_source_label,
 j.id AS job_id,j.job_number,current_user_can_view_aggregation(a.id) AS visible,
 COALESCE(b.vital,false) AS vital,COALESCE(b.security,false) AS security,
 COALESCE(b.held,false) AS held,COALESCE(b.vital_count,0) AS vital_count,
 COALESCE(b.security_count,0) AS security_count,COALESCE(b.hold_count,0) AS hold_count,
 COALESCE(b.hidden,false) AS hidden_blockers
 FROM aggregations a LEFT JOIN org_units o ON o.id=a.owning_org_unit_id
 CROSS JOIN LATERAL disposition_private.eligibility(a.id) e
 LEFT JOIN disposition_job_memberships m ON m.root_aggregation_id=a.id AND m.membership_state='active'
 LEFT JOIN disposition_jobs j ON j.id=m.job_id AND j.lifecycle_state='active'
 LEFT JOIN LATERAL (SELECT bool_or(is_vital) vital,bool_or(security_blocked) security,
 bool_or(cardinality(hold_ids)>0) held,count(*) FILTER(WHERE is_vital) vital_count,
 count(*) FILTER(WHERE security_blocked) security_count,count(*) FILTER(WHERE cardinality(hold_ids)>0) hold_count,
 bool_or(NOT CASE WHEN resource_kind='aggregation' THEN current_user_can_view_aggregation(resource_id)
 ELSE current_user_can_view_record(resource_id) END) hidden
 FROM disposition_private.protection_blockers(a.id)) b ON true
 WHERE a.parent_aggregation_id IS NULL AND (a.disposition_status BETWEEN 2 AND 5 OR j.id IS NOT NULL))
'''


def eligibility(c, *, limit, offset, sort='due', descending=False, owner=None,
                status=None, vital=None, security=None, held=None, due_from=None,
                due_to=None, group_owner=False, active_job=False, language_tag='en'):
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
    if active_job is not None:
        clauses.append('(job_id IS NOT NULL)=%s'); values.append(active_job)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    total = c.execute(ELIGIBILITY + 'SELECT count(*) total FROM facts' + where, values).fetchone()['total']
    order = ('owner ASC NULLS LAST,owning_org_unit_id ASC,' if group_owner else '') + sorts[sort] + (' DESC' if descending else ' ASC') + ' NULLS LAST,id ASC'
    rows = c.execute(ELIGIBILITY + 'SELECT * FROM facts' + where + ' ORDER BY ' + order + ' LIMIT %s OFFSET %s', [*values, limit, offset]).fetchall()
    # Enrich only the visible roots on this server page, never the whole result
    # set or a separate request per row. Share episode rules with details.
    accelerations = current_accelerations(c, [row['id'] for row in rows if row['visible']], language_tag)
    for index, row in enumerate(rows):
        row['owner'] = localized_projection(
            {'name': row['owner'], 'translations': row.pop('owner_translations', {})},
            language_tag, 'name')['name']
        row['acceleration'] = accelerations.get(row['id'])
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


def jobs(c, *, limit, offset, query='', lifecycle=None, sort='id', descending=True,
         job_type=None, owner='', assignee='', unassigned=False, language_tag='en', root_ids=None):
    require_manager(c)
    orders = {'id':'id','job_number':'job_number','job_type':'job_type',
              'lifecycle_state':'lifecycle_state','date_created':'date_created',
              'owner':'owner','assignee':'assignee'}
    if sort not in orders: raise HTTPException(422, detail='invalid sort')
    # Resolve display names before filtering/sorting/paging, using the same
    # exact-language, base-language, canonical fallback as entity projections.
    projection = """WITH jobs AS (SELECT j.*,
      COALESCE(NULLIF(COALESCE(NULLIF(u.translations->%s,'{}'::jsonb),u.translations->%s)->>'name',''),u.name) AS assignee,
      COALESCE(NULLIF(COALESCE(NULLIF(o.translations->%s,'{}'::jsonb),o.translations->%s)->>'name',''),o.name) AS owner,
      u.name AS canonical_assignee,o.name AS canonical_owner
      FROM disposition_jobs j LEFT JOIN users u ON u.id=j.assigned_user_id
      LEFT JOIN org_units o ON o.id=j.owning_org_unit_id) """
    where, values = ['job_number ILIKE %s'], [language_tag,language_tag.split('-')[0]]*2+['%'+query.strip()+'%']
    for field,value in [('lifecycle_state',lifecycle),('job_type',job_type)]:
        if value:where.append(field+'=%s');values.append(value)
    for field,value in [('owner',owner),('assignee',assignee)]:
        if value.strip():
            where.append('('+field+' ILIKE %s OR canonical_'+field+' ILIKE %s)')
            values.extend(['%'+value.strip()+'%']*2)
    if unassigned:where.append('assigned_user_id IS NULL')
    source=' FROM jobs WHERE '+' AND '.join(where)
    total=c.execute(projection+'SELECT count(*) total'+source,values).fetchone()['total']
    rows=c.execute(projection+'SELECT *'+source+' ORDER BY '+orders[sort]+(' DESC' if descending else ' ASC')+' NULLS LAST,id LIMIT %s OFFSET %s',[*values,limit,offset]).fetchall()
    for row in rows:
        row.pop('canonical_owner');row.pop('canonical_assignee')
    if root_ids:
        compatibility=job_selection_compatibility(c,[r['id'] for r in rows],root_ids)
        for row in rows:row['selection_error']=compatibility.get(row['id'])
    return {'items':rows,'total':total}


def job(c, identity, language_tag='en'):
    from .artifacts import require_workspace
    row=c.execute('''SELECT j.*,u.translations AS assignee_translations,o.translations AS owner_translations,u.name AS assignee,o.name AS owner,EXISTS(SELECT 1 FROM disposition_tasks t WHERE t.job_id=j.id AND t.workflow_stage=j.workflow_stage AND t.destination_user_id=current_user_id() AND t.task_state='open' AND t.task_type IN ('preparation','correction')) AS own_preparation_task FROM disposition_jobs j
     LEFT JOIN users u ON u.id=j.assigned_user_id LEFT JOIN org_units o ON o.id=j.owning_org_unit_id WHERE j.id=%s''',(identity,)).fetchone()
    if row and row['job_type']=='destruction':require_workspace(c,identity)
    else:require_manager(c)
    if not row: raise HTTPException(404, detail='job not found')
    for field in ('assignee','owner'):
        row[field]=localized_projection({'name':row[field],'translations':row.pop(field+'_translations')},language_tag,'name')['name']
    manager=c.execute('SELECT disposition_private.can_manage() allowed').fetchone()['allowed']
    row['assignment_editable']=manager and row['lifecycle_state']=='active'
    row['owner_editable']=manager and row['lifecycle_state']=='active' and row['job_type']=='destruction' and not row['current_review_round'] and not c.execute("SELECT 1 FROM disposition_job_memberships WHERE job_id=%s AND membership_state='active' UNION ALL SELECT 1 FROM disposition_review_rounds WHERE job_id=%s UNION ALL SELECT 1 FROM event_history WHERE entity_type='disposition_job' AND entity_id=%s AND operation='REVIEW_SUBMIT' LIMIT 1",(identity,identity,identity)).fetchone()
    preparer=c.execute("SELECT current_user_id()=%s AND disposition_private.governance_person(current_user_id(),%s) allowed",(row['assigned_user_id'],'INFO_GOV_MGR' if row.get('review_route')=='records_manager_only' else 'INFO_GOV_OFFICER')).fetchone()['allowed'] if row['job_type']=='destruction' else True
    own_preparation_task=row.pop('own_preparation_task')
    row['membership_editable']=row['lifecycle_state']=='active' and (row['job_type']!='destruction' or preparer and own_preparation_task and row['workflow_stage'] in ('officer_preparation','officer_correction','manager_preparation','manager_correction'))
    review_adder=c.execute('''SELECT t.destination_role_id AS role_id FROM disposition_tasks t
        WHERE t.job_id=%s AND t.workflow_stage='records_manager_review' AND t.task_state='claimed'
        AND t.claimed_by_user_id=current_user_id() AND disposition_private.can_add_review_members(t.job_id,t.destination_role_id)
        ORDER BY t.id LIMIT 1''',(identity,)).fetchone() if row['review_route']=='simplified' and row['workflow_stage']=='records_manager_review' else None
    row['membership_add_role_id']=review_adder['role_id'] if review_adder else None
    row['membership_addable']=row['membership_editable'] or review_adder is not None
    return row


def members(c, identity, *, limit, offset, query='', sort='id', descending=True, state=None, language_tag='en'):
    job(c,identity)
    orders={'id':'m.id','identity':'a.aggregation_number','owning_org_unit_name':'o.name','status_label':'a.disposition_status','membership_label':'m.membership_state','medium':'a.medium','classification_label':'cl.code'}
    if sort not in orders:raise HTTPException(422,detail='invalid sort')
    clauses=['m.job_id=%s'];params=[identity]
    if query.strip():
        clauses.append("current_user_can_view_aggregation(a.id) AND (a.aggregation_number ILIKE %s OR a.title ILIKE %s OR o.name ILIKE %s OR cl.code ILIKE %s OR cl.title ILIKE %s)")
        params.extend(['%'+query.strip()+'%']*5)
    if state:clauses.append('m.membership_state=%s');params.append(state)
    source=' FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id LEFT JOIN org_units o ON o.id=a.owning_org_unit_id LEFT JOIN classifications cl ON cl.id=a.classification_id WHERE '+' AND '.join(clauses)
    total=c.execute('SELECT count(*) total'+source,params).fetchone()['total']
    row_source=source.replace(' WHERE '," LEFT JOIN LATERAL disposition_private.eligibility(a.id) e ON true LEFT JOIN classifications rule_class ON rule_class.id=(e.rule_snapshot->>'defined_by_classification_id')::bigint WHERE ",1)
    rows=c.execute('''SELECT m.*,a.version AS root_version,a.aggregation_number,a.title,a.disposition_status,a.owning_org_unit_id,
      o.name AS owning_org_unit_name,o.translations AS owner_translations,a.medium,cl.code AS classification_code,cl.title AS classification_title,
      e.rule_snapshot AS effective_rule,rule_class.code AS rule_source_code,rule_class.title AS rule_source_title,
      (SELECT count(*) FROM disposition_review_proposals p WHERE p.job_id=m.job_id AND p.governing_root_id=m.root_aggregation_id AND p.review_round=disposition_private.review_round_for_work(m.job_id) AND p.proposal_state='active') AS proposal_count,
      EXISTS(SELECT 1 FROM disposition_review_proposals p WHERE p.job_id=m.job_id AND p.governing_root_id=m.root_aggregation_id AND p.review_round=disposition_private.review_round_for_work(m.job_id) AND p.proposal_state='active' AND p.proposal_type='remove_from_job') AS removal_proposed,
      (current_user_can_view_aggregation(a.id) OR disposition_private.retained_access('aggregation',a.id,false)) AS visible,a.disposition_status=10 AS destroyed,
      EXISTS(SELECT 1 FROM disposition_private.protection_blockers(a.id) WHERE is_vital) AS vital,
      EXISTS(SELECT 1 FROM disposition_private.protection_blockers(a.id) WHERE security_blocked) AS security,
      EXISTS(SELECT 1 FROM disposition_private.protection_blockers(a.id) WHERE cardinality(hold_ids)>0) AS held,
      EXISTS(SELECT 1 FROM disposition_private.relationship_scope(a.id) WHERE blocks_final) AS relationships_block_final,
      a.disposition_status NOT IN (10,11,12) AND disposition_private.unit_has_digital(a.id) AND EXISTS(SELECT 1 FROM disposition_private.unit_ids(a.id) u(id) WHERE NOT disposition_private.physical_item_remaining('aggregations',u.id) OR EXISTS(SELECT 1 FROM records r WHERE r.aggregation_id=u.id AND NOT disposition_private.physical_item_remaining('records',r.id))) AS partially_destroyed,
      EXISTS(SELECT 1 FROM disposition_private.recovery_roots(m.job_id) rr WHERE rr.root_id=a.id) AND disposition_private.recovery_unit_visible(a.id) AND disposition_private.can_manage() AS can_recover
      '''+row_source+' ORDER BY '+orders[sort]+(' DESC' if descending else ' ASC')+',m.id LIMIT %s OFFSET %s',(*params,limit,offset)).fetchall()
    for r in rows:
        r['owning_org_unit_name']=localized_projection({'name':r['owning_org_unit_name'],'translations':r.pop('owner_translations')},language_tag,'name')['name']
        if r['membership_state']=='active':observations.detect(c,identity,r['root_aggregation_id'])
        r['redacted']=not r.pop('visible')
        if r['redacted']:
            for field in ('destroyed','medium','classification_code','classification_title','rule_source_code','rule_source_title','effective_rule','proposal_count','removal_proposed','owning_org_unit_id','owning_org_unit_name','root_aggregation_id','root_version','aggregation_number','title','disposition_status','removal_reason','removal_required_reason','vital','security','held','relationships_block_final','partially_destroyed','can_recover'): r[field]=None
    return {'items':rows,'total':total}


def history(c, identity, *, limit, offset, language_tag='en'):
    job(c,identity)
    # Join by event ID before projection: filtering a redacted entity_id would
    # accidentally hide the immutable redacted event envelope itself.
    source=''' FROM event_history raw JOIN authorized_event_history e ON e.id=raw.id
      WHERE (raw.entity_type='aggregation' AND COALESCE(raw.metadata->>'recovery_job_id',raw.metadata->>'job_id')=%s::text) OR (raw.entity_type='disposition_job' AND raw.entity_id=%s)
      OR (raw.entity_type='disposition_job_membership' AND raw.entity_id IN
        (SELECT id FROM disposition_job_memberships WHERE job_id=%s))
      OR (raw.entity_type IN ('disposition_task','disposition_review_round','disposition_review_decision') AND
       ((raw.entity_type='disposition_task' AND raw.entity_id IN (SELECT id FROM disposition_tasks WHERE job_id=%s)) OR
        (raw.entity_type='disposition_review_round' AND raw.entity_id IN (SELECT id FROM disposition_review_rounds WHERE job_id=%s)) OR
        (raw.entity_type='disposition_review_decision' AND raw.entity_id IN (SELECT id FROM disposition_review_decisions WHERE job_id=%s))))
      OR (raw.entity_type='disposition_review_proposal' AND raw.entity_id IN (SELECT id FROM disposition_review_proposals WHERE job_id=%s))
      OR (raw.entity_type='disposition_review_note' AND raw.entity_id IN (SELECT id FROM disposition_review_notes WHERE job_id=%s))
      OR (raw.entity_type='disposition_job_document' AND raw.entity_id IN
        (SELECT id FROM disposition_job_documents WHERE job_id=%s))'''
    total=c.execute('SELECT count(*) total'+source,(identity,)*9).fetchone()['total']
    from .history_display import enrich
    rows=c.execute('SELECT e.*'+source+' ORDER BY e.occurred_at DESC,e.id DESC LIMIT %s OFFSET %s',(*(identity,)*9,limit,offset)).fetchall()
    return {'total':total,'items':enrich(c,rows,language_tag)}


def selector(c, kind, *, query='', selected=None, job_type='destruction', job_id=None, language_tag='en'):
    require_manager(c)
    saved=job(c,job_id) if job_id is not None else None
    route=saved['review_route'] if saved else c.execute("SELECT value#>>'{}' route FROM application_settings WHERE key='DISPOSITION_DESTRUCTION_REVIEW_ROUTE'").fetchone()['route']
    if saved:job_type=saved['job_type']
    if selected is None and len(query.strip())<2: return {'items':[]}
    if kind=='owners':
        rows=c.execute('''SELECT id,code,name,translations FROM org_units WHERE ((%s::bigint IS NOT NULL AND id=%s) OR (%s::bigint IS NULL AND (name ILIKE %s OR code ILIKE %s OR EXISTS(SELECT 1 FROM jsonb_each(translations) t WHERE t.value->>'name' ILIKE %s))))
          ORDER BY name,id LIMIT 25''',(selected,selected,selected,'%'+query.strip()+'%','%'+query.strip()+'%','%'+query.strip()+'%')).fetchall()
        for row in rows:
            row['name']=localized_projection(row,language_tag,'name')['name']
            row.pop('translations')
    elif kind=='assignees':
        rows=c.execute('''SELECT u.id,u.name FROM users u WHERE u.status='active' AND u.account_type='person'
          AND ((%s::bigint IS NOT NULL AND u.id=%s) OR (%s::bigint IS NULL AND (u.name ILIKE %s OR u.email ILIKE %s)))
          AND EXISTS(SELECT 1 FROM user_role_assignments a JOIN roles r ON r.id=a.role_id
          JOIN profiles profile ON profile.id=r.profile_id JOIN profile_privileges pp ON pp.profile_id=profile.id
          JOIN privileges p ON p.id=pp.privilege_id WHERE a.user_id=u.id AND r.is_information_governance
          AND role_effectively_active(r.id) AND a.valid_from<=CURRENT_TIMESTAMP AND (a.valid_until IS NULL OR a.valid_until>CURRENT_TIMESTAMP)
          AND p.code='disposition.jobs.manage' AND (%s<>'destruction' OR profile.code=CASE WHEN %s='records_manager_only' THEN 'INFO_GOV_MGR' ELSE 'INFO_GOV_OFFICER' END))
          ORDER BY u.name,u.id LIMIT 25''',(selected,selected,selected,'%'+query.strip()+'%','%'+query.strip()+'%',job_type,route)).fetchall()
    else: raise HTTPException(404,detail='selector not found')
    return {'items':rows}


def suggested_owner(c, root_ids, language_tag='en'):
    """Advisory owner from current accessible roots; never grants admission."""
    require_manager(c)
    ids=list(dict.fromkeys(root_ids))
    if not ids or len(ids)>100:
        raise HTTPException(422,detail='invalid root selection')
    roots=c.execute('''SELECT id,owning_org_unit_id FROM aggregations
      WHERE id=ANY(%s) AND parent_aggregation_id IS NULL
      AND current_user_can_view_aggregation(id)''',(ids,)).fetchall()
    if len(roots)!=len(ids):
        raise HTTPException(403,detail={'code':'disposition_resource_access_required'})
    owners=list({r['owning_org_unit_id'] for r in roots})
    row=c.execute('''WITH RECURSIVE ancestors AS (
      SELECT id AS source,id,parent_org_unit_id,0 AS depth,ARRAY[id] AS path
      FROM org_units WHERE id=ANY(%s)
      UNION ALL
      SELECT a.source,o.id,o.parent_org_unit_id,a.depth+1,a.path||o.id
      FROM ancestors a JOIN org_units o ON o.id=a.parent_org_unit_id
      WHERE NOT o.id=ANY(a.path)
    ), common AS (
      SELECT id,max(depth) AS depth FROM ancestors GROUP BY id
      HAVING count(DISTINCT source)=%s
    ) SELECT o.id,o.code,o.name,o.translations FROM common c JOIN org_units o USING(id)
      ORDER BY c.depth,o.id LIMIT 1''',(owners,len(owners))).fetchone()
    if row:
        row['name']=localized_projection(row,language_tag,'name')['name']
        row.pop('translations')
    return {'owner':row,'basis':'same_unit' if len(owners)==1 and row else 'common_ancestor' if row else 'no_common_ancestor'}


def job_selection_compatibility(c, job_ids, root_ids):
    """Bounded advisory chooser check; commands still lock and revalidate."""
    require_manager(c)
    ids=list(dict.fromkeys(root_ids))
    if not ids or len(ids)>100:raise HTTPException(422,detail='invalid root selection')
    roots=c.execute('SELECT id FROM aggregations WHERE id=ANY(%s) AND parent_aggregation_id IS NULL AND current_user_can_view_aggregation(id)',(ids,)).fetchall()
    if len(roots)!=len(ids):raise HTTPException(403,detail={'code':'disposition_resource_access_required'})
    rows=c.execute("""WITH RECURSIVE owners AS (
      SELECT a.id AS root_id,o.id,o.parent_org_unit_id,ARRAY[o.id] AS path
      FROM aggregations a JOIN org_units o ON o.id=a.owning_org_unit_id WHERE a.id=ANY(%s)
      UNION ALL SELECT a.root_id,o.id,o.parent_org_unit_id,a.path||o.id
      FROM owners a JOIN org_units o ON o.id=a.parent_org_unit_id WHERE NOT o.id=ANY(a.path)
    ) SELECT j.id,CASE
      WHEN j.lifecycle_state<>'active' THEN 'disposition_inactive_job'
      WHEN j.assigned_user_id IS NULL THEN 'disposition_assignment_required'
      WHEN j.job_type='destruction' AND j.workflow_stage NOT IN ('officer_preparation','officer_correction','manager_preparation','manager_correction') AND NOT disposition_private.can_add_review_members(j.id) THEN 'disposition_membership_stage_invalid'
      WHEN j.job_type='destruction' AND j.assigned_user_id<>current_user_id() AND NOT disposition_private.can_add_review_members(j.id) THEN 'disposition_assigned_preparer_required'
      WHEN j.job_type='destruction' AND NOT disposition_private.governance_person(j.assigned_user_id,CASE WHEN j.review_route='records_manager_only' THEN 'INFO_GOV_MGR' ELSE 'INFO_GOV_OFFICER' END) THEN 'disposition_assignee_not_authorized'
      WHEN j.job_type='destruction' AND NOT EXISTS(SELECT 1 FROM disposition_tasks t WHERE t.job_id=j.id AND t.workflow_stage=j.workflow_stage AND t.destination_user_id=current_user_id() AND t.task_state='open' AND t.task_type IN ('preparation','correction')) AND NOT disposition_private.can_add_review_members(j.id) THEN 'disposition_membership_stage_invalid'
      WHEN EXISTS(SELECT 1 FROM aggregations a WHERE a.id=ANY(%s) AND (a.disposition_status NOT BETWEEN 2 AND 5 OR a.disposition_status<>j.disposition_status-4)) THEN 'disposition_job_type_status_mismatch'
      WHEN j.job_type='destruction' AND EXISTS(SELECT 1 FROM unnest(%s::bigint[]) r(id) WHERE NOT EXISTS(SELECT 1 FROM owners o WHERE o.root_id=r.id AND o.id=j.owning_org_unit_id)) THEN 'disposition_owning_unit_mismatch'
      WHEN EXISTS(SELECT 1 FROM aggregations a WHERE a.id=ANY(%s) AND a.date_closed IS NULL) THEN 'disposition_root_not_closed'
      WHEN EXISTS(SELECT 1 FROM unnest(%s::bigint[]) a(id) CROSS JOIN LATERAL disposition_private.protection_blockers(a.id) b) THEN 'disposition_admission_blocked'
      WHEN EXISTS(SELECT 1 FROM unnest(%s::bigint[]) a(id) WHERE NOT user_can_view_aggregation(j.assigned_user_id,a.id)) THEN 'disposition_assignee_access_required'
      ELSE NULL END AS error FROM disposition_jobs j WHERE j.id=ANY(%s)
      """,(ids,ids,ids,ids,ids,ids,job_ids)).fetchall()
    return {r['id']:r['error'] for r in rows}
