"""Current acceleration provenance for a bounded set of visible governing roots."""

from ..entity_localization import localized_projection

def current_accelerations(connection, root_ids, language_tag='en'):
    """One indexed lookup per page root in one query; no operational cache.

    Reopening or a changed effective rule ends the acceleration episode. An
    explicitly unchanged-rule recalculation preserves it. Immutable actor and
    reason snapshots also support accelerations recorded before this display.
    """
    if not root_ids:
        return {}
    rows = connection.execute(
        """SELECT roots.id AS root_id, e.*, u.translations AS actor_translations
           FROM unnest(%s::bigint[]) AS roots(id)
           CROSS JOIN LATERAL (
               SELECT e.id AS event_id, e.operation, e.occurred_at, e.actor_name, e.actor_user_id, e.reason
               FROM event_history e
               WHERE e.entity_type='aggregation' AND e.entity_id=roots.id
                 AND (e.operation IN ('DISPOSITION_ACCELERATED','DISPOSITION_REOPENED')
                      OR (e.operation='DISPOSITION_RECALCULATED'
                          AND e.metadata->>'effective_rule_unchanged' IS DISTINCT FROM 'true'))
               ORDER BY e.occurred_at DESC, e.id DESC LIMIT 1
           ) e
           LEFT JOIN users u ON u.id=e.actor_user_id
           WHERE current_user_can_view_aggregation(roots.id)""",
        (list(dict.fromkeys(root_ids)),),
    ).fetchall()
    result = {}
    for event in rows:
        root_id = event.pop('root_id')
        event.pop('actor_user_id')
        event['actor_name'] = localized_projection(
            {'name': event['actor_name'], 'translations': event.pop('actor_translations')},
            language_tag, 'name')['name']
        if event.pop('operation') == 'DISPOSITION_ACCELERATED':
            result[root_id] = event
    return result
