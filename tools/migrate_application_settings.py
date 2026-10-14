"""Offline preview/apply/readiness CLI; never writes the selected legacy file."""
import argparse
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import psycopg
from psycopg.rows import dict_row
from backend.services.api.application_settings_migration import (
    MigrationInvalid, apply_preview, preview, readiness, source_values,
)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url',required=True,help='One explicitly selected PostgreSQL database; never printed.')
    parser.add_argument('--source-env',type=Path,required=True,help='Reviewed legacy .env; read only registered active migration keys.')
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--preview',action='store_true');modes.add_argument('--apply',action='store_true');modes.add_argument('--check',action='store_true')
    parser.add_argument('--plan',type=Path,help='Preview output file or reviewed apply input file (contains non-secret values only).')
    parser.add_argument('--actor-user-id',type=int,help='Existing active person with app.settings.manage, required for apply.')
    parser.add_argument('--reason',help='Required governed apply reason.')
    parser.add_argument('--keep-database',action='append',default=[],metavar='KEY',help='Explicitly retain a database value when resolving a conflict/invalid legacy entry in preview.')
    parser.add_argument('--use-legacy',action='append',default=[],metavar='KEY',help='Explicitly replace a configured value through the governed edit path in preview.')
    args=parser.parse_args(argv)
    if (args.preview or args.apply) and not args.plan:parser.error('--plan is required for preview/apply')
    if args.apply and (not args.actor_user_id or not args.reason):parser.error('--actor-user-id and --reason are required for apply')
    if not args.preview and (args.keep_database or args.use_legacy):parser.error('Resolution options belong to the reviewed preview only')
    try:
        if not args.source_env.is_file():raise MigrationInvalid('source_file_missing')
        if args.plan and args.plan.resolve()==args.source_env.resolve():raise MigrationInvalid('plan_cannot_replace_source')
        source=source_values(args.source_env)
        with psycopg.connect(args.database_url,row_factory=dict_row,options='-c timezone=UTC') as connection:
            if args.check or args.preview:connection.execute('SET TRANSACTION READ ONLY')
            if args.check:
                result=readiness(connection,source)
                print(json.dumps(result,ensure_ascii=False,indent=2))
                if not result['ready']:
                    invocation='backend/services/api/.venv/bin/python tools/migrate_application_settings.py'
                    suffix=' --database-url "$DATABASE_URL" --source-env '+shlex.quote(str(args.source_env))+' --plan /tmp/erms-settings-review.json'
                    print('Migration incomplete. Review: '+invocation+' --preview'+suffix,file=sys.stderr)
                    print('Then apply: '+invocation+' --apply'+suffix+' --actor-user-id <authorized-person-id> --reason <reviewed-reason>',file=sys.stderr)
                    return 1
            elif args.preview:
                result=preview(connection,source,keep_database=args.keep_database,use_legacy=args.use_legacy)
                # Exclusive creation prevents overwriting an unrelated file.
                with args.plan.open('x',encoding='utf-8') as output:
                    json.dump(result,output,ensure_ascii=False,indent=2);output.write('\n')
                print(json.dumps(result,ensure_ascii=False,indent=2))
                return 1 if result['issues'] else 0
            else:
                plan=json.loads(args.plan.read_text())
                result=apply_preview(connection,plan,source,user_id=args.actor_user_id,reason=args.reason)
                connection.commit()
                print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (MigrationInvalid,OSError,ValueError,psycopg.Error) as error:
        # Neither driver errors nor source/parser exceptions may expose private
        # data. Registered issue details are only in validated preview output.
        code=str(error) if isinstance(error,MigrationInvalid) else type(error).__name__
        print('Settings migration failed: '+code,file=sys.stderr)
        return 1


if __name__=='__main__':sys.exit(main())
