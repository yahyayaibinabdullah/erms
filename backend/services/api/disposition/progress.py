"""Read-only round history; no snapshots or proposal contents leave this projection."""
from .artifacts import require_workspace


def round_number(job):
    saved=job.get('current_review_round') or 0
    return max(1,saved+1 if job.get('workflow_stage') in ('officer_correction','manager_correction') else saved)


def page(c, job, *, limit=25, offset=0, language_tag='en'):
    require_workspace(c,job['id'])
    number=round_number(job)
    rows=c.execute('''SELECT r.id,r.round_number,r.started_at,r.submission_reason,
        r.invalidated_at,r.invalidation_reason,
        COALESCE(NULLIF(u.translations->%s->>'name',''),NULLIF(u.translations->%s->>'name',''),u.name) actor_name,
        current_user_can_view_event_resource('disposition_review_round',r.id,NULL,to_jsonb(r)) visible
        FROM disposition_review_rounds r JOIN users u ON u.id=r.started_by_user_id
        WHERE r.job_id=%s AND r.round_number<%s ORDER BY r.round_number DESC LIMIT %s OFFSET %s''',
        (language_tag,language_tag.split('-')[0],job['id'],number,limit+1,offset)).fetchall()
    more=len(rows)>limit;rows=rows[:limit]
    ids=[r['id'] for r in rows if r['visible']]
    decisions=[]
    if ids:
        decisions=c.execute('''SELECT d.round_id,d.review_stage,d.decision,d.reason,d.decided_at,
            CASE d.review_stage WHEN 'file_administrator_review' THEN 1 WHEN 'unit_manager_review' THEN 2 ELSE 3 END sequence,d.id,
            COALESCE(NULLIF(u.translations->%s->>'name',''),NULLIF(u.translations->%s->>'name',''),u.name) actor_name
            FROM disposition_review_decisions d JOIN users u ON u.id=d.actor_user_id
            WHERE d.round_id=ANY(%s) AND current_user_can_view_event_resource('disposition_review_decision',d.id,NULL,to_jsonb(d))
            UNION ALL SELECT d.round_id,'external_approval_pending',d.decision,d.correction_notes,d.recorded_at,4,d.id,
            COALESCE(NULLIF(u.translations->%s->>'name',''),NULLIF(u.translations->%s->>'name',''),u.name)
            FROM disposition_external_approvals d JOIN users u ON u.id=d.recorded_by_user_id
            WHERE d.round_id=ANY(%s) AND current_user_can_view_event_resource('disposition_job',d.job_id,NULL,NULL)
            ORDER BY decided_at,sequence,id''',(language_tag,language_tag.split('-')[0],ids,language_tag,language_tag.split('-')[0],ids)).fetchall()
    for index,row in enumerate(rows):
        if not row.pop('visible'):
            rows[index]={'id':row['id'],'redacted':True}
        else:row['decisions']=[d for d in decisions if d['round_id']==row['id']]
    return {'items':rows,'has_more':more,'round_number':number}
