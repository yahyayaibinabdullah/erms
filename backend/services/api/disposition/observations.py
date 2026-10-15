"""Immutable detection evidence, never a saved authority for the blocked state.

The job reader calls this for its bounded page of current members. In particular,
a time-activated hold is recorded on first detection, without a state transition.
The existing whole-job event projection protects hidden descendant identities.
"""
from psycopg.types.json import Jsonb


def detect(c, job_id, root_id):
    # Serialize only observation writers for this root. Business commands retain
    # their existing resource/hold locks and independently check current facts.
    c.execute("SELECT pg_advisory_xact_lock(hashtextextended('disposition-observation/'||%s::text,0))",(root_id,))
    if not c.execute("""SELECT 1 FROM disposition_job_memberships m JOIN aggregations a ON a.id=m.root_aggregation_id
      WHERE m.job_id=%s AND m.root_aggregation_id=%s AND m.membership_state='active'
      AND a.disposition_status BETWEEN 6 AND 9""",(job_id,root_id)).fetchone():return
    facts=c.execute('''SELECT COALESCE(bool_or(is_vital),false) vital,
       COALESCE(bool_or(security_blocked),false) security,
       COALESCE(bool_or(cardinality(hold_ids)>0),false) held,
       md5(COALESCE(string_agg(resource_kind||':'||resource_id||':'||is_vital||':'||security_blocked||':'||hold_ids::text,',' ORDER BY resource_kind,resource_id),'')) signature
       FROM disposition_private.protection_blockers(%s)''',(root_id,)).fetchone()
    relationships=c.execute('''SELECT count(*)>0 blocked,md5(COALESCE(string_agg(resource_kind||':'||relationship_id,',' ORDER BY resource_kind,relationship_id),'')) signature
       FROM disposition_private.relationship_scope(%s) WHERE blocks_final''',(root_id,)).fetchone()
    signature=facts.pop('signature')+relationships['signature']
    previous=c.execute("""SELECT metadata FROM event_history WHERE entity_type='disposition_job' AND entity_id=%s
       AND operation IN ('DISPOSITION_BLOCKERS_DETECTED','DISPOSITION_BLOCKERS_RESOLVED')
       AND metadata->>'root_aggregation_id'=%s ORDER BY id DESC LIMIT 1""",(job_id,str(root_id))).fetchone()
    blocked=any(facts.values()) or relationships['blocked']
    if previous and previous['metadata'].get('signature')==signature:return
    if not previous and not blocked:return
    metadata={**facts,'relationships':relationships['blocked'],'root_aggregation_id':root_id,
              'job_id':job_id,'signature':signature}
    c.execute('SELECT append_domain_event(%s,%s,%s,%s,%s)',('disposition_job',job_id,
       'DISPOSITION_BLOCKERS_DETECTED' if blocked else 'DISPOSITION_BLOCKERS_RESOLVED',
       Jsonb(metadata),'Detected current disposition blocker facts'))
