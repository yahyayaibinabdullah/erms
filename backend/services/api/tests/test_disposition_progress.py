"""Round projection integration; disposable database runner only."""
from backend.services.api.disposition import progress,queries
from backend.services.api.tests.test_disposition_review import db,seeded,submit,claim,decide


def test_return_resubmit_and_repeated_rounds(client):
    with db() as c:
        job,*_=seeded(c,fa=True)
        c.execute("UPDATE users SET translations=jsonb_build_object('ar',jsonb_build_object('name','مراجع الاختبار')) WHERE id=1")
        read=lambda **kw:progress.page(c,queries.job(c,job['id']),**kw)
        assert read()['items']==[]
        assert read()['round_number']==1
        for number in (1,2):
            submit(c,job);claim(c,job);decide(c,job)
            claim(c,job);decide(c,job,'rejected','Correct the proposed membership')
            result=read(limit=1,language_tag='ar')
            assert result['round_number']==number+1
            row=result['items'][0]
            assert row['actor_name']=='مراجع الاختبار'
            assert all(d['actor_name']=='مراجع الاختبار' for d in row['decisions'])
            assert row['round_number']==number
            assert [d['review_stage'] for d in row['decisions']]==['file_administrator_review','unit_manager_review']
            assert row['decisions'][-1]['reason']=='Correct the proposed membership'
            assert not {'membership_snapshot','proposal_snapshot'} & row.keys()
        assert result['has_more']
        assert read(limit=1,offset=1)['items'][0]['round_number']==1
        submit(c,job)
        assert read()['round_number']==3
        assert len(read()['items'])==2
    response=client.get(f"/api/v1/disposition/jobs/{job['id']}/workflow-progress",params={'limit':1})
    assert response.status_code==200,response.text
    assert response.json()['has_more']
    assert client.get(f"/api/v1/disposition/jobs/{job['id']}/workflow-progress",params={'limit':26}).status_code==422


def test_round_number_projection():
    for stage in ('officer_correction','manager_correction'):
        assert progress.round_number({'current_review_round':2,'workflow_stage':stage})==3
    assert progress.round_number({'current_review_round':2,'workflow_stage':'unit_manager_review'})==2


def test_redacted_round_does_not_fetch_decisions(monkeypatch):
    monkeypatch.setattr(progress,'require_workspace',lambda *a:None)
    class Cursor:
        def fetchall(self):return [{'id':7,'visible':False,'submission_reason':'private','actor_name':'private'}]
    class Connection:
        def __init__(self):self.calls=0
        def execute(self,*a):self.calls+=1;return Cursor()
    connection=Connection()
    result=progress.page(connection,{'id':1,'current_review_round':1,'workflow_stage':'officer_correction'})
    assert result['items']==[{'id':7,'redacted':True}]
    assert connection.calls==1
