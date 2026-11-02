"""Desired-effect duplicate guards, current-round scope, and safe picker hints."""
from copy import deepcopy
from uuid import uuid4
import psycopg
import pytest
from backend.services.api.tests.test_disposition_review import save,create,payloads,submit,claim
from backend.services.api.tests.test_disposition_workflow import seeded,person,role,task
from backend.services.api.tests.test_disposition_membership import db,actor,ready,admit
from backend.services.api.disposition import proposals


@pytest.mark.parametrize('index',range(8))
def test_equivalent_effect_is_rejected_at_save_without_history_changes(client,index):
    with db() as c:
        job,root,*_=seeded(c)
        item=payloads(c,root)[index]
        saved=save(c,job,changes=[item])
        duplicate=deepcopy(item);duplicate['reason']='A different author explanation'
        if item['proposal_type']=='add_to_holds':duplicate['proposed_values']['hold_ids'].reverse()
        if item['proposal_type']=='local_retention_override':duplicate['proposed_values']['instructions']='' if item['proposed_values']['instructions'] is None else item['proposed_values']['instructions']
        before=c.execute('SELECT count(*) n FROM event_history').fetchone()['n']
        with pytest.raises(psycopg.Error,match='disposition_proposal_duplicate'),c.transaction():save(c,job,changes=[duplicate])
        assert c.execute('SELECT count(*) n FROM disposition_review_proposals').fetchone()['n']==1
        assert c.execute('SELECT count(*) n FROM event_history').fetchone()['n']==before
        assert saved['changes'][0]['id']


def test_other_reviewer_cannot_duplicate_and_picker_points_to_existing_proposal(client):
    with db() as c:
        job,root,um,fa,*_=seeded(c,fa=True)
        other,*_=ready(c)
        kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active LIMIT 1").fetchone()['id']
        link=c.execute('INSERT INTO aggregation_relationships(relationship_type_id,source_id,target_id) VALUES(%s,%s,%s) RETURNING id',(kind,root,other)).fetchone()['id']
        item=create(c,root,'remove_aggregation_relationship',{'relationship_id':link})
        pid=save(c,job,changes=[item])['changes'][0]['id']
        reviewer=person(c);c.execute('INSERT INTO user_role_assignments(user_id,role_id) VALUES(%s,%s)',(reviewer,fa))
        submit(c,job);actor(c,reviewer);claim(c,job)
        rows=proposals.removal_candidates(c,task(c,job['id'])['id'],acting_role_id=fa,root_id=root,kind='aggregation',target_id=root,limit=25,offset=0)['items']
        assert rows[0]['already_proposed'] and not rows[0]['selectable'] and rows[0]['existing_proposal_id']==pid
        assert proposals.page(c,job['id'],limit=1,offset=0,proposal_id=pid)['items'][0]['id']==pid
        with pytest.raises(psycopg.Error,match='disposition_proposal_duplicate'),c.transaction():save(c,job,acting=fa,changes=[item])
        own=proposals.removal_candidates(c,task(c,job['id'])['id'],acting_role_id=fa,root_id=root,kind='aggregation',target_id=root,limit=1,offset=0,exclude_proposal_id=pid,selected_id=link)['items']
        assert own[0]['selectable'] and not own[0]['already_proposed']


def test_symmetric_creation_reversals_are_duplicates(client):
    with db() as c:
        job,root,*_=seeded(c);other,*_=ready(c)
        kind=c.execute("SELECT id FROM relationship_types WHERE resource_kind='aggregation' AND is_active AND is_symmetric LIMIT 1").fetchone()['id']
        values=dict(direction='incoming',related_aggregation_id=other,relationship_type_id=kind)
        save(c,job,changes=[create(c,root,'create_aggregation_relationship',values)])
        with pytest.raises(psycopg.Error,match='disposition_proposal_duplicate'),c.transaction():
            save(c,job,changes=[create(c,root,'create_aggregation_relationship',{**values,'direction':'outgoing'})])


def test_revision_self_is_allowed_withdrawal_releases_effect_and_atomic_batch_rolls_back(client):
    with db() as c:
        job,root,*_=seeded(c);item=create(c,root)
        with pytest.raises(psycopg.Error,match='disposition_proposal_duplicate'),c.transaction():save(c,job,changes=[item,item])
        assert not c.execute('SELECT 1 FROM disposition_review_proposals').fetchone()
        pid=save(c,job,changes=[item])['changes'][0]['id']
        prop=c.execute('SELECT * FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone()
        save(c,job,changes=[dict(action='revise',proposal_id=pid,expected_version=prop['version'],target_version=item['target_version'],proposed_values={},reason='Refined reason')])
        prop=c.execute('SELECT * FROM disposition_review_proposals WHERE id=%s',(pid,)).fetchone()
        save(c,job,changes=[dict(action='withdraw',proposal_id=pid,expected_version=prop['version'],reason='No longer required'),item])
        assert c.execute("SELECT count(*) n FROM disposition_review_proposals WHERE proposal_state='active'").fetchone()['n']==1


@pytest.mark.parametrize('serializable',[False,True])
def test_idempotent_retry_and_concurrent_saves_cannot_create_duplicates(client,serializable):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    with db() as c:
        job,root,*_=seeded(c);item=create(c,root)
    barrier=Barrier(2)
    def attempt(_):
        try:
            with db() as c:
                if serializable:c.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
                actor(c);barrier.wait(timeout=10)
                return ('saved',save(c,job,changes=[item]))
        except psycopg.Error as error:return ('rejected',error.diag.message_primary)
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(attempt,range(2)))
    assert sum(kind=='saved' for kind,_ in results)==1
    with db() as c:
        actor(c);assert c.execute('SELECT count(*) n FROM disposition_review_proposals').fetchone()['n']==1
        # A committed exact command retry is returned before duplicate insertion.
        from backend.services.api.tests.test_disposition_membership import job_version
        from backend.services.api.tests.test_disposition_review import officer
        t=task(c,job['id']);key=uuid4()
        parameters=dict(task_id=t['id'],expected_version=job_version(c,job['id']),task_version=t['version'],changes=[],acting_role_id=officer(c),command_id=key)
        first=proposals.save(c,**parameters)
        assert proposals.save(c,**parameters)==first


def test_upgrade_preserves_preexisting_duplicate_rows_but_prevents_new_duplicates(client):
    from pathlib import Path
    with db() as c:
        c.execute('DROP TRIGGER disposition_proposal_unique ON disposition_review_proposals')
        c.execute('DROP FUNCTION disposition_private.reject_duplicate_proposal()')
        c.execute('DROP FUNCTION disposition_private.proposal_duplicate_key(jsonb)')
        c.execute('DROP INDEX disposition_proposal_active_round')
        job,root,*_=seeded(c);item=create(c,root)
        save(c,job,changes=[item,item])
        before=c.execute('SELECT to_jsonb(p) data FROM disposition_review_proposals p ORDER BY id').fetchall()
        sql=(Path(__file__).resolve().parents[4]/'database/migrations/085_prevent_duplicate_review_proposals.sql').read_text()
        c.execute(sql.removeprefix('BEGIN;\n').removesuffix('COMMIT;\n'),prepare=False)
        assert c.execute('SELECT to_jsonb(p) data FROM disposition_review_proposals p ORDER BY id').fetchall()==before
        with pytest.raises(psycopg.Error,match='disposition_proposal_duplicate'),c.transaction():save(c,job,changes=[item])


def test_api_rejects_duplicate_with_readable_conflict_and_preserves_saved_proposal(client):
    from backend.services.api.tests.test_disposition_review import officer
    from backend.services.api.tests.test_disposition_membership import job_version
    with db() as c:
        job,root,*_=seeded(c);item=create(c,root);t=task(c,job['id']);acting=officer(c);version=job_version(c,job['id'])
    path=f"/api/v1/disposition/tasks/{t['id']}/review-work"
    payload=dict(command_id=str(uuid4()),acting_role_id=acting,task_version=t['version'],changes=[item])
    headers={'If-Match':str(version),'X-CSRF-Token':client.cookies.get('erms_csrf')}
    first=client.post(path,json=payload,headers=headers);assert first.status_code==200,first.text
    payload.update(command_id=str(uuid4()),task_version=first.json()['task_version'])
    headers['If-Match']=str(first.json()['job_version'])
    second=client.post(path,json=payload,headers=headers)
    assert second.status_code==409 and second.json()=={'detail':{'code':'disposition_proposal_duplicate'}}
    with db() as c:assert c.execute('SELECT count(*) n FROM disposition_review_proposals').fetchone()['n']==1
