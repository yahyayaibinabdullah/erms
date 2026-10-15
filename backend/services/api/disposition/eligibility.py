"""Bounded, repeatable scheduled eligibility work; no final-action capability."""
from __future__ import annotations

import argparse
import json
import time
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from ..config import load_environment, required_environment


def worker_actor(connection):
    connection.execute("""SELECT set_config('app.user_id','',true),
      set_config('app.actor_type','automated_process',true),
      set_config('app.actor_name','Disposition eligibility service',true),
      set_config('app.actor_email','',true),set_config('app.event_source','background_service',true)""")


def evaluate_root(connection, root_id: int, *, command_id=None):
    """Evaluate using the database clock and rules on this transaction only."""
    return connection.execute('SELECT disposition_private.evaluate_root(%s,%s) AS result',
                              (root_id, command_id or uuid4())).fetchone()['result']


def run_pass(database_url: str, *, batch_size: int = 100, after_id: int = 0):
    if type(batch_size) is not int or not 1 <= batch_size <= 1000 or type(after_id) is not int or after_id < 0:
        raise ValueError('Invalid eligibility batch bounds')
    with psycopg.connect(database_url, row_factory=dict_row, options='-c timezone=UTC') as connection:
        if not connection.execute("SELECT 1 FROM schema_migrations WHERE version='054_disposition_eligibility'").fetchone():
            raise RuntimeError('Apply disposition migration 054 before starting eligibility work')
        candidates=connection.execute('''SELECT id FROM aggregations WHERE parent_aggregation_id IS NULL
          AND disposition_status=1 AND date_closed IS NOT NULL AND id>%s ORDER BY id LIMIT %s''',
          (after_id,batch_size)).fetchall()
    result={'examined':len(candidates),'changed':0,'unchanged':0,'failures':[],
            'next_after_id':candidates[-1]['id'] if len(candidates)==batch_size else 0}
    # A fresh transaction for each root gives failures independent rollback and
    # the next root a fresh database clock/snapshot. No batch-long business lock.
    for candidate in candidates:
        root_id=candidate['id']
        for attempt in range(3):
            try:
                with psycopg.connect(database_url,row_factory=dict_row,options='-c timezone=UTC') as connection:
                    worker_actor(connection)
                    outcome=evaluate_root(connection,root_id)
                result['changed' if outcome['changed'] else 'unchanged']+=1
                break
            except (psycopg.errors.DeadlockDetected,psycopg.errors.SerializationFailure) as error:
                if attempt<2:
                    continue
                result['failures'].append({'root_id':root_id,'sqlstate':error.sqlstate})
            except psycopg.Error as error:
                # An internal worker result can identify its failed root, but
                # neither credentials nor raw SQL error values go into logs.
                result['failures'].append({'root_id':root_id,'sqlstate':error.sqlstate})
                break
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description='Evaluate a bounded batch of disposition roots')
    parser.add_argument('--batch-size',type=int,default=100)
    parser.add_argument('--after-id',type=int,default=0)
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--interval-seconds',type=int,default=60)
    args=parser.parse_args(argv)
    if not 1<=args.batch_size<=1000 or args.after_id<0 or args.interval_seconds<1:
        parser.error('Batch size must be 1–1000; cursor nonnegative; interval positive')
    load_environment()
    database_url=required_environment('DATABASE_URL')
    cursor=args.after_id
    while True:
        result=run_pass(database_url,batch_size=args.batch_size,after_id=cursor)
        print(json.dumps(result),flush=True)
        if not args.watch:
            return 1 if result['failures'] else 0
        cursor=result['next_after_id']
        time.sleep(args.interval_seconds)


if __name__=='__main__':
    raise SystemExit(main())
