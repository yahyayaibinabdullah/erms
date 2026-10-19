"""Phase 10 live read contracts; run only through the disposable test runner."""
from datetime import datetime,timezone
from fastapi import HTTPException
import pytest
from backend.services.api.disposition import queries
from backend.services.api.tests.test_disposition_membership import db,actor,ready,setup,admit,remove


def page(c,**kw):
    return queries.eligibility(c,limit=25,offset=0,**kw)


def test_live_eligibility_dates_tie_break_filters_and_page_bounds(client):
    with db() as c:
        actor(c)
        roots=[ready(c)[0] for _ in range(31)]
        first=queries.eligibility(c,limit=10,offset=0)
        second=queries.eligibility(c,limit=10,offset=10)
        assert first['total']==31 and [r['id'] for r in first['items']]==roots[:10]
        assert [r['id'] for r in second['items']]==roots[10:20]
        row=first['items'][0]
        assert row['calculated_disposition_at']==datetime(2025,1,1,tzinfo=timezone.utc)
        assert row['days_overdue']>=0 and row['rule_source']=='aggregation'
        assert row['selectable'] and not row['blocked']
        assert page(c,status=3)['total']==0
        assert page(c,owner=1,due_from=datetime(2024,1,1,tzinfo=timezone.utc),group_owner=True)['total']==31
        assert page(c,vital=True)['total']==0 and page(c,held=False)['total']==31
        with pytest.raises(HTTPException):page(c,sort='id; DROP TABLE users')


def test_protections_are_current_and_counts_do_not_disclose_hidden_descendants(client):
    with db() as c:
        actor(c);root,child,leaf,record=ready(c)
        c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)")
        c.execute('UPDATE records SET is_vital=true WHERE id=%s',(record,))
        assert page(c,vital=True)['items'][0]['blocked']
        assert page(c,vital=True)['items'][0]['vital_count']==1
        c.execute('UPDATE records SET is_vital=false WHERE id=%s',(record,))
        assert page(c,vital=True)['total']==0


def test_job_membership_episodes_history_and_selector_contracts(client):
    with db() as c:
        saved=setup(c);root,*_=ready(c);admit(c,saved['id'],[root]);remove(c,root)
        assert queries.jobs(c,limit=10,offset=0)['total']==1
        assert queries.job(c,saved['id'])['membership_editable']
        assert queries.members(c,saved['id'],limit=10,offset=0)['items'][0]['membership_state']=='removed'
        history=queries.history(c,saved['id'],limit=10,offset=0)
        assert history['total']>=3 and any(r['operation']=='MEMBERSHIP_ADD' for r in history['items'])
        assert queries.selector(c,'assignees',query='T')['items']==[]
        assert queries.selector(c,'assignees',selected=1)['items'][0]['id']==1
        assert queries.context(c)['roles'][0]['id']==1
        c.execute("SELECT set_config('app.user_id','',true)")
        # Workspace context has used a non-disclosing 404 since governed
        # evidence/task recipients were introduced. Manager-only reads use 403.
        for query,status in ((lambda:page(c),403),(lambda:queries.job(c,saved['id']),404),(lambda:queries.selector(c,'owners',query='Te'),403)):
            with pytest.raises(HTTPException) as e:query()
            assert e.value.status_code==status


def test_read_http_is_bounded_and_uses_authenticated_actor(client):
    with db() as c:actor(c);ready(c)
    response=client.get('/api/v1/disposition/eligibility?limit=1')
    assert response.status_code==200 and len(response.json()['items'])==1
    assert client.get('/api/v1/disposition/eligibility?limit=101').status_code==422
    assert client.get('/api/v1/disposition/selectors/assignees?query=T').json()=={'items':[]}


def test_hidden_root_envelope_and_separate_hidden_blockers_never_leak_identifiers(client):
    from backend.services.api.disposition import blockers
    with db() as c, c.transaction(force_rollback=True):
        actor(c);root,child,leaf,record=ready(c)
        c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)")
        c.execute('UPDATE records SET is_vital=true WHERE id=%s',(record,))
        c.execute("DELETE FROM profile_privileges WHERE profile_id=(SELECT profile_id FROM roles WHERE id=1) AND privilege_id=(SELECT id FROM privileges WHERE code='record.view')")
        row=page(c)['items'][0]
        assert row['blocked'] and not row['selectable'] and row['vital_count'] is None
        hidden=blockers.protection_page(c,root)['items'][0]
        assert hidden['redacted'] and hidden['resource_id'] is None and hidden['resource_label'] is None and hidden['holds']==[]
        c.execute("DELETE FROM profile_privileges WHERE profile_id=(SELECT profile_id FROM roles WHERE id=1) AND privilege_id=(SELECT id FROM privileges WHERE code='aggregation.view')")
        row=page(c)['items'][0]
        assert row['redacted'] and not row['selectable'] and row['title'] is None and row['version'] is None
        assert str(root)!=row['id'] and row['owner'] is None and row['job_id'] is None


def test_first_blocker_detection_is_permanent_deduplicated_and_never_changes_membership(client):
    from backend.services.api.tests.test_disposition_eligibility import make_hold,statuses
    with db() as c:
        job=setup(c);root,child,leaf,record=ready(c);admit(c,job['id'],[root])
        before=c.execute('SELECT * FROM disposition_job_memberships').fetchall()
        hold=make_hold(c,'record',record)
        first=queries.members(c,job['id'],limit=25,offset=0)
        assert first['items'][0]['held']
        queries.members(c,job['id'],limit=25,offset=0)
        assert c.execute("SELECT count(*) n FROM event_history WHERE operation='DISPOSITION_BLOCKERS_DETECTED'").fetchone()['n']==1
        c.execute('DELETE FROM hold_record_assignments WHERE hold_id=%s',(hold,))
        queries.members(c,job['id'],limit=25,offset=0)
        assert c.execute("SELECT count(*) n FROM event_history WHERE operation='DISPOSITION_BLOCKERS_RESOLVED'").fetchone()['n']==1
        assert c.execute('SELECT * FROM disposition_job_memberships').fetchall()==before and statuses(c,root)==[6]*4


def test_descendant_search_and_browse_return_stored_pending_status_and_reopening_notice(client):
    with db() as c:
        job=setup(c);root,child,leaf,record=ready(c);admit(c,job['id'],[root])
    response=client.post('/api/v1/records/search',json={'where':{'field':'disposition_status','operator':'eq','value':6},'limit':10})
    assert response.status_code==200,response.text
    assert response.json()['items'][0]['disposition_status']==6
    response=client.get(f'/api/v1/browse/aggregations/{leaf}/records')
    assert response.status_code==200,response.text
    assert response.json()['items'][0]['disposition_status']==6
    with db() as c:
        actor(c);c.execute('UPDATE aggregations SET date_closed=NULL WHERE id=%s',(root,))
        row=queries.members(c,job['id'],limit=10,offset=0)['items'][0]
        assert row['disposition_status']==1 and row['removal_required'] and row['removal_required_reason']=='reopened'


def test_principal_capability_requires_manage_and_igu_role_intersection(client):
    assert client.get('/api/v1/auth/me').json()['can_manage_disposition']
    with db() as c:
        actor(c)
        c.execute('UPDATE roles SET is_information_governance=false WHERE id=1')
    assert not client.get('/api/v1/auth/me').json()['can_manage_disposition']
    assert client.get('/api/v1/disposition/eligibility').status_code==403
    assert client.get('/api/v1/disposition/context').status_code==403


def test_flagged_disposition_translations_remain_drafts_and_cannot_be_published(client):
    from backend.services.api.localization import synchronize_generated_arabic_drafts
    synchronize_generated_arabic_drafts()
    key='disposition.ui.eligibility'
    row=client.get('/api/v1/admin/i18n/messages',params={'language_tag':'ar','key':key,'limit':25}).json()['items'][0]
    result=client.post('/api/v1/admin/i18n/translations/ar/bulk-review-publish',json={'items':[{'message_key':key,'version':row['translation_version']}]},headers={'X-Change-Reason':'Prove flagged drafts remain blocked'})
    assert result.status_code==422
    assert result.json()['detail']['parameters']['invalid'][0]['code']=='generation_quality_attention'


def test_due_filter_api_rejects_offset_free_instants(client):
    assert client.get('/api/v1/disposition/eligibility',params={'due_from':'2025-01-01T00:00:00'}).status_code==422
    assert client.get('/api/v1/disposition/eligibility',params={'due_from':'2025-01-01T00:00:00Z'}).status_code==200


def test_all_filter_categories_sort_directions_and_grouping_are_server_applied(client):
    from backend.services.api.tests.test_disposition_eligibility import make_hold
    with db() as c, c.transaction(force_rollback=True):
        actor(c)
        one,child,*_=ready(c)
        two,_,_,record=ready(c,'transfer_to_external_archive',closed='2021-01-01T00:00:00Z')
        c.execute("INSERT INTO org_units(code,name,parent_org_unit_id) VALUES('SECOND','Other owner',1)")
        from backend.services.api.disposition.eligibility import worker_actor,evaluate_root
        three=c.execute("INSERT INTO aggregations(aggregation_number,title,classification_id,owning_org_unit_id,date_opened,date_closed) VALUES('THIRD','Third root',1,2,'1900-01-01','2010-01-01T00:00:00Z') RETURNING id").fetchone()['id']
        worker_actor(c);evaluate_root(c,three);actor(c)
        c.execute("SELECT set_config('app.vital_status_change_authorized','authorized',true)")
        c.execute('UPDATE aggregations SET is_vital=true WHERE id=%s',(child,))
        make_hold(c,'record',record)
        c.execute('UPDATE security_levels SET prevents_disposition=true WHERE id=(SELECT security_level_id FROM aggregations WHERE id=%s)',(one,))
        assert [r['id'] for r in page(c,vital=True)['items']]==[one]
        assert [r['id'] for r in page(c,held=True)['items']]==[two]
        assert page(c,security=True)['total']==3 and page(c,security=False)['total']==0
        assert [r['id'] for r in page(c,due_to=datetime(2020,1,1,tzinfo=timezone.utc))['items']]==[three]
        assert [r['id'] for r in page(c,owner=2)['items']]==[three]
        for field,expected in [('status',two),('vital',one),('held',two)]:
            assert page(c,sort=field,descending=True)['items'][0]['id']==expected
        assert page(c,sort='due')['items'][0]['id']==three
        assert page(c,sort='due',descending=True)['items'][0]['id']==two
        assert page(c,group_owner=True)['items'][0]['id']==three
        assert page(c,status=3)['items'][0]['final_disposition']=='transfer_to_external_archive'
