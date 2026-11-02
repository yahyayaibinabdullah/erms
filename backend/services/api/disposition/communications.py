"""Bounded external-email and reminder worker, independent of browser lifetime."""
import argparse,json,time
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from ..config import load_environment,required_environment
from ..messaging.notification_registry import initialize_registry
from . import email,reminders


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--watch',action='store_true');parser.add_argument('--batch-size',type=int,default=100);parser.add_argument('--interval-seconds',type=int,default=30);args=parser.parse_args(argv)
    if not 1<=args.batch_size<=1000 or args.interval_seconds<1:parser.error('Invalid worker bounds')
    load_environment();url=required_environment('DATABASE_URL');initialize_registry()
    @contextmanager
    def connection():
        with psycopg.connect(url,row_factory=dict_row,options='-c timezone=UTC') as c:yield c
    with connection() as c:
        if not c.execute("SELECT 1 FROM schema_migrations WHERE version='063_disposition_communications'").fetchone():raise RuntimeError('Apply migration 063 before starting communications')
    while True:
        sent=0
        try:
            for _ in range(args.batch_size):
                if not email.process_one(connection):break
                sent+=1
            result=reminders.run_batch(connection,limit=args.batch_size)
            print(json.dumps({'email_attempts_processed':sent,'reminders':result}),flush=True)
        except Exception:
            # Never print raw database/SMTP exceptions or configuration values.
            print(json.dumps({'error':'disposition_communications_pass_failed'}),flush=True)
            if not args.watch:return 1
        if not args.watch:return 0
        time.sleep(args.interval_seconds)


if __name__=='__main__':raise SystemExit(main())
