"""Calendar-month eligibility reminders through the existing messaging service."""
import calendar
from datetime import datetime,timezone
from ..messaging.notification_registry import SystemNotificationDefinition,Placeholder
from ..messaging.models import Selector
from ..messaging.notifications import emit_system_notification
from .email import worker_actor

CODE='disposition.eligibility_reminder'


def qualifies(c,identity):
    return c.execute("SELECT disposition_private.governance_person(%s,'INFO_GOV_OFFICER') OR disposition_private.governance_person(%s,'INFO_GOV_MGR') allowed",(identity,identity)).fetchone()['allowed']


def audience(c,context):
    identity=context['recipient_id']
    return [Selector(selector_kind='user',target_id=identity)] if qualifies(c,identity) else []


def definition():
    return SystemNotificationDefinition(producer_code=CODE,feature_code='disposition',event_type='eligibility_reminder',contract_version=1,
      required_for_business_commit=False,allow_static_audience=False,
      placeholders={'recipient_id':Placeholder(type='integer'),'scheduled_interval':Placeholder(type='text')},
      audience_resolvers={'current_governance_person':audience},sample_context={'recipient_id':1,'scheduled_interval':'2026-10-01T00:00:00+00:00'})


def add_months(anchor,months):
    total=anchor.year*12+anchor.month-1+months;year,month=divmod(total,12);month+=1
    return anchor.replace(year=year,month=month,day=min(anchor.day,calendar.monthrange(year,month)[1]))


def run_batch(connection_factory,*,limit=100,now=None):
    if type(limit) is not int or not 1<=limit<=1000:raise ValueError('Invalid reminder batch size')
    # A transaction-scoped session mutex is taken BEFORE the repeatable snapshot
    # on a separate autocommit connection, so overlapping workers observe the
    # winner's committed checkpoint rather than a stale pre-lock snapshot.
    with connection_factory() as c:
        c.autocommit=True
        if not c.execute('SELECT pg_try_advisory_lock(7362,1) locked').fetchone()['locked']:return {'sent':0,'busy':True}
        try:
            c.autocommit=False;c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE');worker_actor(c)
            at=now or c.execute('SELECT clock_timestamp() at').fetchone()['at']
            if at.tzinfo is None:raise ValueError('Reminder clock must be timezone aware')
            at=at.astimezone(timezone.utc)
            setting=c.execute("SELECT value,version FROM application_settings WHERE key='DISPOSITION_DESTRUCTION_REMINDER_MONTHS'").fetchone()
            months=int(setting['value']);state=c.execute('SELECT * FROM disposition_private.reminder_schedule WHERE producer_code=%s FOR UPDATE',(CODE,)).fetchone()
            if not state or (state['months'],state['setting_version'])!=(months,setting['version']):
                c.execute('''INSERT INTO disposition_private.reminder_schedule(producer_code,anchor_at,months,setting_version) VALUES(%s,%s,%s,%s)
                    ON CONFLICT(producer_code) DO UPDATE SET anchor_at=EXCLUDED.anchor_at,months=EXCLUDED.months,setting_version=EXCLUDED.setting_version,interval_index=1,recipient_after=0''',(CODE,at,months,setting['version']));c.commit();return {'sent':0,'rescheduled':True}
            due=add_months(state['anchor_at'],months*state['interval_index'])
            if due>at:c.commit();return {'sent':0}
            # Skip missed old intervals; do not flood after downtime or replay
            # old schedules after a configuration change.
            latest=max(state['interval_index'],((at.year-state['anchor_at'].year)*12+at.month-state['anchor_at'].month)//months)
            while add_months(state['anchor_at'],months*latest)>at:latest-=1
            if latest!=state['interval_index']:state.update(interval_index=latest,recipient_after=0);due=add_months(state['anchor_at'],months*latest)
            enabled=c.execute('''SELECT EXISTS(SELECT 1 FROM system_notification_producers p JOIN system_notification_configuration_versions v ON v.id=p.active_configuration_version_id WHERE p.producer_code=%s AND v.enabled) allowed''',(CODE,)).fetchone()['allowed']
            exists=c.execute('SELECT EXISTS(SELECT 1 FROM aggregations WHERE parent_aggregation_id IS NULL AND disposition_status=2) allowed').fetchone()['allowed']
            rows=[];sent=0
            if enabled and exists:
                rows=c.execute("""SELECT u.id FROM users u WHERE u.id>%s AND u.status='active' AND u.account_type='person'
                   AND (disposition_private.governance_person(u.id,'INFO_GOV_OFFICER') OR disposition_private.governance_person(u.id,'INFO_GOV_MGR')) ORDER BY u.id LIMIT %s""",(state['recipient_after'],limit)).fetchall()
                for row in rows:
                    identity=row['id']
                    if c.execute('SELECT 1 FROM disposition_private.reminder_checkpoints WHERE producer_code=%s AND scheduled_at=%s AND recipient_user_id=%s',(CODE,due,identity)).fetchone():continue
                    result=emit_system_notification(transaction=c,producer_code=CODE,source_event_id=f'{due.isoformat()}:{identity}',context={'recipient_id':identity,'scheduled_interval':due.isoformat()})
                    if result.status in ('created','existing','message_result_purged'):
                        c.execute('INSERT INTO disposition_private.reminder_checkpoints(producer_code,scheduled_at,recipient_user_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',(CODE,due,identity));sent+=1
            finished=len(rows)<limit
            c.execute('UPDATE disposition_private.reminder_schedule SET interval_index=%s,recipient_after=%s WHERE producer_code=%s',(state['interval_index']+int(finished),0 if finished else rows[-1]['id'],CODE))
            c.commit();return {'sent':sent,'more':not finished,'scheduled_at':due.isoformat()}
        except BaseException:c.rollback();raise
        finally:
            c.autocommit=True;c.execute('SELECT pg_advisory_unlock(7362,1)')
