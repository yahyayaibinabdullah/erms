"""Verify consolidation in two owned disposable PostgreSQL databases, then drop both.

Use a backup of a migration-built database as the independent reference. Both
disposable databases inherit its explicit locale settings. The historical Git
mode remains available for comparisons with a deliberately selected old schema.
Only pg_dump client boilerplate and PostgreSQL's associative Boolean deparsing
are normalized. Object names, visible column order, function bodies and grants
remain in the comparison. Persistent databases are never used as test targets.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from psycopg.rows import dict_row
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.canonical_schema import assert_canonical
from tools.initialize_database import initialize

SCHEMAS=('public','disposition_private')
VOLATILE_COLUMNS=['date_created','date_updated','applied_at','database_id']


def archive_locale(create_sql):
    """Read only PostgreSQL's quoted locale options, never execute archive CREATE DATABASE."""
    match = re.search(r'^CREATE DATABASE .+? WITH TEMPLATE = template0 (.+);$', create_sql, re.M)
    if not match:
        raise ValueError('Archive must contain PostgreSQL CREATE DATABASE metadata')
    options = match[1]
    provider = re.search(r'\bLOCALE_PROVIDER = (libc|icu|builtin)\b', options)
    if not provider:
        raise ValueError('Archive has no explicit supported locale provider')
    values = {'provider': provider[1]}
    for key in ('ENCODING', 'LOCALE', 'LC_COLLATE', 'LC_CTYPE', 'ICU_LOCALE', 'ICU_RULES', 'BUILTIN_LOCALE'):
        value = re.search(r"\b" + key + r" = '((?:[^']|'')*)'", options)
        if value:
            values[key.lower()] = value[1].replace("''", "'")
    if 'encoding' not in values:
        raise ValueError('Archive has no explicit database encoding')
    required = {'libc': ('locale','lc_collate'), 'icu': ('icu_locale',), 'builtin': ('builtin_locale',)}[values['provider']]
    if not any(key in values for key in required):
        raise ValueError('Archive is missing its provider locale')
    return values


def create_database_statement(name, locale):
    provider = locale['provider']
    if provider not in ('libc','icu','builtin'):
        raise ValueError('Unsupported locale provider')
    statement = sql.SQL('CREATE DATABASE {} WITH TEMPLATE template0 LOCALE_PROVIDER {}').format(
        sql.Identifier(name), sql.SQL(provider))
    for key in ('encoding','locale','lc_collate','lc_ctype','icu_locale','icu_rules','builtin_locale'):
        if key in locale:
            statement += sql.SQL(' {} {}').format(sql.SQL(key.upper()), sql.Literal(locale[key]))
    return statement


def run_restore(pg_restore, database_url, archive, *, data_only=False, label='restore'):
    info = conninfo_to_dict(database_url)
    env = dict(os.environ)
    for key,name in [('host','PGHOST'),('port','PGPORT'),('user','PGUSER'),('password','PGPASSWORD'),('dbname','PGDATABASE'),('sslmode','PGSSLMODE')]:
        if key in info:
            env[name] = info[key]
    arguments = [pg_restore, '--single-transaction', '--exit-on-error', '--no-owner',
                 '--dbname=' + info['dbname']]
    if data_only:
        arguments += ['--data-only', '--disable-triggers']
    arguments.append(str(archive))
    logs = ROOT / '.runtime/canonical-schema-verification'
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = logs / (info['dbname'] + '-' + label + '.log')
    with open(log, 'w', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        result = subprocess.run(arguments, env=env, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(label + ' failed; diagnostic log: ' + str(log))


def table_fingerprints(connection):
    """Compare exact typed row contents, including JSON text, NULLs and audit history."""
    connection.execute("SET LOCAL TIME ZONE 'UTC'")
    connection.execute("SET LOCAL DateStyle='ISO, YMD'")
    connection.execute("SET LOCAL IntervalStyle='postgres'")
    connection.execute("SET LOCAL bytea_output='hex'")
    connection.execute('SET LOCAL extra_float_digits=3')
    result = {}
    tables = connection.execute('SELECT schemaname,tablename FROM pg_tables WHERE schemaname=ANY(%s) ORDER BY 1,2', (list(SCHEMAS),)).fetchall()
    for table in tables:
        schema,name = table['schemaname'],table['tablename']
        columns = connection.execute("""SELECT a.attname FROM pg_attribute a
            JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY a.attname""", (schema,name)).fetchall()
        values = sql.SQL(',').join(sql.SQL('t.{}').format(sql.Identifier(row['attname'])) for row in columns)
        query = sql.SQL('COPY (SELECT payload FROM (SELECT ROW({})::text AS payload FROM {}.{} t) rows ORDER BY payload COLLATE "C") TO STDOUT').format(
            values, sql.Identifier(schema), sql.Identifier(name))
        digest = hashlib.sha256()
        with connection.cursor().copy(query) as copy:
            for block in copy:
                digest.update(block)
        count = connection.execute(sql.SQL('SELECT count(*) n FROM {}.{}').format(
            sql.Identifier(schema), sql.Identifier(name))).fetchone()['n']
        result[schema + '.' + name] = {'rows':count,'sha256':digest.hexdigest()}
    return result


def sequence_states(connection):
    result = {}
    for row in connection.execute('SELECT schemaname,sequencename FROM pg_sequences WHERE schemaname=ANY(%s) ORDER BY 1,2', (list(SCHEMAS),)).fetchall():
        result[row['schemaname'] + '.' + row['sequencename']] = connection.execute(
            sql.SQL('SELECT last_value,is_called FROM {}.{}').format(
                sql.Identifier(row['schemaname']),sql.Identifier(row['sequencename']))).fetchone()
    return result


def dump_schema(database_url,pg_dump):
    env=dict(os.environ);info=conninfo_to_dict(database_url)
    # The password is passed only in the child environment, never argv/logs.
    for key,name in [('host','PGHOST'),('port','PGPORT'),('user','PGUSER'),('password','PGPASSWORD'),('dbname','PGDATABASE'),('sslmode','PGSSLMODE')]:
        if key in info:env[name]=info[key]
    process=subprocess.run([pg_dump,'--schema-only','--no-owner'],env=env,text=True,capture_output=True)
    if process.returncode:raise RuntimeError('pg_dump failed; use a PostgreSQL client compatible with the server: '+process.stderr)
    return '\n'.join(line for line in process.stdout.splitlines() if not line.startswith(('\\restrict','\\unrestrict','-- Dumped')))+'\n'


def normalized_dump(c,text):
    """Let PostgreSQL reparse AND/OR grouping; do not erase parentheses blindly.

    Deparsing a row-comparison CHECK/WHEN then parsing it again flattens nested
    same-operator Boolean nodes. Temporary views canonicalize these expressions
    on both sides, preserving precedence, NULL semantics and evaluation order.
    They contain no data and are removed when the verification connection closes.
    """
    rows=c.execute("""SELECT conname,n.nspname,cl.relname,pg_get_constraintdef(co.oid) definition,
      pg_get_expr(conbin,conrelid) expr FROM pg_constraint co JOIN pg_class cl ON cl.oid=co.conrelid
      JOIN pg_namespace n ON n.oid=cl.relnamespace WHERE contype='c' AND n.nspname=ANY(%s)
      ORDER BY 2,3,1""",(list(SCHEMAS),)).fetchall()
    for row in rows:
        c.execute('DROP VIEW IF EXISTS pg_temp.__erms_schema_expr')
        c.execute(sql.SQL('CREATE TEMP VIEW __erms_schema_expr AS SELECT {} AS result FROM {}.{}').format(
            sql.SQL(row['expr']),sql.Identifier(row['nspname']),sql.Identifier(row['relname'])))
        value=c.execute("SELECT pg_get_viewdef('pg_temp.__erms_schema_expr'::regclass) v").fetchone()['v']
        text=text.replace('CONSTRAINT '+row['conname']+' '+row['definition'],
                          'CONSTRAINT '+row['conname']+' NORMALIZED CHECK '+value.replace('\n',' '))
    rows=c.execute("""SELECT n.nspname,cl.relname,pg_get_triggerdef(t.oid) definition
      FROM pg_trigger t JOIN pg_class cl ON cl.oid=t.tgrelid JOIN pg_namespace n ON n.oid=cl.relnamespace
      WHERE NOT t.tgisinternal AND tgqual IS NOT NULL AND n.nspname=ANY(%s)
      ORDER BY 1,2,tgname""",(list(SCHEMAS),)).fetchall()
    for row in rows:
        definition=row['definition'];start=definition.index(' WHEN (')+len(' WHEN (');end=definition.index(') EXECUTE FUNCTION',start)
        c.execute('DROP VIEW IF EXISTS pg_temp.__erms_schema_expr')
        c.execute(sql.SQL('CREATE TEMP VIEW __erms_schema_expr AS SELECT {} AS result FROM {}.{} AS old CROSS JOIN {}.{} AS new').format(
            sql.SQL(definition[start:end]),sql.Identifier(row['nspname']),sql.Identifier(row['relname']),sql.Identifier(row['nspname']),sql.Identifier(row['relname'])))
        value=c.execute("SELECT pg_get_viewdef('pg_temp.__erms_schema_expr'::regclass) v").fetchone()['v']
        text=text.replace(definition,definition[:start]+value.replace('\n',' ')+definition[end:])
    return text


def reference_snapshot(c):
    result={}
    for row in c.execute("SELECT schemaname,tablename FROM pg_tables WHERE schemaname=ANY(%s) ORDER BY 1,2",(list(SCHEMAS),)).fetchall():
        if row['tablename']=='event_history':continue
        name=row['schemaname']+'.'+row['tablename']
        query=sql.SQL('SELECT to_jsonb(t)-%s::text[] value FROM {}.{} t ORDER BY (to_jsonb(t)-%s::text[])::text').format(sql.Identifier(row['schemaname']),sql.Identifier(row['tablename']))
        values=[r['value'] for r in c.execute(query,(VOLATILE_COLUMNS,VOLATILE_COLUMNS))]
        result[name]=values
    return result


def object_counts(connection):
    counts = {}
    for label,query in {
        'tables':"SELECT count(*) n FROM pg_tables WHERE schemaname=ANY(%s)",
        'views':"SELECT count(*) n FROM pg_views WHERE schemaname=ANY(%s)",
        'functions':"SELECT count(*) n FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=ANY(%s) AND NOT EXISTS(SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')",
        'triggers':"SELECT count(*) n FROM pg_trigger t JOIN pg_class cl ON cl.oid=t.tgrelid JOIN pg_namespace n ON n.oid=cl.relnamespace WHERE NOT t.tgisinternal AND n.nspname=ANY(%s)",
    }.items():
        counts[label] = connection.execute(query, (list(SCHEMAS),)).fetchone()['n']
    return counts


def verify_pair(old_url,clean_url,pg_dump,*,archive_mode=False):
    old_dump=dump_schema(old_url,pg_dump);clean_dump=dump_schema(clean_url,pg_dump)
    with psycopg.connect(old_url,row_factory=dict_row) as old,psycopg.connect(clean_url,row_factory=dict_row) as clean:
        a=normalized_dump(old,old_dump);b=normalized_dump(clean,clean_dump)
        if a!=b:raise AssertionError('Final object definitions differ:\n'+''.join(difflib.unified_diff(a.splitlines(True),b.splitlines(True)))[:20000])
        if archive_mode:
            x,y = table_fingerprints(old),table_fingerprints(clean)
            differences = [name for name in sorted(x.keys() | y.keys()) if x.get(name)!=y.get(name)]
            if differences:
                raise AssertionError('Restored table contents differ: ' + ', '.join(differences))
            old_sequences,new_sequences = sequence_states(old),sequence_states(clean)
            if old_sequences != new_sequences:
                raise AssertionError('Restored sequence states differ')
            locale_query = """SELECT pg_encoding_to_char(encoding) AS encoding,
                datlocprovider,datlocale,datcollate,datctype,datcollversion
                FROM pg_database WHERE datname=current_database()"""
            source_locale,target_locale = old.execute(locale_query).fetchone(),clean.execute(locale_query).fetchone()
            if source_locale != target_locale:
                raise AssertionError('Database locale settings differ')
            disabled = clean.execute("""SELECT count(*) n FROM pg_trigger t
                JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=ANY(%s) AND t.tgenabled='D'""", (list(SCHEMAS),)).fetchone()['n']
            if disabled:
                raise AssertionError('Restore left disabled triggers')
            return {'schema_equal':True,'full_data_equal':True,'sequence_states_equal':True,
                    'objects':object_counts(clean),'rows':sum(value['rows'] for value in y.values()),
                    'sequences':len(new_sequences),'table_fingerprints':y,
                    'normalized_schema_sha256':hashlib.sha256(a.encode()).hexdigest(),
                    'database_locale':source_locale,'triggers_reenabled':True,
                    'comparison_note':'Both disposable databases restored the same archive snapshot; no runtime tables, audit rows, timestamps or settings were excluded.'}
        x=reference_snapshot(old);y=reference_snapshot(clean)
        # Initial language INSERTs now run with the final notification-coverage
        # trigger installed. Its serialization counter is runtime bookkeeping,
        # not a setting, permission or tenant row. Validate the exact seed effect.
        guard='public.messaging_notification_configuration_guard'
        coverage_guard={'reference':x.pop(guard),'clean':y.pop(guard)}
        assert coverage_guard['reference']==[]
        assert coverage_guard['clean']==[{'singleton':True,'revision':len(y['public.supported_languages'])}]
        differences=[name for name in sorted(x.keys()|y.keys()) if x.get(name)!=y.get(name)]
        if differences:raise AssertionError('Required reference data differs: '+', '.join(differences))
        audit=lambda c:{r['source']:r['count'] for r in c.execute('SELECT source,count(*) count FROM event_history GROUP BY source ORDER BY source')}
        clean_audit=audit(clean);assert set(clean_audit)=={'seeding'},'Fresh-install audit must use seeding provenance'
        old_id=old.execute('SELECT database_id FROM application_settings_state').fetchone()['database_id']
        new_id=clean.execute('SELECT database_id FROM application_settings_state').fetchone()['database_id']
        assert old_id!=new_id,'Fresh installations must have separate database identities'
        return {'schema_equal':True,'required_data_equal':True,'objects':object_counts(clean),
                'normalized_schema_sha256':hashlib.sha256(a.encode()).hexdigest(),
                'nonempty_reference_tables':{name:len(rows) for name,rows in y.items() if rows},
                'audit_sources':{'reference':audit(old),'clean':clean_audit},
                'notification_coverage_initialization':coverage_guard,
                'excluded_reference_fields':VOLATILE_COLUMNS,
                'audit_note':'Fresh seed emits current CREATE/seed events; historical upgrade events are not replayed.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    references=parser.add_mutually_exclusive_group(required=True)
    references.add_argument('--reference-archive',type=Path,help='Full pg_dump custom archive of the migration-built reference')
    references.add_argument('--reference-ref',help='Explicit historical Git schema for a historical comparison only')
    parser.add_argument('--pg-dump',default=shutil.which('pg_dump'))
    parser.add_argument('--pg-restore',help='Server-compatible pg_restore; defaults to the pg_dump directory')
    parser.add_argument('--locale-provider',choices=('libc','icu','builtin'),help='Required for Git mode; archive mode preserves its own metadata')
    parser.add_argument('--locale',help='Explicit provider locale for Git mode')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    if not args.pg_dump:parser.error('Provide --pg-dump for a server-compatible PostgreSQL client')
    pg_restore=args.pg_restore or str(Path(args.pg_dump).with_name('pg_restore'))
    archive_mode=args.reference_archive is not None
    if archive_mode:
        if args.locale_provider or args.locale:
            parser.error('Archive mode preserves the backup locale; do not override it')
        if not args.reference_archive.is_file():
            parser.error('Reference archive does not exist')
        metadata=subprocess.run([pg_restore,'--schema-only','--create','--no-owner','--file=-',str(args.reference_archive)],text=True,capture_output=True)
        if metadata.returncode:
            raise RuntimeError('Could not read reference archive database metadata')
        locale=archive_locale(metadata.stdout)
        with args.reference_archive.open('rb') as stream:
            reference_hash=hashlib.file_digest(stream,'sha256').hexdigest()
        provenance={'reference_archive':args.reference_archive.name,'reference_archive_sha256':reference_hash}
        old_source=None
    else:
        if not args.locale_provider or not args.locale:
            parser.error('Git mode requires explicit --locale-provider and --locale')
        locale={'provider':args.locale_provider,'encoding':'UTF8',
                {'libc':'locale','icu':'icu_locale','builtin':'builtin_locale'}[args.locale_provider]:args.locale}
        old_source=subprocess.check_output(['git','show',args.reference_ref+':database/schema.sql'],cwd=ROOT,text=True)
        provenance={'reference_ref':args.reference_ref,'reference_sql_sha256':hashlib.sha256(old_source.encode()).hexdigest()}
    base={**dotenv_values(ROOT/'.env'),**os.environ}['DATABASE_URL'];admin_url=make_conninfo(base,dbname='postgres')
    static=assert_canonical((ROOT/'database/schema.sql').read_text())
    names=['erms_messaging_test_acl_'+kind+'_'+uuid4().hex for kind in ('ref','clean')];created=[];report=None
    assert all(len(name)<=63 for name in names)
    try:
        with psycopg.connect(admin_url,autocommit=True) as admin:
            for name in names:
                admin.execute(create_database_statement(name,locale));created.append(name);print('Created disposable database',name,flush=True)
        urls=[make_conninfo(base,dbname=name) for name in names]
        if archive_mode:
            run_restore(pg_restore,urls[0],args.reference_archive,label='reference')
            print('Restored migration-built reference archive.',flush=True)
            with psycopg.connect(urls[1]) as c:
                c.execute((ROOT/'database/schema.sql').read_text(),prepare=False)
            run_restore(pg_restore,urls[1],args.reference_archive,data_only=True,label='canonical-data')
            print('Built canonical schema and restored the same data snapshot.',flush=True)
        else:
            with psycopg.connect(urls[0]) as c:c.execute(old_source,prepare=False)
            print('Built historical reference schema.',flush=True)
            with psycopg.connect(urls[1]) as c:initialize(c)
            print('Built canonical schema and required reference data.',flush=True)
        report={**verify_pair(*urls,args.pg_dump,archive_mode=archive_mode),'canonical':static,**provenance,
                'canonical_sql_sha256':hashlib.sha256((ROOT/'database/schema.sql').read_bytes()).hexdigest()}
        print('Passed complete schema and data parity.',flush=True)
    finally:
        failures=[]
        with psycopg.connect(admin_url,autocommit=True) as admin:
            for name in reversed(created):
                try:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)));print('Dropped disposable database',name,flush=True)
                except Exception as error:failures.append((name,type(error).__name__))
        if failures:raise RuntimeError('Disposable database cleanup failed: '+repr(failures))
    if args.report and report:
        report['disposable_databases_dropped']=True
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
