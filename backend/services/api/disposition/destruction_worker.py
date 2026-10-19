"""Dedicated bounded execution process; no browser task owns this work."""
import argparse,json,time
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from ..config import load_environment,required_environment
from ..messaging.notification_registry import initialize_registry
from .destruction import process_one


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--watch',action='store_true');parser.add_argument('--batch-size',type=int,default=1);parser.add_argument('--interval-seconds',type=int,default=5);args=parser.parse_args(argv)
    if not 1<=args.batch_size<=100 or args.interval_seconds<1:parser.error('Invalid worker bounds')
    load_environment();url=required_environment('DATABASE_URL');initialize_registry()
    @contextmanager
    def connection():
        with psycopg.connect(url,row_factory=dict_row,options='-c timezone=UTC') as c:yield c
    with connection() as c:
        if not c.execute("SELECT 1 FROM schema_migrations WHERE version='068_disposition_retained_records'").fetchone():raise RuntimeError('Apply migrations066–068 before starting destruction')
    while True:
        completed=0
        try:
            for _ in range(args.batch_size):
                if not process_one(connection):break
                completed+=1
            print(json.dumps({'units_processed':completed}),flush=True)
        except Exception:
            print(json.dumps({'error':'disposition_destruction_pass_failed'}),flush=True)
            if not args.watch:return 1
        if not args.watch:return 0
        time.sleep(args.interval_seconds)


if __name__=='__main__':raise SystemExit(main())
