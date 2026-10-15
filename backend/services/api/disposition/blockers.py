"""Current blocker facts, with bounded person-facing projections.

The raw SQL helpers remain private. These queries do not mutate membership,
approvals or resources and never resume an action. Admission/final command
phases must recheck their corresponding facts under their transaction locks.
"""
from fastapi import HTTPException

from ..holds import _visibility_sql as hold_visibility_sql
from ..resource_authorization import require_global


def _require_root(connection,root_id):
    require_global(connection,'disposition.jobs.manage')
    if not connection.execute('SELECT disposition_private.can_manage() allowed').fetchone()['allowed']:
        raise HTTPException(403,detail={'code':'insufficient_privilege'})
    if not connection.execute('SELECT 1 FROM aggregations WHERE id=%s AND parent_aggregation_id IS NULL AND current_user_can_view_aggregation(id)',(root_id,)).fetchone():
        raise HTTPException(404,detail='aggregation not found')


def summary(connection,root_id):
    _require_root(connection,root_id)
    return connection.execute('''WITH facts AS (SELECT
      EXISTS(SELECT 1 FROM disposition_private.protection_blockers(%s)) AS blocks_admission,
      EXISTS(SELECT 1 FROM disposition_private.relationship_scope(%s) WHERE blocks_final) AS relationships_block_final)
      SELECT *,blocks_admission OR relationships_block_final AS blocks_final FROM facts''',
      (root_id,root_id)).fetchone()


def protection_page(connection,root_id,*,limit=25,offset=0):
    _require_root(connection,root_id)
    if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0:
        raise ValueError('Invalid blocker page bounds')
    rows=connection.execute('''SELECT b.*,
     CASE WHEN resource_kind='aggregation' THEN current_user_can_view_aggregation(resource_id)
      ELSE current_user_can_view_record(resource_id) END AS visible
     FROM disposition_private.protection_blockers(%s) b
     ORDER BY resource_kind,resource_id LIMIT %s OFFSET %s''',
     (root_id,limit+1,offset)).fetchall()
    # Hold metadata is separately protected even when its resource is visible.
    ids=sorted({hid for r in rows[:limit] if r['visible'] for hid in r['hold_ids'][:25]})
    holds={r['id']:{'id':r['id'],'code':r['code'],'name':r['name']} for r in connection.execute(
     f'SELECT hold.id,hold.code,hold.name FROM holds hold WHERE hold.id=ANY(%s::bigint[]) AND {hold_visibility_sql()}',(ids,)).fetchall()} if ids else {}
    items=[]
    for r in rows[:limit]:
        items.append({'resource_kind':r['resource_kind'],'resource_id':r['resource_id'] if r['visible'] else None,
          'redacted':not r['visible'],'is_vital':r['is_vital'],'security_blocked':r['security_blocked'],
          'legal_hold':bool(r['hold_ids']),
          'holds':[holds[hid] for hid in r['hold_ids'][:25] if hid in holds] if r['visible'] else [],
          'holds_has_more':r['visible'] and len(r['hold_ids'])>25})
    return {'items':items,'has_more':len(rows)>limit}



def relationship_page(connection,root_id,*,limit=25,offset=0):
    _require_root(connection,root_id)
    if type(limit) is not int or not 1<=limit<=100 or type(offset) is not int or offset<0:
        raise ValueError('Invalid relationship page bounds')
    rows=connection.execute('''SELECT l.*,
      CASE WHEN resource_kind='aggregation' THEN current_user_can_view_aggregation(source_id) ELSE current_user_can_view_record(source_id) END source_visible,
      CASE WHEN resource_kind='aggregation' THEN current_user_can_view_aggregation(target_id) ELSE current_user_can_view_record(target_id) END target_visible
      FROM disposition_private.relationship_scope(%s) l
      ORDER BY resource_kind,relationship_id LIMIT %s OFFSET %s''',(root_id,limit+1,offset)).fetchall()
    items=[]
    for r in rows[:limit]:
        visible=r['source_visible'] and r['target_visible']
        items.append({'resource_kind':r['resource_kind'],'relationship_id':r['relationship_id'] if visible else None,
         'relationship_type_id':r['relationship_type_id'] if visible else None,
         'source_id':r['source_id'] if r['source_visible'] else None,'target_id':r['target_id'] if r['target_visible'] else None,
         'redacted':not visible,'is_internal':r['is_internal'],'is_same_job':r['is_same_job'],'blocks_final':r['blocks_final']})
    return {'items':items,'has_more':len(rows)>limit}


def locked_summary(connection,root_id):
    """Current action facts locked until caller commit; this executes no action.

    The protected action service supplies stage/evidence/approval/version gates.
    Recheck authorization after waiting for locks, then read current facts.
    """
    _require_root(connection,root_id)
    connection.execute('SELECT disposition_private.lock_current_blockers(%s)',(root_id,))
    return summary(connection,root_id)
