"""Verify Phase 7 fresh/upgrade parity and data preservation in disposable DBs."""
import os
from pathlib import Path
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
MARKER = '-- Common disposition foundation (053).\n'
FIELDS = ['disposition_status','final_disposition_at','final_disposition_by_user_id',
          'disposition_job_id','destruction_number','transfer_number','final_disposition_event_id']


from tools.historical_schema import historical_schema


def catalogue(c):
    # Names/definitions, never OIDs or allocation order. Include common tables,
    # changed resource tables/views, private functions, triggers and all constraints.
    relations = "(cl.relname LIKE 'disposition_%' OR ns.nspname='disposition_private' OR cl.relname IN ('aggregations','records','authorized_aggregations_for_search','authorized_records_for_search'))"
    data = {}
    data['columns'] = c.execute(f"""SELECT ns.nspname,cl.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,
     pg_get_expr(d.adbin,d.adrelid) FROM pg_class cl JOIN pg_namespace ns ON ns.oid=cl.relnamespace
     JOIN pg_attribute a ON a.attrelid=cl.oid AND a.attnum>0 AND NOT a.attisdropped
     LEFT JOIN pg_attrdef d ON d.adrelid=cl.oid AND d.adnum=a.attnum
     WHERE ns.nspname IN ('public','disposition_private') AND {relations} ORDER BY 1,2,a.attnum""").fetchall()
    data['constraints'] = c.execute(f"""SELECT ns.nspname,cl.relname,k.conname,pg_get_constraintdef(k.oid)
     FROM pg_constraint k JOIN pg_class cl ON cl.oid=k.conrelid JOIN pg_namespace ns ON ns.oid=cl.relnamespace
     WHERE {relations} ORDER BY 1,2,3""").fetchall()
    data['triggers'] = c.execute(f"""SELECT ns.nspname,cl.relname,t.tgname,pg_get_triggerdef(t.oid)
     FROM pg_trigger t JOIN pg_class cl ON cl.oid=t.tgrelid JOIN pg_namespace ns ON ns.oid=cl.relnamespace
     WHERE NOT t.tgisinternal AND {relations} ORDER BY 1,2,3""").fetchall()
    data['indexes'] = c.execute(f"""SELECT ns.nspname,cl.relname,pg_get_indexdef(i.indexrelid)
     FROM pg_index i JOIN pg_class cl ON cl.oid=i.indrelid JOIN pg_namespace ns ON ns.oid=cl.relnamespace
     WHERE {relations} ORDER BY 1,2,3""").fetchall()
    data['functions'] = c.execute("""SELECT ns.nspname,p.proname,pg_get_functiondef(p.oid),p.proacl::text
     FROM pg_proc p JOIN pg_namespace ns ON ns.oid=p.pronamespace WHERE ns.nspname='disposition_private'
     OR (ns.nspname='public' AND p.proname IN ('protect_closed_aggregation_hierarchy','protect_record_in_closed_aggregation','current_user_can_view_event_resource')) ORDER BY 1,2""").fetchall()
    data['views'] = c.execute("SELECT viewname,definition FROM pg_views WHERE schemaname='public' AND viewname IN ('authorized_aggregations_for_search','authorized_records_for_search') ORDER BY viewname").fetchall()
    return data


def baseline_data(c):
    c.execute("SELECT set_config('app.event_source','seeding',true),set_config('app.actor_type','automated_process',true)")
    org=c.execute("INSERT INTO org_units(code,name) VALUES('upgrade-unit','Existing Unit') RETURNING id").fetchone()[0]
    user=c.execute("INSERT INTO users(name,email) VALUES('Existing person','upgrade@example.invalid') RETURNING id").fetchone()[0]
    role=c.execute("INSERT INTO roles(org_unit_id,code,name,is_information_governance) VALUES(%s,'existing','Existing governance role',true) RETURNING id",(org,)).fetchone()[0]
    c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(user,role))
    scheme=c.execute("INSERT INTO classification_schemes(code,title,date_published) VALUES('UPGRADE','Existing scheme',CURRENT_TIMESTAMP) RETURNING id").fetchone()[0]
    classification=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(%s,'UPGRADE-1','Existing classification',true) RETURNING id",(scheme,)).fetchone()[0]
    c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')",(classification,))
    root=c.execute("INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id) VALUES('existing-root','Existing root',%s,%s) RETURNING id",(classification,org)).fetchone()[0]
    child=c.execute("INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title) VALUES(%s,'existing-child','Existing child') RETURNING id",(root,)).fetchone()[0]
    c.execute("INSERT INTO records(aggregation_id,record_number,title) VALUES(%s,'existing-record','Existing record')",(child,))
    c.execute('UPDATE aggregations SET date_closed=CURRENT_TIMESTAMP WHERE id=%s',(root,))


def snapshot(c, upgraded=False):
    tables=['aggregations','records','org_units','roles','users','user_role_assignments','event_history','profile_privileges','application_settings']
    return {table:c.execute(sql.SQL('SELECT to_jsonb(t) - %s::text[] FROM {} t ORDER BY id').format(sql.Identifier(table)),(FIELDS if upgraded and table in ('aggregations','records') else [],)).fetchall() for table in tables}


def main():
    config={**dotenv_values(ROOT/'.env'),**os.environ}
    base=config['DATABASE_URL']; admin_url=make_conninfo(base,dbname='postgres')
    schema=historical_schema().split('-- Disposition eligibility and current blockers (054).',1)[0].rstrip()+'\n'
    old=schema.split(MARKER,1)[0]
    migration=(ROOT/'database/migrations/053_disposition_foundation.sql').read_text()
    assert schema.split(MARKER,1)[1]==migration
    names=[]
    try:
        for kind in ['fresh','upgrade']:
            name='erms_disposition_test_'+kind+'_'+uuid.uuid4().hex
            with psycopg.connect(admin_url,autocommit=True) as admin:
                admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            names.append(name); print('Created disposable database '+name,flush=True)
            with psycopg.connect(make_conninfo(base,dbname=name)) as c:
                c.execute(schema if kind=='fresh' else old,prepare=False); c.commit()
                if kind=='upgrade':
                    baseline_data(c); c.commit(); before=snapshot(c)
                    c.execute(migration,prepare=False); c.commit(); after=snapshot(c,True)
                    for table in before:
                        # The approved new grant is additive; all older grants
                        # must remain byte-for-byte unchanged.
                        if table in ('profile_privileges','event_history'):
                            assert all(row in after[table] for row in before[table]),table
                            if table=='event_history':
                                assert all(row[0]['source']=='migration' for row in after[table] if row not in before[table])
                        else: assert before[table]==after[table],table
                    assert c.execute('SELECT DISTINCT disposition_status FROM aggregations UNION SELECT DISTINCT disposition_status FROM records').fetchall()==[(1,)]
                    assert catalogue(c)==fresh,'fresh/upgrade catalogue mismatch'
                    print('Passed: catalogue parity; existing resources, history, settings and grants preserved',flush=True)
                else: fresh=catalogue(c)
    finally:
        failures=[]
        for name in reversed(names):
            try:
                with psycopg.connect(admin_url,autocommit=True) as admin:
                    admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
                print('Dropped disposable database '+name,flush=True)
            except Exception as error:
                failures.append((name,type(error).__name__))
        if failures: raise RuntimeError('Disposable database cleanup failed: '+repr(failures))


if __name__=='__main__': main()
