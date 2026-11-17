"""Best-effort disposition notices through the existing messaging service."""
import logging

from ..messaging import notification_registry
from ..messaging.notification_registry import SystemNotificationDefinition, Placeholder
from ..messaging.models import Selector
from ..messaging.config import LIMITS
from ..messaging.notifications import emit_system_notification

ASSIGNED = 'disposition.task_assigned'
DESTRUCTION_OUTCOME='disposition.destruction_outcome'
COMPLETION_OUTCOME='disposition.completion_outcome'
OPERATION_OUTCOME='disposition.operation_outcome'

logger = logging.getLogger(__name__)


def try_notification(c, code, send, /, *args, **kwargs):
    """Discard a failed optional send and its partial messaging writes."""
    definition = notification_registry.registry.definitions.get(code)
    if definition and definition.required_for_business_commit:
        return send(*args, **kwargs)
    try:
        with c.transaction():
            result = send(*args, **kwargs)
            # The envelope and receipt require all fan-out rows before validation.
            # Surface deferred failures while the notification savepoint is open.
            c.execute('SET CONSTRAINTS ALL IMMEDIATE')
            c.execute('SET CONSTRAINTS ALL DEFERRED')
    except Exception:
        logger.exception('Could not publish optional disposition notification %s', code)
        return None
    return result


def audience(c, context):
    return [Selector(selector_kind='user',target_id=row['id']) for row in c.execute('''
      SELECT u.id FROM users u JOIN disposition_tasks t ON t.id=%s
      WHERE t.task_state IN ('open','claimed')
      AND (t.claimed_by_user_id IS NULL OR t.claimed_by_user_id=u.id)
      AND disposition_private.task_eligible(u.id,t.id)
      ORDER BY u.id LIMIT %s''', (context['task_id'],LIMITS['MAX_SELECTORS_PER_SEND']+1)).fetchall()]


def destruction_audience(c,context):
    return [Selector(selector_kind='user',target_id=row['id']) for row in c.execute("""SELECT DISTINCT u.id FROM users u JOIN disposition_tasks t ON disposition_private.task_eligible(u.id,t.id)
      JOIN disposition_destruction_runs r ON r.job_id=t.job_id WHERE r.id=%s AND t.task_type='digital_destruction' AND t.task_state IN ('open','claimed') ORDER BY u.id LIMIT %s""",(context['run_id'],LIMITS['MAX_SELECTORS_PER_SEND']+1)).fetchall()]


def completion_audience(c,context):
    return [Selector(selector_kind='user',target_id=row['id']) for row in c.execute('''SELECT DISTINCT u.id FROM users u JOIN user_role_assignments a ON a.user_id=u.id
      WHERE disposition_private.person_role(u.id,a.role_id) AND disposition_private.review_role(%s,'records_manager_review',a.role_id)
      AND disposition_private.can_review_content(u.id,%s) ORDER BY u.id LIMIT %s''',(context['job_id'],context['job_id'],LIMITS['MAX_SELECTORS_PER_SEND']+1)).fetchall()]



def operation_audience(c,context):
    return [Selector(selector_kind='user',target_id=row['requested_by_user_id']) for row in c.execute("""SELECT DISTINCT w.requested_by_user_id FROM disposition_private.operation_work w
      WHERE w.id=%s::uuid AND disposition_private.person_role(w.requested_by_user_id,w.acting_role_id)
      AND disposition_private.review_role(w.job_id,'records_manager_review',w.acting_role_id)
      AND disposition_private.can_review_content(w.requested_by_user_id,w.job_id)""",(context['operation_id'],)).fetchall()]


def definitions():
    from .reminders import definition

    job_producers = (
        (ASSIGNED, 'current_eligible_task_recipients', audience, {'task_id': 1}),
        (DESTRUCTION_OUTCOME, 'current_eligible_managers', destruction_audience, {'run_id': 1}),
        (COMPLETION_OUTCOME, 'current_eligible_managers', completion_audience, {'job_id': 1}),
        (OPERATION_OUTCOME, 'requesting_managers', operation_audience,
         {'job_id': 1, 'operation_id': '00000000-0000-0000-0000-000000000001'}),
    )
    return tuple(
        SystemNotificationDefinition(
            producer_code=code,
            feature_code='disposition',
            event_type=code.split('.', 1)[1],
            contract_version=2,
            required_for_business_commit=False,
            allow_static_audience=False,
            placeholders={
                **{key: Placeholder(type='integer' if isinstance(value, int) else 'text')
                   for key, value in event_sample.items()},
                'job_number': Placeholder(type='text'),
            },
            audience_resolvers={mode: resolver},
            sample_context={**event_sample, 'job_number': 'DT-2026-1'},
            display_only_placeholders=frozenset({'job_number'}),
        )
        for code, mode, resolver, event_sample in job_producers
    ) + (definition(),)


def publish_command_tasks(c, command_id):
    """Publish each optional producer independently within the command transaction."""
    try_notification(c, DESTRUCTION_OUTCOME, publish_destruction_outcomes, c)
    try_notification(c, COMPLETION_OUTCOME, publish_completion_outcomes, c)
    try_notification(c, ASSIGNED, publish_assignments, c, command_id)


def publish_assignments(c, command_id):
    if not c.execute('SELECT 1 FROM system_notification_producers WHERE producer_code=%s AND active_configuration_version_id IS NOT NULL',(ASSIGNED,)).fetchone():
        return
    # A command can route a bounded number of role tasks. Consume only its final
    # availability event for each task; a claim alone produces no assignment.
    rows=c.execute('''SELECT DISTINCT ON (e.entity_id) e.id,e.entity_id,j.job_number,current_user_id() actor_id FROM event_history e
      JOIN disposition_tasks t ON t.id=e.entity_id
      JOIN disposition_jobs j ON j.id=t.job_id
      WHERE e.metadata->>'command_id'=%s AND e.entity_type='disposition_task'
      AND t.task_state IN ('open','claimed') AND e.operation IN ('JOB_CREATE','JOB_ASSIGN','REVIEW_SUBMIT','REVIEW_DECIDE','TASK_RELEASE','TASK_REASSIGN','FINAL_COMPLETE')
      ORDER BY e.entity_id,e.id DESC''',(str(command_id),)).fetchall()
    for row in rows:
        emit_system_notification(transaction=c,producer_code=ASSIGNED,source_event_id=str(row['id']),
          context={'task_id':row['entity_id'],'job_number':row['job_number']},triggered_by_user_id=row['actor_id'])


def publish_destruction_outcomes(c,run_id=None):
    if not c.execute('SELECT 1 FROM system_notification_producers WHERE producer_code=%s AND active_configuration_version_id IS NOT NULL',(DESTRUCTION_OUTCOME,)).fetchone():return
    # Immutable source event identity + notification receipts deduplicate this
    # outcome. Ordinary running/count updates never send repetitive messages.
    rows=c.execute("""WITH outcomes AS MATERIALIZED (
        SELECT id,(metadata->>'run_id')::bigint AS run_id FROM event_history
        WHERE entity_type='disposition_job' AND operation IN ('DIGITAL_DESTRUCTION_FAILED','DIGITAL_DESTRUCTION_SUCCEEDED')
        AND ((%s::bigint IS NOT NULL AND metadata->>'run_id'=%s::text) OR (%s::bigint IS NULL AND transaction_id=txid_current()))
      )
      SELECT e.id,e.run_id,r.requested_by_user_id,j.job_number FROM outcomes e
      JOIN disposition_destruction_runs r ON r.id=e.run_id
      JOIN disposition_jobs j ON j.id=r.job_id ORDER BY e.id""",(run_id,run_id,run_id)).fetchall()
    for row in rows:emit_system_notification(transaction=c,producer_code=DESTRUCTION_OUTCOME,source_event_id=str(row['id']),context={'run_id':row['run_id'],'job_number':row['job_number']},triggered_by_user_id=row['requested_by_user_id'])


def publish_completion_outcomes(c,job_id=None):
    if not c.execute('SELECT 1 FROM system_notification_producers WHERE producer_code=%s AND active_configuration_version_id IS NOT NULL',(COMPLETION_OUTCOME,)).fetchone():return
    rows=c.execute("""SELECT e.id,e.entity_id,e.actor_user_id,j.job_number FROM event_history e
      JOIN disposition_jobs j ON j.id=e.entity_id
      WHERE e.entity_type='disposition_job' AND e.operation IN ('DESTRUCTION_JOB_COMPLETED','DIGITAL_CERTIFICATE_FAILED')
      AND ((%s::bigint IS NOT NULL AND e.entity_id=%s) OR (%s::bigint IS NULL AND e.transaction_id=txid_current())) ORDER BY e.id""",(job_id,job_id,job_id)).fetchall()
    for row in rows:emit_system_notification(transaction=c,producer_code=COMPLETION_OUTCOME,source_event_id=str(row['id']),context={'job_id':row['entity_id'],'job_number':row['job_number']},triggered_by_user_id=row['actor_user_id'])


def publish_operation_outcomes(c,operation_id):
    if not c.execute('SELECT 1 FROM system_notification_producers WHERE producer_code=%s AND active_configuration_version_id IS NOT NULL',(OPERATION_OUTCOME,)).fetchone():return False
    if not operation_audience(c,{'operation_id':str(operation_id)}):return True
    rows=c.execute("""SELECT e.id,w.job_id,w.requested_by_user_id,j.job_number FROM event_history e
      JOIN disposition_private.operation_work w ON e.metadata->>'operation_id'=w.id::text
      JOIN disposition_jobs j ON j.id=w.job_id
      WHERE w.id=%s AND e.operation IN ('DISPOSITION_OPERATION_READY','DISPOSITION_OPERATION_FAILED')
      ORDER BY e.id""",(operation_id,)).fetchall()
    for row in rows:emit_system_notification(transaction=c,producer_code=OPERATION_OUTCOME,source_event_id=str(row['id']),context={'job_id':row['job_id'],'operation_id':str(operation_id),'job_number':row['job_number']},triggered_by_user_id=row['requested_by_user_id'])
    return True
