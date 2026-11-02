"""Read-only action summaries over immutable, individually authorized events.

Pagination is over actions, never a client-side deduplication of an event page.
Unattributed legacy events join a command only when its transaction, actor,
source and request identify exactly one recorded command. Ambiguous events
remain independent. Every displayed event uses the existing authorized
projection, including restricted envelopes inside actions. No cache or writes.
"""
from fastapi import HTTPException
from .history_display import enrich


# This scope is also used by the existing raw event endpoint. Raw IDs locate
# redacted envelopes. Raw correlation is used only for server-side grouping;
# every returned fact comes from the authorized projection after pagination.
SCOPE = ''' WHERE (raw.entity_type='aggregation' AND COALESCE(raw.metadata->>'recovery_job_id',raw.metadata->>'job_id')=%s::text)
 OR (raw.entity_type='disposition_job' AND raw.entity_id=%s)
 OR (raw.entity_type='disposition_job_membership' AND raw.entity_id IN (SELECT id FROM disposition_job_memberships WHERE job_id=%s))
 OR (raw.entity_type='disposition_task' AND raw.entity_id IN (SELECT id FROM disposition_tasks WHERE job_id=%s))
 OR (raw.entity_type='disposition_review_round' AND raw.entity_id IN (SELECT id FROM disposition_review_rounds WHERE job_id=%s))
 OR (raw.entity_type='disposition_review_decision' AND raw.entity_id IN (SELECT id FROM disposition_review_decisions WHERE job_id=%s))
 OR (raw.entity_type='disposition_review_proposal' AND raw.entity_id IN (SELECT id FROM disposition_review_proposals WHERE job_id=%s))
 OR (raw.entity_type='disposition_review_note' AND raw.entity_id IN (SELECT id FROM disposition_review_notes WHERE job_id=%s))
 OR (raw.entity_type='disposition_job_document' AND raw.entity_id IN (SELECT id FROM disposition_job_documents WHERE job_id=%s))'''

SOURCE = ' FROM event_history raw JOIN authorized_event_history e ON e.id=raw.id'+SCOPE

GROUPS = '''WITH events AS MATERIALIZED (SELECT raw.* FROM event_history raw''' + SCOPE + '''),
 commands AS (
  SELECT transaction_id,actor_user_id,actor_type,source,request_id,
   count(DISTINCT NULLIF(metadata->>'command_id','')) command_count,
   min(NULLIF(metadata->>'command_id','')) command_id
  FROM events
  GROUP BY transaction_id,actor_user_id,actor_type,source,request_id
 ), grouped AS (
  SELECT e.*,CASE
   WHEN NULLIF(e.metadata->>'command_id','') IS NOT NULL THEN jsonb_build_array(e.transaction_id,e.actor_user_id,e.actor_type,e.source,e.request_id,e.metadata->>'command_id')::text
   WHEN c.command_count=1 THEN jsonb_build_array(e.transaction_id,e.actor_user_id,e.actor_type,e.source,e.request_id,c.command_id)::text
   ELSE 'event:'||e.id END AS action_key
  FROM events e LEFT JOIN commands c ON c.transaction_id=e.transaction_id
   AND c.actor_user_id IS NOT DISTINCT FROM e.actor_user_id AND c.actor_type=e.actor_type
   AND c.source=e.source AND c.request_id IS NOT DISTINCT FROM e.request_id
 ) '''

# Prefer the business outcome over the rows changed to produce it. Decisions
# and submissions carry their recorded round/stage; no current job state is
# consulted to interpret the historical action.
PRIORITY = '''CASE
 WHEN operation IN ('DESTRUCTION_JOB_COMPLETED','REVIEW_PROPOSALS_APPROVED','EXTERNAL_APPROVAL_RECORDED','EXTERNAL_REJECTION_RECORDED','PHYSICAL_DESTRUCTION_CONFIRMED','DIGITAL_DESTRUCTION_SUCCEEDED','DISPOSITION_ACCELERATED') THEN 0
 WHEN entity_type='disposition_review_decision' THEN 1
 WHEN entity_type='disposition_review_round' AND operation='REVIEW_SUBMIT' THEN 1
 WHEN entity_type='disposition_job_membership' THEN 2
 WHEN entity_type='disposition_job' AND operation NOT IN ('TASK_ROUTED','DISPOSITION_RECALCULATED') THEN 3
 WHEN NULLIF(metadata->>'command_id','') IS NOT NULL THEN 4 ELSE 5 END'''

SUMMARY_FIELDS = {'task_type','task_state','workflow_stage','current_review_round',
                  'round_number','review_stage','decision','lifecycle_state'}


def compact_summary(row):
    """Do not put entire membership/proposal snapshots on an action-list row.

    Contextual labels need only these recorded scalar facts. Full authorized
    events, including single-event actions, remain in the lazy detail page.
    """
    for field in ('before_state','after_state'):
        if isinstance(row.get(field),dict):
            row[field]={k:v for k,v in row[field].items() if k in SUMMARY_FIELDS}
    metadata=row.get('metadata') or {}
    if metadata.get('redacted'):return
    row['metadata']={key:metadata[key] for key in ('command_id',) if key in metadata}
    for field in ('before','after'):
        if field in metadata:
            value=metadata[field]
            row['metadata'][field]={k:v for k,v in value.items() if k in SUMMARY_FIELDS} if isinstance(value,dict) else None


def page(c, job_id, *, limit, offset, language_tag='en'):
    args=(job_id,)*9
    rows=c.execute(GROUPS+''', ranked AS (
      SELECT *,count(*) OVER (PARTITION BY action_key) action_event_count,
       max(occurred_at) OVER (PARTITION BY action_key) action_occurred_at,
       max(id) OVER (PARTITION BY action_key) action_last_id,
       row_number() OVER (PARTITION BY action_key ORDER BY '''+PRIORITY+''',occurred_at DESC,id DESC) representative
      FROM grouped), selected AS MATERIALIZED (
       SELECT id,action_event_count,action_occurred_at,action_last_id,count(*) OVER () action_total
       FROM ranked WHERE representative=1
       ORDER BY action_occurred_at DESC,action_last_id DESC LIMIT %s OFFSET %s)
      SELECT e.*,p.action_event_count,p.action_occurred_at,p.action_total
      FROM selected p CROSS JOIN LATERAL (
       SELECT * FROM authorized_event_history WHERE id=p.id OFFSET 0
      ) e ORDER BY p.action_occurred_at DESC,p.action_last_id DESC''',(*args,limit,offset)).fetchall()
    total=rows[0]['action_total'] if rows else 0
    # Only a now-empty later page needs a separate count to let PageTable
    # restore the last page after permissions or result membership change.
    if not rows and offset:
        total=c.execute(GROUPS+'SELECT count(DISTINCT action_key) total FROM grouped',args).fetchone()['total']
    for row in rows:
        row['history_group']={'event_count':row.pop('action_event_count')}
        row.pop('action_total')
        compact_summary(row)
    return {'total':total,'items':enrich(c,rows,language_tag)}


def events(c, job_id, event_id, *, limit, offset, language_tag='en'):
    args=(job_id,)*9
    scope=' FROM grouped WHERE action_key=(SELECT action_key FROM grouped WHERE id=%s)'
    rows=c.execute(GROUPS+''', selected AS MATERIALIZED (
      SELECT id,occurred_at,count(*) OVER () action_total'''+scope+''' ORDER BY occurred_at,id LIMIT %s OFFSET %s)
      SELECT e.*,p.action_total FROM selected p CROSS JOIN LATERAL (
       SELECT * FROM authorized_event_history WHERE id=p.id OFFSET 0
      ) e ORDER BY p.occurred_at,p.id''',(*args,event_id,limit,offset)).fetchall()
    total=rows[0]['action_total'] if rows else 0
    if not rows and offset:
        total=c.execute(GROUPS+'SELECT count(*) total'+scope,(*args,event_id)).fetchone()['total']
    if not total:raise HTTPException(404,detail='event not found')
    for row in rows:
        row.pop('action_total')
    return {'total':total,'items':enrich(c,rows,language_tag)}
