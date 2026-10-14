"""Configuration warning/readiness and selector paths in a disposable database."""
from datetime import datetime, timezone

from backend.services.api.application_settings import cache, destination_configuration
from backend.services.api.tests.test_application_settings import db, actor, items, save, PATH

CUSTODY = '/api/v1/authorization/governance-custody'
KEYS = {'DISPOSITION_CLASSIFICATION_SCHEME_ID', 'DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID', 'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID'}


def warnings(client):
    response = client.get(CUSTODY)
    assert response.status_code == 200, response.text
    return response.json()['disposition_configuration_warnings']


def configure(client, **values):
    result = save(client, values, group='destinations')
    assert result.status_code == 200, result.text


def root(client, code, classification=1, parent=None):
    result = client.post('/api/v1/aggregations', json={'aggregation_number':code, 'title':code,
                        **({'parent_aggregation_id':parent} if parent else {'classification_id':classification})})
    assert result.status_code == 201, result.text
    return result.json()


def test_each_missing_setting_clears_independently_without_cached_warning(client):
    assert {w['setting_key'] for w in warnings(client)} == KEYS
    assert all(w['code'] == 'destination_unset' and set(w) == {'code','setting_key'} for w in warnings(client))
    with db() as c:
        stale = cache.for_connection(c)
    configure(client, DISPOSITION_CLASSIFICATION_SCHEME_ID=1)
    assert stale['DISPOSITION_CLASSIFICATION_SCHEME_ID'] is None
    assert {w['setting_key'] for w in warnings(client)} == KEYS - {'DISPOSITION_CLASSIFICATION_SCHEME_ID'}
    configure(client, DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID=1)
    assert {w['setting_key']:w['code'] for w in warnings(client)} == {
        'DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID':'destination_open_root_missing',
        'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID':'destination_unset'}
    root(client, 'EVIDENCE-ROOT')
    assert warnings(client) == [{'setting_key':'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID','code':'destination_unset'}]
    configure(client, DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID=1)
    assert warnings(client) == []
    # No route, SMTP or authority default is reported as a missing destination.
    assert items(client)['DISPOSITION_DESTRUCTION_REVIEW_ROUTE']['value'] == 'standard'


def test_closed_children_wrong_classifications_and_changed_settings_are_not_roots(client):
    configure(client, DISPOSITION_CLASSIFICATION_SCHEME_ID=1, DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID=1,
              DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID=1)
    closed = root(client, 'CLOSED-ROOT')
    root(client, 'OPEN-CHILD', parent=closed['id'])
    result = client.patch(f"/api/v1/aggregations/{closed['id']}",
                          headers={'If-Match':str(closed['version']), 'X-Change-Reason':'Close test root'},
                          json={'date_closed':datetime.now(timezone.utc).isoformat()})
    assert result.status_code == 200, result.text
    classification = client.post('/api/v1/classifications', json={'classification_scheme_id':1,
        'code':'OTHER-01','title':'Other terminal','is_terminal':True,
        'retention_rule':{'current_period_years':5,'intermediate_period_years':0,'final_disposition':'destruction'}}).json()
    root(client, 'WRONG-CLASSIFICATION', classification['id'])
    assert len(warnings(client)) == 2
    configure(client, DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID=classification['id'])
    assert warnings(client) == [{'setting_key':'DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID','code':'destination_open_root_missing'}]
    root(client, 'CURRENT-REPORT-ROOT')
    assert warnings(client) == []


def test_latest_root_uses_opening_date_then_id_and_warnings_hide_root_details(client):
    configure(client, DISPOSITION_CLASSIFICATION_SCHEME_ID=1, DISPOSITION_UPLOADED_EVIDENCE_CLASSIFICATION_ID=1,
              DISPOSITION_GENERATED_REPORTS_CLASSIFICATION_ID=1)
    first, second, newest = (root(client, code) for code in ('FIRST','SECOND','NEWEST'))
    with db() as c:
        actor(c)
        c.execute("UPDATE aggregations SET date_opened=CASE WHEN id=%s THEN '2026-02-01'::timestamptz ELSE '2026-01-01'::timestamptz END WHERE id=ANY(%s)", (newest['id'],[first['id'],second['id'],newest['id']]))
        assert {row['open_root_id'] for row in destination_configuration(c) if row['key']!='DISPOSITION_CLASSIFICATION_SCHEME_ID'} == {newest['id']}
        c.execute("UPDATE aggregations SET date_opened='2026-02-01'::timestamptz WHERE id=%s", (second['id'],))
        assert {row['open_root_id'] for row in destination_configuration(c) if row['key']!='DISPOSITION_CLASSIFICATION_SCHEME_ID'} == {newest['id']}
    assert warnings(client) == []
    with db() as c:
        c.execute("UPDATE roles SET profile_id=(SELECT id FROM profiles WHERE code='INFO_GOV_OFFICER') WHERE id=1")
    assert client.get(PATH).status_code == 403
    # Custody authority does not confer settings authority, and does not leak root
    # IDs/titles/SMTP configuration when checking readiness.
    assert warnings(client) == []


def test_large_branch_and_terminal_search_are_bounded_and_scheme_scoped(client):
    with db() as c:
        c.execute("SELECT set_config('app.event_source','seeding',true)")
        branch = c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(1,'BRANCH','Branch',false) RETURNING id").fetchone()['id']
        c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')",(branch,))
        c.execute("INSERT INTO classifications(classification_scheme_id,parent_classification_id,code,title,is_terminal) SELECT 1,%s,'T-'||lpad(i::text,4,'0'),'Terminal '||i,true FROM generate_series(1,1000) i", (branch,))
        other = c.execute("INSERT INTO classification_schemes(code,title) VALUES('OTHER','Other scheme') RETURNING id").fetchone()['id']
        other_class = c.execute("INSERT INTO classifications(classification_scheme_id,code,title,is_terminal) VALUES(%s,'T-OTHER','Terminal other',true) RETURNING id",(other,)).fetchone()['id']
        c.execute("INSERT INTO classification_retention_rules(classification_id,current_period_years,intermediate_period_years,final_disposition) VALUES(%s,5,0,'destruction')",(other_class,))
    first=client.get('/api/v1/classifications',params={'classification_scheme_id':1,'parent_classification_id':branch,'limit':26,'offset':0}).json()
    second=client.get('/api/v1/classifications',params={'classification_scheme_id':1,'parent_classification_id':branch,'limit':26,'offset':25}).json()
    assert len(first)==len(second)==26 and first[25]['id']==second[0]['id']
    response=client.post('/api/v1/classifications/search',json={'limit':25,'offset':0,'sort':[{'field':'code','direction':'asc'}], 'where':{'and':[{'field':'classification_scheme_id','operator':'eq','value':1},{'field':'is_terminal','operator':'eq','value':True},{'field':'title','operator':'contains_ci','value':'Terminal'}]}})
    assert response.status_code==200,response.text
    assert len(response.json()['items'])==25
    assert all(row['is_terminal'] and row['classification_scheme_id']==1 for row in response.json()['items'])
