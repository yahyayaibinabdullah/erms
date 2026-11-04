"""Dashboard ACLs equal canonical predicates within the nonterminal scope."""
import os

import psycopg
from psycopg.rows import dict_row

from backend.services.api.dashboard_visibility import VISIBILITY_CTES
from backend.services.api.dashboard import _resource_metrics


def assert_equivalent(connection, identity):
    connection.execute("SELECT set_config('app.user_id',%s,true)",(str(identity) if identity else '',))
    for table,kind in (('aggregations','aggregation'),('records','record')):
        expected=connection.execute(
            f'SELECT id FROM {table} WHERE disposition_status NOT IN (10,11,12) AND current_user_can_view_{kind}(id) ORDER BY id').fetchall()
        actual=connection.execute(
            f'WITH RECURSIVE {VISIBILITY_CTES} SELECT id FROM authorized_{table} ORDER BY id').fetchall()
        assert actual==expected,(identity,table,actual,expected)
    expected=connection.execute("SELECT code FROM privileges WHERE user_has_global_privilege(current_user_id(),code) ORDER BY code").fetchall()
    actual=connection.execute(f'WITH RECURSIVE {VISIBILITY_CTES} SELECT code FROM effective_privileges ORDER BY code').fetchall()
    assert actual==expected


def test_prepared_dashboard_query_never_reuses_another_identity_visibility(client,aggregation,record):
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row,prepare_threshold=0) as c:
        c.execute('SET LOCAL plan_cache_mode=force_generic_plan')
        other=c.execute("INSERT INTO users(name,email) VALUES('Prepared query B','prepared-b@test.invalid') RETURNING id").fetchone()['id']
        c.execute('INSERT INTO user_favourite_aggregations(user_id,aggregation_id) VALUES(1,%s)',(aggregation['id'],))
        c.execute('INSERT INTO user_favourite_records(user_id,record_id) VALUES(1,%s)',(record['id'],))
        for identity in (1,other,1,other,None,1):
            c.execute("SELECT set_config('app.user_id',%s,true)",(str(identity) if identity else '',))
            metrics=_resource_metrics(c,30,5)
            expected=int(identity==1)
            assert sum(row['total'] for row in metrics['aggregations'])==expected
            assert sum(row['total'] for row in metrics['records'])==expected
            assert len(metrics['favourite_aggregations'])==expected
            assert len(metrics['favourite_records'])==expected
            if not expected:
                assert metrics['recent_activity']==metrics['units']==[]
                assert metrics['privileges']==[]
        assert c.execute("SELECT count(*) AS total FROM pg_prepared_statements WHERE statement LIKE 'WITH RECURSIVE%' AND generic_plans>0").fetchone()['total']>0


def test_set_visibility_matches_acl_sources_contextual_roles_clearance_and_identity(client,aggregation,record):
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        owner=c.execute('SELECT owning_org_unit_id FROM aggregations WHERE id=%s',(aggregation['id'],)).fetchone()['owning_org_unit_id']
        child_unit=c.execute("INSERT INTO org_units(parent_org_unit_id,code,name) VALUES(%s,'ACL-CHILD','ACL child') RETURNING id",(owner,)).fetchone()['id']
        profile=c.execute("SELECT id FROM profiles WHERE code='ALL_PRIVS'").fetchone()['id']
        levels=c.execute('SELECT id FROM security_levels ORDER BY level_number').fetchall()
        low,high=levels[0]['id'],levels[-1]['id']
        user=c.execute("INSERT INTO users(name,email) VALUES('Batched reader','batched@test.invalid') RETURNING id").fetchone()['id']
        role=c.execute("INSERT INTO roles(org_unit_id,code,name,profile_id,security_level_id) VALUES(%s,'BATCHED','Batched reader',%s,%s) RETURNING id",(owner,profile,high)).fetchone()['id']
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(user,role))
        local_role=c.execute("INSERT INTO roles(org_unit_id,code,name,profile_id,security_level_id) VALUES(%s,'LOCAL','Local reader',%s,%s) RETURNING id",(child_unit,profile,low)).fetchone()['id']
        c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(user,local_role))
        c.execute('UPDATE org_units SET managing_role_id=%s,file_administrator_role_id=%s WHERE id=%s',(role,role,owner))
        permission=c.execute("SELECT id,code FROM permissions WHERE code IN ('record.view','aggregation.view')").fetchall()
        permissions={row['code']:row['id'] for row in permission}
        # Exercise inherited resource ACLs, custom child defaults, inheritance
        # breaks and a child with a different owner from its ACL source.
        children=[]
        for index in range(3):
            parent=aggregation['id'] if not children else children[-1]
            children.append(c.execute("INSERT INTO aggregations(parent_aggregation_id,aggregation_number,title,owning_org_unit_id) VALUES(%s,%s,%s,%s) RETURNING id",(parent,f'BATCH-{index}',f'Child {index}',child_unit)).fetchone()['id'])
        c.execute('UPDATE aggregations SET inherit_acl_from_parent=false WHERE id=%s',(children[2],))
        extra=c.execute("INSERT INTO records(aggregation_id,record_number,title,owning_org_unit_id) VALUES(%s,'BATCH-RECORD','Inherited record',%s) RETURNING id",(children[1],child_unit)).fetchone()['id']
        c.execute('UPDATE records SET inherit_acl_from_parent=false WHERE id=%s',(record['id'],))
        matrices=[('aggregation_acl_grants','aggregation_id',aggregation['id'],'aggregation.view'),
                  ('aggregation_acl_grants','aggregation_id',children[2],'aggregation.view'),
                  ('aggregation_child_aggregation_acl_defaults','aggregation_id',children[0],'aggregation.view'),
                  ('record_acl_grants','record_id',record['id'],'record.view'),
                  ('aggregation_child_record_acl_defaults','aggregation_id',children[1],'record.view')]
        c.execute("UPDATE aggregations SET default_child_aggregation_acl_mode='custom' WHERE id=%s",(children[0],))
        for principal in ('everyone','role','org_unit_members','owning_and_higher_level_unit_managers','effective_file_administrator'):
            for table,column,identifier,code in matrices:
                c.execute(f'DELETE FROM {table} WHERE {column}=%s',(identifier,))
                c.execute(f'INSERT INTO {table}({column},principal_type,role_id,permission_id) VALUES(%s,%s,%s,%s)',
                          (identifier,principal,role if principal=='role' else None,permissions[code]))
            for identity in (1,user,None,user,1):assert_equivalent(c,identity)
        # Nearest file administrator blocks fallback to a higher-level one,
        # including when that nearest administrator is ineffective.
        c.execute('UPDATE org_units SET file_administrator_role_id=%s WHERE id=%s',(local_role,child_unit))
        c.execute('UPDATE roles SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s',(local_role,))
        assert_equivalent(c,user)
        c.execute('UPDATE roles SET date_deactivated=NULL WHERE id=%s',(local_role,))
        c.execute('UPDATE roles SET security_level_id=%s WHERE id=%s',(low,role))
        for identifier in (aggregation['id'],*children):
            c.execute('UPDATE aggregations SET security_level_id=%s WHERE id=%s',(high,identifier))
        c.execute('UPDATE records SET security_level_id=%s WHERE id=%s',(high,extra))
        assert_equivalent(c,user)
        c.execute('UPDATE roles SET is_information_governance=true,security_level_id=%s WHERE id=%s',(high,role))
        assert_equivalent(c,user)
        # Global view privilege is mandatory even with governance clearance.
        no_view=c.execute("INSERT INTO profiles(code,name) VALUES('NO-BATCH-VIEW','No view') RETURNING id").fetchone()['id']
        c.execute('UPDATE roles SET profile_id=%s WHERE id IN (%s,%s)',(no_view,role,local_role))
        assert_equivalent(c,user)
        c.execute('UPDATE roles SET profile_id=%s WHERE id=%s',(profile,role))
        for assignment_change in ("valid_from=CURRENT_TIMESTAMP+INTERVAL '1 day'",
                                  "valid_from=CURRENT_TIMESTAMP-INTERVAL '1 day',valid_until=CURRENT_TIMESTAMP",
                                  'valid_until=NULL',):
            c.execute(f'UPDATE user_role_assignments SET {assignment_change} WHERE user_id=%s',(user,))
            assert_equivalent(c,user)
        c.execute('UPDATE org_units SET date_deactivated=CURRENT_TIMESTAMP WHERE id=%s',(owner,))
        assert_equivalent(c,user)
        c.execute('UPDATE org_units SET date_deactivated=NULL WHERE id=%s',(owner,))
        c.execute("UPDATE users SET date_suspended=CURRENT_TIMESTAMP WHERE id=%s",(user,))
        assert_equivalent(c,user)
        c.commit()
        for table in ('records','aggregations'):
            c.execute(f'ALTER TABLE {table} DISABLE TRIGGER USER')
            try:c.execute(f'UPDATE {table} SET disposition_status=10')
            finally:c.execute(f'ALTER TABLE {table} ENABLE TRIGGER USER')
        assert_equivalent(c,1)


def test_batched_classification_metrics_equal_canonical_inherited_state(client):
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row) as c:
        scheme=c.execute('SELECT id FROM classification_schemes LIMIT 1').fetchone()['id']
        parent=c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(%s,'BATCH-ROOT','Batch root',false) RETURNING id",(scheme,)).fetchone()['id']
        branch=c.execute("INSERT INTO classifications(classification_scheme_id,parent_classification_id,code,title,is_terminal) VALUES(%s,%s,'BATCH-BRANCH','Batch branch',false) RETURNING id",(scheme,parent)).fetchone()['id']
        c.execute("INSERT INTO classifications(classification_scheme_id,parent_classification_id,code,title,is_terminal) VALUES(%s,%s,'BATCH-TERM','Batch term',true)",(scheme,branch))
        c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')",(parent,))
    for change in ('SELECT 1',f'UPDATE classifications SET date_deactivated=CURRENT_TIMESTAMP WHERE id={branch}',
                   f'UPDATE classifications SET date_deactivated=NULL WHERE id={branch}',
                   f"UPDATE classification_schemes SET date_published=CURRENT_TIMESTAMP+INTERVAL '1 day' WHERE id={scheme}"):
        with psycopg.connect(os.environ['DATABASE_URL']) as c:c.execute(change)
        response=client.get('/api/v1/dashboard/summary')
        assert response.status_code==200,response.text
        with psycopg.connect(os.environ['DATABASE_URL']) as c:
            expected=c.execute('''SELECT count(*) FROM classifications classification
                WHERE is_terminal AND classification_scheme_is_eligible(classification_scheme_id)
                  AND classification_is_effectively_active(id)
                  AND EXISTS(SELECT 1 FROM effective_classification_retention_rule(id))''').fetchone()[0]
        assert response.json()['classification_metrics']['assignable_terminal_count']==expected
