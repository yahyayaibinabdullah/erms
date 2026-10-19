"""Task availability uses the existing atomic messaging service and receipts.

No job title, resource names or protected content enter a notification. The
inbox/workspace link presentation is owned by Phase 16. Administrators activate
this optional producer through the existing notification administration flow.
"""
from ..messaging.notification_registry import SystemNotificationDefinition, Placeholder
from ..messaging.models import Selector
from ..messaging.config import LIMITS
from ..messaging.notifications import emit_system_notification

ASSIGNED = 'disposition.task_assigned'


def audience(c, context):
    return [Selector(selector_kind='user',target_id=row['id']) for row in c.execute('''
      SELECT u.id FROM users u JOIN disposition_tasks t ON t.id=%s
      WHERE t.task_state IN ('open','claimed')
      AND (t.claimed_by_user_id IS NULL OR t.claimed_by_user_id=u.id)
      AND disposition_private.task_eligible(u.id,t.id)
      ORDER BY u.id LIMIT %s''', (context['task_id'],LIMITS['MAX_SELECTORS_PER_SEND']+1)).fetchall()]


def definitions():
    return (SystemNotificationDefinition(
        producer_code=ASSIGNED,feature_code='disposition',event_type='task_assigned',
        contract_version=1,required_for_business_commit=False,allow_static_audience=False,
        placeholders={'task_id':Placeholder(type='integer')},
        audience_resolvers={'current_eligible_task_recipients':audience},
        sample_context={'task_id':1},
    ),)


def publish_command_tasks(c, command_id=None):
    """Called before finish_command: exact business/event/message commit boundary.

    Committed command retries never enter this function. Source event IDs and
    messaging receipts also prevent duplicate deliveries after an outer retry.
    Disabled/unconfigured producers are dormant; configured send failures roll
    back the business transaction. No unbounded audience or history download.
    """
    if not c.execute('SELECT 1 FROM system_notification_producers WHERE producer_code=%s AND active_configuration_version_id IS NOT NULL',(ASSIGNED,)).fetchone():
        return
    # A command can route a bounded number of role tasks. Consume only its final
    # availability event for each task; a claim alone produces no assignment.
    rows=c.execute('''SELECT DISTINCT ON (e.entity_id) e.id,e.entity_id FROM event_history e
      JOIN disposition_tasks t ON t.id=e.entity_id
      WHERE e.metadata->>'command_id'=COALESCE(%s::text,(SELECT command_id::text FROM disposition_private.command_context WHERE transaction_id=txid_current())) AND e.entity_type='disposition_task'
      AND t.task_state IN ('open','claimed') AND e.operation IN ('JOB_CREATE','JOB_ASSIGN','REVIEW_SUBMIT','REVIEW_DECIDE','TASK_RELEASE','TASK_REASSIGN')
      ORDER BY e.entity_id,e.id DESC''',(str(command_id) if command_id is not None else None,)).fetchall()
    for row in rows:
        emit_system_notification(transaction=c,producer_code=ASSIGNED,source_event_id=str(row['id']),
          context={'task_id':row['entity_id']},triggered_by_user_id=c.execute('SELECT current_user_id() id').fetchone()['id'])
