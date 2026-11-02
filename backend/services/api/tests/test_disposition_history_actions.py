"""Action pagination preserves all authorized records; disposable database only."""
from uuid import uuid4
import pytest
from psycopg.types.json import Jsonb
from fastapi import HTTPException
from backend.services.api.disposition import queries
from backend.services.api.tests.test_disposition_review import db,actor,seeded,save,create,submit,claim,decide,person
from backend.services.api.tests.test_disposition_membership import setup


def rows(c,job,**kwargs):
    return queries.history(c,job['id'],limit=kwargs.pop('limit',25),offset=kwargs.pop('offset',0),grouped=True,**kwargs)


def event(c,job,operation,metadata):
    return c.execute("SELECT append_domain_event('disposition_job',%s,%s,%s,'History fixture') id",(job['id'],operation,Jsonb(metadata))).fetchone()['id']


def test_resubmission_and_carried_proposals_are_one_action_with_all_original_events(client):
    with db() as c:
        job,root,*_=seeded(c,'simplified');c.commit();actor(c)
        save(c,job,changes=[create(c,root),create(c,root,'local_retention_override',{'current_period_years':1,'intermediate_period_years':2,'final_disposition':'destruction','instructions':None})]);c.commit();actor(c)
        submit(c,job,'Round one');c.commit();actor(c)
        claim(c,job);c.commit();actor(c)
        decide(c,job,'rejected','Correct and resubmit');c.commit();actor(c)
        submit(c,job,'Round two');c.commit();actor(c)
        before=c.execute('SELECT count(*) n,max(id) last FROM event_history').fetchone()
        result=rows(c,job)
        submissions=[r for r in result['items'] if r['operation']=='REVIEW_SUBMIT']
        assert len(submissions)==2
        second=next(r for r in submissions if r['metadata']['after']['round_number']==2)
        assert second['entity_type']=='disposition_review_round'
        assert 'membership_snapshot' not in str(second) and 'proposal_snapshot' not in str(second)
        details=queries.history_action_events(c,job['id'],second['id'],limit=2,offset=0)
        assert details['total']==second['history_group']['event_count'] and details['total']>5
        collected=[]
        for offset in range(0,details['total'],2):
            collected+=queries.history_action_events(c,job['id'],second['id'],limit=2,offset=offset)['items']
        assert len({r['id'] for r in collected})==details['total']
        assert sum(r['operation']=='REVIEW_PROPOSAL_CARRIED' for r in collected)==2
        assert sum(r['operation']=='REVIEW_SUBMIT' for r in collected)==5
        assert len({r['transaction_id'] for r in collected})==1
        assert next(r for r in collected if r['operation']=='TASK_ROUTED')
        assert any(r['entity_type']=='disposition_review_decision' for r in result['items'])
        assert c.execute('SELECT count(*) n,max(id) last FROM event_history').fetchone()==before
        raw=queries.history(c,job['id'],limit=100,offset=0)
        assert raw['total']>result['total'] and all('history_group' not in r for r in raw['items'])


def test_action_pages_are_stable_and_commands_in_same_transaction_remain_separate(client):
    with db() as c:
        job,*_=seeded(c,'simplified')
        keys=[str(uuid4()),str(uuid4())]
        for key in keys:
            for _ in range(3):event(c,job,'REVIEW_SAVE',{'command_id':key,'after':{'job_id':job['id']}})
        # Several commands share this fixture transaction. No guessing which
        # command caused an old event without correlation metadata.
        orphan=event(c,job,'REVIEW_NOTES_SAVED',{'after':{'job_id':job['id']}})
        all_rows=rows(c,job,limit=100)
        summaries=[r for r in all_rows['items'] if r['metadata'].get('command_id') in keys]
        assert len(summaries)==2 and all(r['history_group']['event_count']==3 for r in summaries)
        assert next(r for r in all_rows['items'] if r['id']==orphan)['history_group']['event_count']==1
        paged=[rows(c,job,limit=1,offset=i)['items'][0]['id'] for i in range(all_rows['total'])]
        assert paged==[r['id'] for r in all_rows['items']] and len(set(paged))==len(paged)


def test_history_group_never_crosses_job_actor_source_or_request(client):
    with db() as c:
        job,*_=seeded(c,'simplified');other=setup(c)
        key=str(uuid4())
        first=event(c,job,'REVIEW_SAVE',{'command_id':key})
        event(c,other,'REVIEW_SAVE',{'command_id':key})
        c.execute("SELECT set_config('app.event_source','api_client',true)")
        sourced=event(c,job,'REVIEW_SAVE',{'command_id':key})
        c.execute("SELECT set_config('app.request_id',%s,true)",(str(uuid4()),))
        requested=event(c,job,'REVIEW_SAVE',{'command_id':key})
        other_user=person(c);actor(c,user=other_user)
        other_actor=event(c,job,'REVIEW_SAVE',{'command_id':key})
        actor(c)
        for identity in (first,sourced,requested,other_actor):
            detail=queries.history_action_events(c,job['id'],identity,limit=25,offset=0)
            assert detail['total']==1 and detail['items'][0]['id']==identity
        with pytest.raises(HTTPException) as error:
            queries.history_action_events(c,other['id'],first,limit=25,offset=0)
        assert error.value.status_code==404


def test_grouped_http_and_details_contract(client):
    with db() as c:
        job,*_=seeded(c,'simplified');c.commit();actor(c)
        key=str(uuid4())
        event(c,job,'REVIEW_SAVE',{'command_id':key})
        identity=event(c,job,'REVIEW_SAVE',{'command_id':key})
    response=client.get(f"/api/v1/disposition/jobs/{job['id']}/history",params={'grouped':'true','limit':1})
    assert response.status_code==200,response.text
    summary=response.json()['items'][0]
    assert summary['id']==identity and summary['history_group']['event_count']==2
    response=client.get(f"/api/v1/disposition/jobs/{job['id']}/history/{identity}/events",params={'limit':1})
    assert response.status_code==200,response.text
    assert response.json()['total']==2 and len(response.json()['items'])==1
    assert client.get(f"/api/v1/disposition/jobs/{job['id']}/history/{identity}/events",params={'limit':51}).status_code==422


def test_hidden_proposal_event_remains_redacted_inside_its_action(client):
    with db() as c:
        job,root,*_=seeded(c,'simplified')
        save(c,job,changes=[create(c,root)]);c.commit();actor(c)
        proposal=c.execute('SELECT * FROM disposition_review_proposals WHERE job_id=%s',(job['id'],)).fetchone()
        key=str(uuid4())
        visible=event(c,job,'REVIEW_SAVE',{'command_id':key})
        hidden={**proposal,'current_values':{'relationship':{'resource_kind':'aggregation','source_id':root,'target_id':9999999}}}
        # A historical relationship endpoint is now unavailable. No current
        # proposal edit or database policy override is needed to exercise this.
        import json
        hidden=json.loads(json.dumps(hidden,default=str))
        identity=c.execute("SELECT append_domain_event('disposition_review_proposal',%s,'REVIEW_PROPOSAL_REVISED',%s,'Hidden historical reference') id",(proposal['id'],Jsonb({'command_id':key,'before':None,'after':hidden}))).fetchone()['id']
        result=rows(c,job)
        summary=next(r for r in result['items'] if r['id']==visible)
        assert summary['history_group']['event_count']==2
        detail=queries.history_action_events(c,job['id'],visible,limit=25,offset=0)
        assert detail['total']==2 and detail['items'][0]['id']==visible
        redacted=next(r for r in detail['items'] if r['id']==identity)
        assert redacted['metadata']['redacted'] and redacted['display_references']=={} and redacted['reason'] is None
        assert '9999999' not in str(result)+str(detail)
        c.execute("""INSERT INTO aggregations(id,aggregation_number,title,classification_id,owning_org_unit_id,date_opened)
          SELECT 9999999,'RESTORED-RELATED','Restored endpoint',classification_id,owning_org_unit_id,date_opened
          FROM aggregations WHERE id=%s""",(root,))
        fresh=queries.history_action_events(c,job['id'],visible,limit=25,offset=0)
        assert not next(r for r in fresh['items'] if r['id']==identity)['metadata'].get('redacted')


def test_large_action_is_one_summary_and_details_remain_bounded(client):
    with db() as c:
        job,*_=seeded(c,'simplified');c.commit();actor(c)
        key=str(uuid4())
        expected=[event(c,job,'REVIEW_SAVE',{'command_id':key}) for _ in range(123)]
        summary=rows(c,job,limit=1)['items'][0]
        assert summary['history_group']['event_count']==123
        assert len(str(summary))<5000
        first=queries.history_action_events(c,job['id'],summary['id'],limit=50,offset=0)
        last=queries.history_action_events(c,job['id'],summary['id'],limit=50,offset=100)
        assert first['total']==last['total']==123
        assert [r['id'] for r in first['items']]==expected[:50]
        assert [r['id'] for r in last['items']]==expected[100:]
