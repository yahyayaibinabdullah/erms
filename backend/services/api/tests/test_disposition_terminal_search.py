"""Governance-only terminal search; never restore live access or content."""
import pytest
from fastapi import HTTPException
from backend.services.api import search,crud
from backend.services.api.schemas import SearchRequest
from backend.services.api.disposition import destruction
from backend.services.api.tests.test_disposition_completion import ready
from backend.services.api.tests.test_disposition_membership import db,actor
from backend.services.api.tests.test_disposition_destruction import guarded_fixture


def find(c,table,conditions=None):
    return search.search_rows(c,table,SearchRequest.model_validate({'where':conditions,'limit':25,'offset':0}))


@pytest.mark.parametrize('kind,table,number',[('aggregation','aggregations','aggregation_number'),('record','records','record_number')])
def test_destroyed_identity_retained_but_search_requires_status_and_current_governance(client,monkeypatch,kind,table,number):
    job,root,mgr=ready(monkeypatch)
    with db() as c:
        actor(c)
        row=c.execute('SELECT id,title,'+number+' FROM '+table+' WHERE '+('id=%s' if kind=='aggregation' else 'aggregation_id IN (SELECT disposition_private.unit_ids(%s))')+' ORDER BY id LIMIT 1',(root,)).fetchone()
    assert destruction.process_one(db)
    status={'field':'disposition_status','operator':'eq','value':10}
    identity={'field':'id','operator':'eq','value':row['id']}
    with db() as c:
        actor(c)
        retained=c.execute('SELECT title,'+number+',description FROM '+table+' WHERE id=%s',(row['id'],)).fetchone()
        assert retained=={'title':row['title'],number:row[number],'description':None}
        assert find(c,table,identity)['total']==0
        result=find(c,table,{'and':[status,identity]})
        assert result['total']==1 and result['items'][0]['title']==row['title']
        assert result['items'][0][number]==row[number]
        assert result['items'][0]['effective_assigned_location'] is None and result['items'][0]['effective_current_location'] is None
        assert find(c,table,{'and':[status,{'field':number,'operator':'eq','value':row[number]}]})['total']==1
        detail=destruction.retained(c,kind,row['id'])
        assert detail['title']==row['title'] and detail['resource_number']==row[number]
        with pytest.raises(HTTPException):crud.get_or_404(c,table,row['id'])
        c.execute('UPDATE roles SET is_information_governance=false WHERE id IN (SELECT role_id FROM user_role_assignments WHERE user_id=1)')
        assert not c.execute('SELECT disposition_private.can_manage() allowed').fetchone()['allowed']
        assert find(c,table,{'and':[status,identity]})['total']==0
        with pytest.raises(HTTPException):destruction.retained(c,kind,row['id'])


@pytest.mark.parametrize('status',[11,12])
@pytest.mark.parametrize('kind,table',[('aggregation','aggregations'),('record','records')])
def test_archival_terminal_status_filters_cannot_be_used_by_non_governance(client,monkeypatch,status,kind,table):
    job,root,mgr=ready(monkeypatch)
    with db() as c:
        actor(c)
        assert c.execute('SELECT current_database() name').fetchone()['name'].startswith('erms_messaging_test_acl_')
        # Synthetic archived fixtures only: do not claim to exercise a transfer
        # workflow. User triggers are always restored before testing real reads.
        for target in ('aggregations','records'):
            c.execute('ALTER TABLE '+target+' DISABLE TRIGGER USER')
            try:
                c.execute('UPDATE '+target+' SET disposition_status=%s WHERE '+('id IN (SELECT disposition_private.unit_ids(%s))' if target=='aggregations' else 'aggregation_id IN (SELECT disposition_private.unit_ids(%s))'),(status,root))
            finally:c.execute('ALTER TABLE '+target+' ENABLE TRIGGER USER')
        identity=c.execute('SELECT id FROM '+table+' WHERE '+('id=%s' if kind=='aggregation' else 'aggregation_id IN (SELECT disposition_private.unit_ids(%s))')+' ORDER BY id LIMIT 1',(root,)).fetchone()['id']
        query={'and':[{'field':'disposition_status','operator':'eq','value':status},{'field':'id','operator':'eq','value':identity}]}
        assert find(c,table,query)['total']==1
        c.execute('UPDATE roles SET is_information_governance=false WHERE id IN (SELECT role_id FROM user_role_assignments WHERE user_id=1)')
        assert find(c,table,query)['total']==0
        assert all(item['id']!=identity for item in find(c,table)['items'])
