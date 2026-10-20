"""Dedicated bounded execution process; no browser task owns this work."""
import argparse,json,time
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from ..config import load_environment,required_environment
from ..messaging.notification_registry import initialize_registry
from .destruction import process_one
from .completion import process_one as complete_one


def run_pass(connection,batch_size):
    units=certificates=0
    for _ in range(batch_size):
        if not process_one(connection):break
        units+=1
    for _ in range(batch_size):
        if not complete_one(connection):break
        certificates+=1
    return {'units_processed':units,'certificates_processed':certificates}


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--watch',action='store_true');parser.add_argument('--batch-size',type=int,default=1);parser.add_argument('--interval-seconds',type=int,default=5);args=parser.parse_args(argv)
    if not 1<=args.batch_size<=100 or args.interval_seconds<1:parser.error('Invalid worker bounds')
    load_environment();url=required_environment('DATABASE_URL');initialize_registry()
    @contextmanager
    def connection():
        with psycopg.connect(url,row_factory=dict_row,options='-c timezone=UTC') as c:yield c
    with connection() as c:
        if not c.execute("SELECT 1 FROM schema_migrations WHERE version='071_remove_destruction_release_gates'").fetchone():raise RuntimeError('Apply migration 071 before starting destruction/completion')
    while True:
        try:
            print(json.dumps(run_pass(connection,args.batch_size)),flush=True)
        except Exception:
            print(json.dumps({'error':'disposition_destruction_pass_failed'}),flush=True)
            if not args.watch:return 1
        if not args.watch:return 0
        time.sleep(args.interval_seconds)


if __name__=='__main__':raise SystemExit(main())
