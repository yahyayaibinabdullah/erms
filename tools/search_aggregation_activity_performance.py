"""AFD-5: scope and authorize before the cap, using the shared search fixture."""
from datetime import datetime, timezone
import json
import time

from backend.services.api.recent_activity import AGGREGATION_RECORD_ACTIVITY
from backend.services.api.search_execution import search_sql_execution


def exercise(client, connection, output, repeats, identity):
    since = datetime(2023, 1, 1, tzinfo=timezone.utc)
    user = connection.execute('SELECT id FROM users WHERE email=%s', (identity+'@performance.invalid',)).fetchone()['id']
    failures, results = [], []
    for label, aggregation_id in [('broad',1),('selective',500),('empty',999999)]:
        expected = connection.execute('''
            SELECT event.entity_id,event.id,event.occurred_at FROM event_history event
            JOIN records record ON record.id=event.entity_id
            WHERE event.entity_type='record' AND event.operation='CREATE'
              AND event.actor_user_id=%s AND record.aggregation_id=%s
            ORDER BY event.occurred_at DESC,event.id DESC LIMIT 50
        ''', (user, aggregation_id)).fetchall() if identity=='reader' else []
        expected_ids = [r['entity_id'] for r in sorted(expected, key=lambda r:r['entity_id'])]
        samples=[]
        for _ in range(repeats):
            start=time.perf_counter()
            response=client.get('/api/v1/auth/me/recent-activity',params={
                'entity_type':'record','aggregation_id':aggregation_id,'since':since.isoformat(),'limit':50,
            })
            elapsed=time.perf_counter()-start
            assert response.status_code==200,response.text
            rows=response.json()
            assert [r['entity_id'] for r in rows]==expected_ids,(identity,label,rows,expected_ids)
            assert all(r['operation']=='CREATE' and 'created_by' in r for r in rows)
            samples.append(elapsed)
            if elapsed>3:failures.append(dict(identity=identity,case='aggregation_activity_'+label,seconds=elapsed))
        connection.execute("SELECT set_config('app.user_id',%s,true)",(str(user),))
        with search_sql_execution(connection):
            plan=connection.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+AGGREGATION_RECORD_ACTIVITY,
                                    (aggregation_id,user,since,user,since,50)).fetchone()['QUERY PLAN']
        (output/f'activity-{identity}-{label}-plan.json').write_text(json.dumps(plan,indent=2))
        connection.commit()
        results.append(dict(identity=identity,scope=label,aggregation_id=aggregation_id,expected_ids=expected_ids,
                            count=len(expected_ids),samples_seconds=samples))
        print(json.dumps(results[-1]),flush=True)
    (output/f'activity-{identity}.json').write_text(json.dumps(results,indent=2))
    return failures
