"""Run through tools/run_disposable_acl_tests.py only."""
from backend.services.api.disposition import queries
from backend.services.api.disposition.history_display import enrich
from backend.services.api.tests.test_disposition_membership import db,actor,ready,setup,admit


def test_history_names_existing_events_localization_and_redaction(client):
    with db() as c:
        saved=setup(c);root,*_=ready(c);admit(c,saved['id'],[root])
        c.execute("UPDATE users SET translations=jsonb_build_object('ar',jsonb_build_object('name','مستخدم الاختبار')) WHERE id=1")
        rows=queries.history(c,saved['id'],limit=25,offset=0,language_tag='ar')['items']
        row=next(r for r in rows if r['operation']=='MEMBERSHIP_ADD')
        assert row['display_references'][f'aggregation:{root}']
        assert row['display_references'][f"job:{saved['id']}"]==saved['job_number']
        assert row['display_references']['user:1']=='مستخدم الاختبار'
        assert row['actor_name']=='مستخدم الاختبار'
        hidden={'operation':'MEMBERSHIP_ADD','metadata':{'redacted':True},'entity_id':None,'actor_user_id':None}
        assert enrich(c,[hidden])[0]['display_references']=={}
        missing={'metadata':{'root_id':9999999}}
        assert enrich(c,[missing])[0]['display_references']['aggregation:9999999'] is None


def test_all_reference_queries_are_bounded_and_admin_flag_is_authoritative(client):
    from backend.services.api.disposition.history_display import REFERENCE_FIELDS
    with db() as c:
        actor(c)
        row={'metadata':{fields[0]:9999999 for fields in REFERENCE_FIELDS.values()}}
        result=enrich(c,[row],'ar')[0]
        assert len(result['display_references'])==len(REFERENCE_FIELDS)
        assert all(value is None for value in result['display_references'].values())
        assert result['can_view_technical_details']==c.execute("SELECT user_has_global_privilege(current_user_id(),'audit.view') allowed").fetchone()['allowed']


def test_global_audit_search_list_and_detail_share_presentation(client):
    with db() as c:
        saved=setup(c);root,*_=ready(c);admit(c,saved['id'],[root])
    query={'where':{'field':'operation','operator':'eq','value':'MEMBERSHIP_ADD'},'limit':25}
    response=client.post('/api/v1/event-history/search',json=query)
    assert response.status_code==200,response.text
    row=response.json()['items'][0]
    assert row['display_presentation']=='disposition'
    assert row['display_references'][f'aggregation:{root}']
    response=client.get(f"/api/v1/event-history/{row['id']}")
    assert response.status_code==200,response.text
    assert response.json()['display_references']==row['display_references']
    response=client.get('/api/v1/event-history',params={'operation':'MEMBERSHIP_ADD'})
    assert response.status_code==200,response.text
    assert response.json()[0]['display_presentation']=='disposition'
